"""Main window for the Speech-to-Text Transcriber GUI.
3-step flow: Select File → Choose Model → Transcribe
"""

import logging
import sys
from typing import cast

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt5.QtGui import QCloseEvent, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDesktopWidget,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from gui import i18n, motion, theme
from gui.checkbox_style import PaintedCheckboxStyle
from gui.crash_dialog import CrashDialog
from gui.crash_handler import get_crash_bridge
from gui.focus import KeyboardFocusTracker
from gui.i18n import t
from gui.presenters import build_transcription_request
from gui.stepper import StepIndicator
from gui.steps import FileSelectStep, ModelSelectStep, Step, TranscriptionStep
from gui.theme import COLORS, Fonts, Motion
from gui.threads import CalibrationThread, TranscriptionThread
from gui.widgets import IconTextButton, make_label
from gui.window_chrome import TitleBarColorizer
from hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)


# High-DPI: without these, Windows bitmap-stretches the window at 125%/150%
# (blurry). AA_EnableHighDpiScaling scales geometry in logical pixels,
# AA_UseHighDpiPixmaps requests pixmaps at the real resolution, and
# PassThrough stops Qt rounding 1.25/1.5 to a whole factor. They are class
# attributes that only work before QApplication is constructed, so they run
# here at import time, which precedes that in every entry point.
QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def _is_text_entry_widget(widget: QWidget | None) -> bool:
    """Whether Enter here confirms typed input rather than advancing the step -
    true for every native text-entry widget.
    """
    return isinstance(widget, (QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox))


class MainWindow(QMainWindow):
    """Main application window - lightweight tool interface."""

    # How long an armed Cancel stays armed: long enough for a deliberate second
    # press, short enough not to look dangerous after an accidental one.
    CANCEL_ARM_TIMEOUT_MS = 3000

    def __init__(self) -> None:
        super().__init__()
        logger.info("Initializing MainWindow...")

        self.setWindowTitle(t("app_title"))
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.move(100, 50)
        # Resizable with a measured minimum (config's GUI_WINDOW_MIN_HEIGHT);
        # a fixed size once clipped step 3's result panel.
        self.resize(config.GUI_WINDOW_WIDTH, config.GUI_WINDOW_HEIGHT)
        self.setMinimumSize(config.GUI_WINDOW_MIN_WIDTH, config.GUI_WINDOW_MIN_HEIGHT)
        # Main window background is set by theme.app_stylesheet() on the
        # QApplication (see main()) rather than here per-instance.

        self.hardware = HardwareDetector()
        self.current_step = Step.FILE_SELECT
        # The running page slide and its page, if any - see _slide_page_in.
        self._page_slide: tuple[QParallelAnimationGroup, QWidget] | None = None
        self.transcription_thread: TranscriptionThread | None = None
        self.selected_files: list[str] = []
        self.selected_model: str | None = None
        # Total across every selected file - what should drive the model
        # recommendation, since the estimate has to cover the whole batch.
        self.audio_duration: int = 0
        self.calibration_thread: CalibrationThread | None = None

        # Two-press Cancel state (see _on_cancel_clicked). A single-shot
        # timer rather than something driven off _tick or similar: arming
        # has nothing to do with the transcription's own progress, it's
        # purely "how long since the first click", so it gets its own
        # independent clock.
        self._cancel_armed = False
        self._cancel_arm_timer = QTimer(self)
        self._cancel_arm_timer.setSingleShot(True)
        self._cancel_arm_timer.setInterval(self.CANCEL_ARM_TIMEOUT_MS)
        self._cancel_arm_timer.timeout.connect(self._disarm_cancel)

        # Build UI
        self._init_ui()

        self._init_shortcuts()

        # Center on screen
        self.center_on_screen()

        # Catches whatever install_global_exception_hook() routes here (see
        # app.py) - anything that would otherwise have crashed with no
        # user-visible trace.
        get_crash_bridge().crashed.connect(self._on_unhandled_crash)

        # Kick off the one-time hardware calibration in the background, if no
        # cached result was already loaded by HardwareDetector. Runs while
        # the user is still picking a file, so real numbers are usually
        # ready before they reach the model-select step.
        if self.hardware.tiny_seconds_per_audio_second is None:
            calibration_device, _ = self.hardware.get_device_recommendation()
            self.calibration_thread = CalibrationThread(self.hardware.cpu_count, calibration_device)
            self.calibration_thread.calibrated.connect(self._on_calibration_done)
            self.calibration_thread.failed.connect(self._on_calibration_failed)
            self.calibration_thread.start()

        logger.info("✓ MainWindow ready")

    def _on_calibration_done(self, tiny_seconds_per_audio_second: float) -> None:
        """Apply a finished background calibration and refresh any visible estimates."""
        self.hardware.set_calibration(tiny_seconds_per_audio_second)
        self.model_step.update_audio_duration(self.audio_duration)
        logger.debug("Refreshed model time estimates with calibrated values")

    def _on_unhandled_crash(self, message: str, traceback_text: str) -> None:
        """Show CrashDialog for a caught exception. Defensive: it is already
        logged, so a bug in the dialog must not crash the crash handler.
        """
        try:
            CrashDialog(self, message, traceback_text).exec_()
        except Exception as e:
            print(f"Crash dialog itself failed: {e}", file=sys.stderr)
            logger.critical(f"Crash dialog itself failed: {e}", exc_info=True)

    def _on_calibration_failed(self, message: str) -> None:
        logger.warning(f"Hardware calibration failed, keeping placeholder estimates: {message}")
        # The "still measuring" note on step 2 (see ModelSelectStep) would
        # otherwise stay up forever, quietly promising a real number that's
        # never coming now that the benchmark itself has failed - swap it
        # for a permanent, honest "these are rough" resting state instead.
        self.model_step.mark_calibration_unmeasured()

    def center_on_screen(self) -> None:
        """Center window on screen."""
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        logger.debug(f"Window centered at ({x}, {y})")

    def _init_shortcuts(self) -> None:
        """Window-level shortcuts (Enter, Escape). They fire anywhere in the
        window; the guards in each handler keep them from firing where they
        should not.
        """
        self._shortcut_browse = QShortcut(QKeySequence("Ctrl+O"), self)
        self._shortcut_browse.activated.connect(self._on_browse_shortcut)

        self._shortcut_toggle_language = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self._shortcut_toggle_language.activated.connect(self._toggle_language)

        # Return AND Enter - the numpad key sends Qt.Key_Enter, the main
        # keyboard's sends Qt.Key_Return, and QKeySequence("Return") only
        # matches one of them.
        self._shortcut_advance_return = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self._shortcut_advance_return.activated.connect(self._on_advance_shortcut)
        self._shortcut_advance_enter = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        self._shortcut_advance_enter.activated.connect(self._on_advance_shortcut)

        self._shortcut_back = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._shortcut_back.activated.connect(self._on_escape_shortcut)

    def _on_browse_shortcut(self) -> None:
        """Ctrl+O: open the file-picker dialog. Only meaningful on step 1."""
        if self.current_step == Step.FILE_SELECT:
            self.file_step.browse_for_files()

    def _on_advance_shortcut(self) -> None:
        """Enter: click Next - unless a text field has focus (Enter confirms
        the value there). Gated on Next being visible and enabled, which
        already encodes every case where Enter should do nothing. On step 1
        the drop zone takes Enter first to open the file dialog.
        """
        focused = QApplication.focusWidget()
        if _is_text_entry_widget(focused):
            return
        if self.next_btn.isVisible() and self.next_btn.isEnabled():
            self.next_btn.click()

    def _on_escape_shortcut(self) -> None:
        """Escape: Back on step 2; on step 3 the same two-press Cancel as the
        button, so one stray key cannot throw away a long run. Nothing on
        step 1, which has nothing behind it.
        """
        if self.current_step == Step.MODEL_SELECT:
            self._go_back()
        elif self.current_step == Step.TRANSCRIPTION:
            self._on_cancel_clicked()

    def _init_ui(self) -> None:
        """Initialize UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_header(main_layout)

        i18n.language_manager.language_changed.connect(self._on_language_changed)

        # The step indicator, between header and pages: chrome framing the
        # current page (see gui/stepper.py).
        self.step_indicator = StepIndicator()
        main_layout.addWidget(self.step_indicator)

        self._build_content_area(main_layout)
        self._build_nav_bar(main_layout)

        self._next_btn_mode = "next"
        self._retranslate_chrome()
        self._wire_tab_order()

    def _build_header(self, main_layout: QVBoxLayout) -> None:
        """The 50px title bar: gradient app title, optically centered between
        the language toggle and a same-width invisible spacer.
        """
        # Header
        header = QFrame()
        header.setObjectName("header")
        header.setStyleSheet(theme.header_qss("header"))
        header.setFixedHeight(50)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(10)

        # Title - centered, gradient-filled text (the one deliberate use of a
        # gradient in this theme, as a brand accent rather than a UI backdrop).
        # A pixmap, re-rendered on language switch. Rendering it here too, not
        # only in _retranslate_chrome, is load-bearing: without it the title
        # and other bold text rasterize differently (pixel-diffed).
        self.title_label = QLabel()
        self._render_title()
        self.title_label.setStyleSheet("background: transparent;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # EN/HE toggle at the trailing edge of the header (label shows the
        # TARGET language). A same-width invisible spacer at the leading edge
        # keeps the title optically centered.
        lang_btn_width = 52
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedSize(lang_btn_width, 30)
        self.lang_btn.setFont(Fonts.CAPTION_BOLD)
        self.lang_btn.setStyleSheet(theme.button_secondary_qss(padding="2px 4px"))
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Its visible text is a language code, meaningless to a screen
        # reader - hence the static accessible name and tooltip.
        self.lang_btn.setAccessibleName(t("toggle_language_name"))
        self.lang_btn.setToolTip(t("toggle_language_tooltip"))
        self.lang_btn.clicked.connect(self._toggle_language)

        header_spacer = QWidget()
        header_spacer.setFixedWidth(lang_btn_width)
        header_spacer.setStyleSheet("background: transparent;")

        header_layout.addWidget(header_spacer)
        header_layout.addStretch()
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.lang_btn)
        main_layout.addWidget(header)

    def _build_content_area(self, main_layout: QVBoxLayout) -> None:
        """The stacked widget holding the three wizard steps, and the wiring
        that turns each step's own signal into a MainWindow transition.
        """
        # Content area
        content_widget = QWidget()
        content_widget.setStyleSheet(theme.frame_bg_qss("bg_primary"))
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Stacked widget for steps
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        # Create steps
        self.file_step = FileSelectStep(self.hardware)
        self.file_step.files_selected.connect(self._on_files_selected)

        self.model_step = ModelSelectStep(self.hardware)
        self.model_step.model_selected.connect(self._on_model_selected)

        self.transcription_step = TranscriptionStep()

        self.stacked_widget.addWidget(self.file_step)
        self.stacked_widget.addWidget(self.model_step)
        self.stacked_widget.addWidget(self.transcription_step)

        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_widget)

    def _build_nav_bar(self, main_layout: QVBoxLayout) -> None:
        """The Back/Cancel/Next bar along the bottom, shared by all three
        steps rather than repeated inside each one.
        """
        # Navigation bar
        nav_widget = QFrame()
        nav_widget.setObjectName("navBar")
        nav_widget.setStyleSheet(theme.nav_bar_qss("navBar"))
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setSpacing(8)

        # Back and Next are given the same fixed size - minimum-size alone
        # lets each button grow to fit its own text/icon, so their rendered
        # widths drifted apart (e.g. "  Back" + icon vs "Next" + icon). Wide
        # enough for next_btn's longest state too ("New File" + icon).
        nav_btn_size = (130, 36)

        self._build_back_and_cancel(nav_layout, nav_btn_size)

        nav_layout.addStretch()

        self._build_next_button(nav_layout, nav_btn_size)

        main_layout.addWidget(nav_widget)

    def _build_back_and_cancel(
        self, nav_layout: QHBoxLayout, nav_btn_size: tuple[int, int]
    ) -> None:
        """Back and Cancel share the leading nav slot - only ever one of them
        is visible - plus the label that explains Cancel's armed state.
        """
        # Back button (text/icon set per language by _retranslate_chrome).
        # IconTextButton draws its own label so the icon side can be chosen
        # visually, independent of layout direction (see gui/widgets.py).
        self.back_btn = IconTextButton()
        self.back_btn.setFixedSize(*nav_btn_size)
        self.back_btn.setFont(Fonts.BODY_BOLD)
        self.back_btn.setStyleSheet(theme.button_secondary_qss())
        self.back_btn.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.hide()
        nav_layout.addWidget(self.back_btn)

        # Cancel: shown only on step 3, in Back's slot; returns to Choose
        # Model. Two-press (see _on_cancel_clicked). Its label stays "Cancel"
        # when armed - every longer armed label overflowed the fixed size in
        # some language - and cancel_confirm_label explains instead.
        self.cancel_btn = IconTextButton()
        self.cancel_btn.setFixedSize(*nav_btn_size)
        self.cancel_btn.setFont(Fonts.BODY_BOLD)
        self.cancel_btn.setStyleSheet(theme.button_secondary_qss())
        self.cancel_btn.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.hide()
        nav_layout.addWidget(self.cancel_btn)

        # Explains the armed state in words, next to a button whose own
        # label has no room to (see the comment above cancel_btn). Free-
        # floating in the nav bar rather than a fixed width because there's
        # nothing on its other side to stay symmetric with - Back is
        # already hidden whenever Cancel is visible.
        self.cancel_confirm_label = make_label(font=Fonts.CAPTION, color="error")
        self.cancel_confirm_label.hide()
        nav_layout.addWidget(self.cancel_confirm_label)

    def _build_next_button(self, nav_layout: QHBoxLayout, nav_btn_size: tuple[int, int]) -> None:
        """The one button that advances the wizard, whatever it currently
        says.
        """
        # Next button (text/icon set by _set_next_button_mode)
        self.next_btn = IconTextButton()
        self.next_btn.setFixedSize(*nav_btn_size)
        self.next_btn.setFont(Fonts.BODY_BOLD)
        self.next_btn.setStyleSheet(theme.button_primary_qss())
        self.next_btn.set_text_colors(COLORS["bg_primary"], disabled=COLORS["text_tertiary"])
        # One connection, dispatching on next_btn's current role.
        self.next_btn.clicked.connect(self._on_next_clicked)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

    def _wire_tab_order(self) -> None:
        """One Tab chain in visual order: language toggle, each step's own
        chain, then the nav bar. Safe across all steps at once, since Qt's
        Tab skips hidden widgets.
        """
        first_model = next(iter(config.MODELS))
        last_model = list(config.MODELS)[-1]
        self.setTabOrder(self.lang_btn, self.file_step.drop_zone)
        self.setTabOrder(self.file_step.drop_zone, self.model_step.model_radios[first_model])
        self.setTabOrder(
            self.model_step.model_radios[last_model], self.model_step.speakers_minus_btn
        )
        self.setTabOrder(self.model_step.speakers_minus_btn, self.model_step.speakers_plus_btn)
        self.setTabOrder(self.model_step.speakers_plus_btn, self.model_step.terms_button)
        self.setTabOrder(self.model_step.terms_button, self.back_btn)
        self.setTabOrder(self.back_btn, self.cancel_btn)
        self.setTabOrder(self.cancel_btn, self.transcription_step.open_button)
        self.setTabOrder(self.transcription_step.open_button, self.transcription_step.folder_button)
        self.setTabOrder(self.transcription_step.folder_button, self.next_btn)
        self.setTabOrder(self.next_btn, self.lang_btn)

    def _render_title(self) -> None:
        self.title_label.setPixmap(
            theme.gradient_text_pixmap(
                t("app_title"), Fonts.SUBTITLE_BOLD, dpr=self.devicePixelRatioF()
            )
        )

    def _retranslate_chrome(self) -> None:
        """(Re-)apply window title, header, and nav button text/icons/directions."""
        self.setWindowTitle(t("app_title"))
        self._render_title()
        # Toggle shows the language it switches TO.
        self.lang_btn.setText("עב" if i18n.get_language() == "en" else "EN")
        self.lang_btn.setAccessibleName(t("toggle_language_name"))
        self.lang_btn.setToolTip(t("toggle_language_tooltip"))

        rtl = i18n.is_rtl()
        # Back's arrow points against the reading direction, on the leading
        # side of the text: [← Back] mirrors to [חזרה →].
        self.back_btn.setText(t("nav_back"))
        self.back_btn.setAccessibleName(t("nav_back"))
        self.back_btn.set_icon_spec(
            "arrow_right" if rtl else "arrow_left", side="right" if rtl else "left"
        )

        # Cancel's x sits on the leading side of the text in both languages.
        self.cancel_btn.setText(t("nav_cancel"))
        self.cancel_btn.setAccessibleName(t("nav_cancel"))
        self.cancel_btn.set_icon_spec("x", side="right" if rtl else "left")
        # Kept up to date even while hidden, so it's correct the instant
        # _set_cancel_armed_visual shows it - no separate re-render path
        # needed for "language changed while armed".
        self.cancel_confirm_label.setText(t("cancel_confirm_hint"))

        self._set_next_button_mode(self._next_btn_mode)

    def _set_next_button_mode(self, mode: str) -> None:
        """Configure next_btn for its current role: "next" (forward arrow on
        the trailing side, pointing along the reading direction) or
        "new_file" (reset action after completion - plus-file icon on the
        leading side, no directional claim).
        """
        self._next_btn_mode = mode
        rtl = i18n.is_rtl()
        if mode == "new_file":
            # Reset action: plus-file icon on the leading side of the text.
            self.next_btn.setText(t("nav_new_file"))
            self.next_btn.setAccessibleName(t("nav_new_file"))
            self.next_btn.set_icon_spec("file_plus", side="right" if rtl else "left")
        else:
            # Forward arrow on the trailing side of the text, pointing along
            # the reading direction: [Next →] mirrors to [← הבא].
            self.next_btn.setText(t("nav_next"))
            self.next_btn.setAccessibleName(t("nav_next"))
            self.next_btn.set_icon_spec(
                "arrow_left" if rtl else "arrow_right", side="left" if rtl else "right"
            )

    def _toggle_language(self) -> None:
        i18n.set_language("he" if i18n.get_language() == "en" else "en")

    def _on_language_changed(self, lang: str) -> None:
        """Apply app-wide layout direction and re-render every visible string."""
        from PyQt5.QtWidgets import QApplication

        # isinstance, not "is not None": instance() is typed as the
        # QCoreApplication base, which has no layout direction at all. A
        # console-only application could never be running this window.
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if lang == "he" else Qt.LayoutDirection.LeftToRight
            )
        self._retranslate_chrome()
        self.step_indicator.retranslate()
        for i in range(self.stacked_widget.count()):
            # Every page in this stack is one of the three wizard steps (see
            # _build_content_area) and each defines retranslate(); they share
            # no base class beyond QFrame, and widget() is typed Optional only
            # because its C++ signature returns a pointer.
            page = cast(
                "FileSelectStep | ModelSelectStep | TranscriptionStep",
                self.stacked_widget.widget(i),
            )
            page.retranslate()
        # The RTL/LTR flip relocates the buttons (the toggle jumps to the
        # opposite side of the header) without Qt sending them a Leave
        # event, so the clicked button keeps its :hover styling until the
        # mouse happens to pass over it again. Clear the stale under-mouse
        # flag and re-polish so hover state matches reality.
        for btn in self.findChildren(QPushButton):
            btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            # style() is typed Optional and is only ever None for a widget
            # whose C++ side is already gone - nothing to re-polish there.
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)
            btn.update()

    def _on_files_selected(self, file_paths: list[str], total_duration: int) -> None:
        """Handle the file list changing (add, remove, or a folder drop)."""
        self.selected_files = list(file_paths)
        self.audio_duration = total_duration
        # Not just "are there files": while a length is still being read its
        # duration is a placeholder, and a run started now would weight its
        # progress and size its time estimate against numbers that are not
        # real yet. files_selected is re-emitted as each probe lands, so this
        # enables itself the moment the last one does.
        self.next_btn.setEnabled(bool(self.selected_files) and not self.file_step.is_probing)
        logger.debug(f"Files selected: {len(self.selected_files)} file(s), {total_duration}s total")

    def _on_model_selected(self, model: str) -> None:
        """Handle model selection."""
        self.selected_model = model
        self.next_btn.setEnabled(True)
        logger.debug(f"Model selected: {model}")

    def _set_step(
        self,
        step: Step,
        *,
        back_visible: bool,
        cancel_visible: bool,
        next_visible: bool,
        next_enabled: bool = False,
        next_mode: str = "next",
        focus_widget: QWidget | None = None,
    ) -> None:
        """The one place every step change goes through: current_step, the
        page, Back/Cancel/Next visibility and state, next_btn's role, seeded
        focus, the step indicator. Step-specific work (starting a run,
        resetting step 1) stays with the callers.
        """
        self.current_step = step
        previous = self.stacked_widget.currentIndex()
        self.stacked_widget.setCurrentWidget(self.stacked_widget.widget(step.value))
        if step.value != previous:
            self._slide_page_in(step.value > previous)

        self.back_btn.setVisible(back_visible)
        if back_visible:
            self.back_btn.setEnabled(True)

        self.cancel_btn.setVisible(cancel_visible)
        # Every step change starts with an unarmed Cancel.
        self._disarm_cancel()

        self._set_next_button_mode(next_mode)
        self.next_btn.setVisible(next_visible)
        self.next_btn.setEnabled(next_enabled)

        if focus_widget is not None:
            focus_widget.setFocus(Qt.FocusReason.OtherFocusReason)

        self.step_indicator.set_current(step)
        logger.debug(f"Navigated to: {step}")

    def _slide_page_in(self, forward: bool) -> None:
        """Fade the new page in from the side it came from (mirrored in Hebrew).

        Visual only - the page is already current and focused. The opacity
        effect comes off at the end, or every repaint of the page would keep
        going through an offscreen pixmap.
        """
        self._end_page_slide()
        if not motion.animations_enabled() or not self.isVisible():
            return
        page = self.stacked_widget.currentWidget()
        if page is None:
            return
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        dx = Motion.PAGE_SLIDE_PX * (1 if forward else -1) * (-1 if rtl else 1)

        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(effect, b"opacity", group)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(page, b"pos", group)
        slide.setStartValue(QPoint(dx, 0))
        slide.setEndValue(QPoint(0, 0))
        for animation in (fade, slide):
            animation.setDuration(Motion.PAGE_MS)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(animation)
        group.finished.connect(self._end_page_slide)
        self._page_slide = (group, page)
        group.start()

    def _end_page_slide(self) -> None:
        """Stop any page slide and leave its page exactly where it belongs."""
        if self._page_slide is None:
            return
        group, page = self._page_slide
        self._page_slide = None
        group.stop()
        group.deleteLater()
        page.setGraphicsEffect(None)
        page.move(0, 0)

    def _on_next_clicked(self) -> None:
        """next_btn's click: "next" advances, "new_file" (after a run) resets."""
        if self._next_btn_mode == "new_file":
            self._reset()
        else:
            self._go_next()

    def _go_back(self) -> None:
        """Go to previous step."""
        if self.current_step == Step.MODEL_SELECT:
            self._set_step(
                Step.FILE_SELECT,
                back_visible=False,
                cancel_visible=False,
                next_visible=True,
                next_enabled=bool(self.selected_files) and not self.file_step.is_probing,
            )

    def _go_next(self) -> None:
        """Go to next step."""
        if self.current_step == Step.FILE_SELECT:
            # Refresh time estimates in place instead of rebuilding the widget.
            self.model_step.update_audio_duration(self.audio_duration)
            # A model is always pre-selected (the recommended one), so carry
            # that selection over instead of leaving Next disabled until the
            # user re-clicks an already-checked radio button.
            self.selected_model = self.model_step.selected_model

            self._set_step(
                Step.MODEL_SELECT,
                back_visible=True,
                cancel_visible=False,
                next_visible=True,
                next_enabled=self.selected_model is not None,
            )

        elif self.current_step == Step.MODEL_SELECT:
            if not self.selected_model:
                QMessageBox.warning(self, t("no_model_title"), t("no_model_body"))
                return

            # Proceed to transcription once the model is selected.
            self._start_transcription()

    def _start_transcription(self) -> None:
        """Start transcription thread."""
        self.model_step.clear_error()
        # Steps 1 and 2 seed their own first Tab stop. During a run step 3 has
        # no control of its own - Cancel, on the nav bar, is the only thing to
        # act on - so focus is seeded here.
        self._set_step(
            Step.TRANSCRIPTION,
            back_visible=False,
            cancel_visible=True,
            next_visible=False,
            focus_widget=self.cancel_btn,
        )

        # The run's decisions come from the Qt-free presenter; only widget
        # and thread work remains here. selected_model is set by now: _go_next
        # returns early without one.
        model = cast(str, self.selected_model)
        request = build_transcription_request(
            files=self.selected_files,
            model=model,
            durations=self.file_step.durations,
            hardware=self.hardware,
            identify_speakers=self.model_step.identify_speakers,
            num_speakers=self.model_step.num_speakers,
            translate=t,
        )

        self.transcription_step.set_file_info(request.file_summary, model)
        # Filenames for the batch strip's tooltips come from here, not from
        # the worker - see TranscriptionStep.set_batch_files's docstring
        # for why. self.selected_files is exactly the list FileSelectStep
        # produced on step 1, in run order.
        self.transcription_step.set_batch_files(self.selected_files)
        self.transcription_step.start(identify_speakers=self.model_step.identify_speakers)

        logger.info(
            f"Starting transcription: {request.file_summary} with {self.selected_model} model"
        )
        logger.info(f"Device: {request.device} ({request.device_reason})")

        self.transcription_thread = TranscriptionThread(
            request.files,
            request.model,
            request.device,
            request.durations,  # real PyAV-measured durations, for accurate progress
            options=request.options,
        )
        self.transcription_thread.progress.connect(self.transcription_step.update_progress)
        # The bar and the clock are fed separately on purpose: a percentage and
        # a count of audio-seconds answer different questions, and turning one
        # back into the other is what made the old time estimate wrong (see
        # gui/presenters/time_estimate.py).
        self.transcription_thread.work.connect(self.transcription_step.update_work)
        self.transcription_thread.phase.connect(self.transcription_step.update_phase)
        self.transcription_thread.file_failed.connect(self.transcription_step.mark_file_failed)
        self.transcription_thread.finished.connect(self._on_transcription_complete)
        self.transcription_thread.error.connect(self._on_transcription_error)
        self.transcription_thread.start()

    def _on_transcription_complete(self, output_file: str) -> None:
        """Handle transcription completion."""
        logger.info(f"Transcription complete: {output_file}")
        self.transcription_step.stop()
        # Force the bar to a definitive 100% on completion, regardless of
        # whether every trailing progress message was relayed in time.
        self.transcription_step.update_progress("w_complete", {}, 100)
        self.transcription_step.show_result(output_file)

        # Stays on step 3 - only next_btn's role changes, to a reset
        # action, since _on_next_clicked now dispatches on next_mode
        # instead of needing next_btn rewired to a different slot.
        self._set_step(
            Step.TRANSCRIPTION,
            back_visible=False,
            cancel_visible=False,
            next_visible=True,
            next_enabled=True,
            next_mode="new_file",
        )
        # After _set_step, which repaints the strip with step 3 as current.
        self.step_indicator.set_complete()

    def _on_transcription_error(self, error_key: str, error_params: dict[str, object]) -> None:
        """A real failure (not a cancel): show the inline banner on Choose
        Model and return there, so the user can retry - say, with a smaller
        model - without re-picking files.
        """
        logger.error(f"Transcription error: {error_key} {error_params}")
        self.transcription_step.stop()
        self.model_step.show_error(error_key, error_params)
        self._return_to_model_select()

    def _on_cancel_clicked(self) -> None:
        """Cancel and Escape on step 3, as a two-press control: the first press
        arms it (destructive colour, an explanation, a timeout), the second
        cancels. A run can be 40+ minutes in, and this app asks for
        confirmation in the control itself rather than a modal dialog.
        """
        if not self._cancel_armed:
            self._arm_cancel()
            return
        self._cancel_arm_timer.stop()
        self._cancel_armed = False
        self._set_cancel_armed_visual(False)
        self._cancel_transcription()

    def _arm_cancel(self) -> None:
        self._cancel_armed = True
        self._set_cancel_armed_visual(True)
        self._cancel_arm_timer.start()

    def _disarm_cancel(self) -> None:
        """Reset Cancel to resting - from its timeout and on every step change.
        Safe when already disarmed.
        """
        self._cancel_arm_timer.stop()
        self._cancel_armed = False
        self._set_cancel_armed_visual(False)

    def _set_cancel_armed_visual(self, armed: bool) -> None:
        """Paint cancel_btn/cancel_confirm_label for `armed` - see _on_cancel_clicked."""
        if armed:
            self.cancel_btn.setStyleSheet(theme.button_danger_qss())
            self.cancel_btn.set_text_colors(COLORS["error"], hover=COLORS["error"])
            self.cancel_confirm_label.show()
        else:
            self.cancel_btn.setStyleSheet(theme.button_secondary_qss())
            self.cancel_btn.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
            self.cancel_confirm_label.hide()

    def _cancel_transcription(self) -> None:
        """Stop a running transcription and return to Choose Model."""
        logger.info("Transcription cancelled by user")
        self.transcription_step.stop()
        if self.transcription_thread:
            # Disconnect first: stop() causes the thread to emit its own
            # "Transcription cancelled" error signal, which we don't want
            # routed through _on_transcription_error (that's for genuine
            # failures only).
            self.transcription_thread.error.disconnect(self._on_transcription_error)
            self.transcription_thread.finished.disconnect(self._on_transcription_complete)
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        self._return_to_model_select()

    def _return_to_model_select(self) -> None:
        """Go back to the Choose Model step, keeping the selected file/model."""
        self._set_step(
            Step.MODEL_SELECT,
            back_visible=True,
            cancel_visible=False,
            next_visible=True,
            next_enabled=self.selected_model is not None,
        )

    def _reset(self) -> None:
        """Reset to file selection."""
        self.model_step.clear_error()
        self.selected_files = []
        self.selected_model = None
        self.audio_duration = 0
        self._set_step(
            Step.FILE_SELECT,
            back_visible=False,
            cancel_visible=False,
            next_visible=True,
            next_enabled=False,
        )
        self.file_step.reset()
        logger.debug("Reset to file selection step")

    def _detach_calibration_thread(self) -> None:
        """Disconnect and stop the background calibration on the way out.

        Its result would otherwise land in widgets Qt is destroying. Disconnect
        first: stopping cannot recall a result already in flight. Idempotent.
        """
        if self.calibration_thread is None:
            return
        try:
            self.calibration_thread.calibrated.disconnect(self._on_calibration_done)
            self.calibration_thread.failed.disconnect(self._on_calibration_failed)
        except TypeError:
            # Already disconnected - _detach_calibration_thread ran twice.
            pass
        self.calibration_thread.stop()
        # Bounded: the run loop wakes at least every 0.5s to re-check its
        # own flag, so this waits for that poll, not for the benchmark.
        self.calibration_thread.wait()

    def shutdown(self) -> None:
        """Stop all background work; idempotent. Also called after exec_()
        returns, for exits that never close the window (app.quit, logout).
        """
        self._detach_calibration_thread()
        # Duration probing is short-lived but can still be in flight when the
        # window goes away - a dropped OneDrive placeholder can take a while -
        # and a QThread delivering into a half-destroyed widget is the exact
        # trap gui/focus.py exists for.
        self.file_step.stop_probing()
        if self.transcription_thread:
            self.transcription_thread.stop()
            self.transcription_thread.wait()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Stop any running transcription and the calibration on close.

        No two-press confirmation: closing the window is already deliberate,
        and the only way to ask would be a modal dialog this app avoids. The
        calibration is detached here, not at aboutToQuit, because its slots
        reach into this window's widgets, which start going away now.
        """
        if self.current_step == Step.TRANSCRIPTION and self.transcription_thread:
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        self._detach_calibration_thread()
        logger.info("Application closed by user")
        # Optional in the override signature only because the C++ one takes
        # a pointer; Qt always delivers a real event to a closing window.
        if a0 is not None:
            a0.accept()


def configure_application(app: QApplication) -> None:
    """Process-wide setup for a fresh QApplication, before any window: the app
    stylesheet, the painted checkbox style, the saved UI language, the focus
    tracker and the title-bar colouring.

    Every entry point calls this one function - app.py once built its own
    QApplication and shipped with no stylesheet at all. Call it after the
    QApplication exists; the high-DPI flags are a separate, import-time matter.
    """
    app.setStyleSheet(theme.app_stylesheet())
    app.setStyle(PaintedCheckboxStyle(app.style()))
    i18n.apply_saved_language(app)

    # One focus tracker per QApplication, so dialogs get focus rings too.
    # Guarded, so a second call is harmless.
    if getattr(app, "_kbd_focus_tracker", None) is None:
        # The attribute name is a contract: ModelSelectStep reads it back.
        app._kbd_focus_tracker = KeyboardFocusTracker(app)  # type: ignore[attr-defined]
    # Dark title bars for every window - see gui/window_chrome.py. Guarded
    # the same way, so a second call doesn't install a second filter.
    if getattr(app, "_title_bar_colorizer", None) is None:
        app._title_bar_colorizer = TitleBarColorizer(app)  # type: ignore[attr-defined]


def main() -> None:
    """Entry point for GUI."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    configure_application(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
