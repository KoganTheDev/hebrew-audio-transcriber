"""Main window for the Speech-to-Text Transcriber GUI.
3-step flow: Select File → Choose Model → Transcribe
"""

import logging
import sys
from typing import Optional

from PyQt5.QtCore import Qt, QThread, QTimer
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDesktopWidget,
    QFrame,
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

from speech_to_text import config
from speech_to_text.gui import i18n, theme
from speech_to_text.gui.checkbox_style import PaintedCheckboxStyle
from speech_to_text.gui.focus import KeyboardFocusTracker
from speech_to_text.gui.i18n import t
from speech_to_text.gui.presenters import build_transcription_request
from speech_to_text.gui.stepper import StepIndicator
from speech_to_text.gui.steps import FileSelectStep, ModelSelectStep, Step, TranscriptionStep
from speech_to_text.gui.theme import COLORS, Fonts
from speech_to_text.gui.threads import CalibrationThread, TranscriptionThread
from speech_to_text.gui.widgets import IconTextButton, make_label
from speech_to_text.hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)


# High-DPI rendering: without these, Qt5 treats the app as DPI-unaware and
# Windows falls back to bitmap-stretching the whole window at 125%/150%
# scale - it renders, but every glyph and icon is a blurred upscale of the
# 100% raster rather than something actually drawn at the higher
# resolution. AA_EnableHighDpiScaling turns on Qt's own scaling of
# geometry (so widget sizes/fonts/positions stay correct in logical pixels
# while Qt asks the OS for physical-pixel-sharp output); AA_UseHighDpiPixmaps
# makes QIcon/QPixmap request the right physical resolution for the
# current scale instead of handing over a 100%-scale bitmap for Windows to
# stretch. setHighDpiScaleFactorRoundingPolicy(PassThrough) additionally
# stops Qt from ROUNDING a scale factor like 1.25 or 1.5 to the nearest
# integer before applying it (its default policy since Qt 5.14) - without
# this, 125% and 150% would both actually render at 100% or 200% internally
# and only get bitmap-scaled to the requested factor after the fact, which
# defeats the whole point of enabling high-DPI scaling in the first place.
#
# These three calls are QApplication/Qt *class*-level attributes, not
# instance state, and Qt requires them to be set before the QApplication
# object is constructed - setting them on an already-running instance is a
# silent no-op. This module is imported (directly or via `from
# speech_to_text.gui import theme` pulling in sibling gui modules) by every
# real and harness entry point - speech_to_text/main.py, this module's own
# main(), and the screenshot/probe scripts under scratchpad/ - strictly
# before any of them calls `QApplication(sys.argv)`, so doing it here at
# module import time, exactly once (Python's module cache guarantees that),
# is the one place that is guaranteed to run first for all of them without
# duplicating this call at every call site.
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def _is_text_entry_widget(widget) -> bool:
    """True for any widget where Enter means "confirm what I just typed here",
    not "advance to the next step" - the window-level Enter shortcut below
    checks this before acting. The speaker-count QSpinBox on step 2 is the
    concrete case that matters (typing "10" and pressing Enter must not
    skip the screen), but every native Qt text-entry base class is covered
    here rather than special-casing just that one widget, so a future text
    field on any step gets the same protection for free.
    """
    return isinstance(widget, (QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox))


class MainWindow(QMainWindow):
    """Main application window - lightweight tool interface."""

    # How long an armed Cancel (first press) stays armed before reverting
    # to its resting state on its own - see _on_cancel_clicked. Long enough
    # that a deliberate "yes, I meant that" second click isn't a race
    # against the clock, short enough that walking away from the keyboard
    # after an accidental first press doesn't leave the button looking
    # dangerous indefinitely.
    CANCEL_ARM_TIMEOUT_MS = 3000

    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow...")

        self.setWindowTitle(t("app_title"))
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.move(100, 50)
        # Resizable with a real floor, not setFixedSize(): a fixed size let
        # the window sit at 650x600 while the transcription step's own
        # content needed 628px, which is what the "result panel clipped on
        # completion" bug actually was - the window was simply too short,
        # and setFixedSize() meant nothing downstream ever had to notice or
        # adapt. See config.py's GUI_WINDOW_MIN_HEIGHT comment for the
        # measurement behind these numbers. The maximize hint that used to
        # be stripped here comes back for the same reason: a maximize
        # button next to a resizable window that silently refuses to
        # maximize would be its own small bug.
        self.resize(config.GUI_WINDOW_WIDTH, config.GUI_WINDOW_HEIGHT)
        self.setMinimumSize(config.GUI_WINDOW_MIN_WIDTH, config.GUI_WINDOW_MIN_HEIGHT)
        # Main window background is set by theme.app_stylesheet() on the
        # QApplication (see main()) rather than here per-instance.

        self.hardware = HardwareDetector()
        self.current_step = Step.FILE_SELECT
        self.transcription_thread: Optional[QThread] = None
        self.selected_files: list[str] = []
        self.selected_model: Optional[str] = None
        # Total across every selected file - what should drive the model
        # recommendation, since the estimate has to cover the whole batch.
        self.audio_duration: int = 0
        self.calibration_thread: Optional[QThread] = None

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

        # Kick off the one-time hardware calibration in the background, if no
        # cached result was already loaded by HardwareDetector. Runs while
        # the user is still picking a file, so real numbers are usually
        # ready before they reach the model-select step.
        if self.hardware.tiny_seconds_per_audio_second is None:
            self.calibration_thread = CalibrationThread(self.hardware.cpu_count)
            self.calibration_thread.calibrated.connect(self._on_calibration_done)
            self.calibration_thread.failed.connect(self._on_calibration_failed)
            self.calibration_thread.start()

        logger.info("✓ MainWindow ready")

    def _on_calibration_done(self, tiny_seconds_per_audio_second: float):
        """Apply a finished background calibration and refresh any visible estimates."""
        self.hardware.set_calibration(tiny_seconds_per_audio_second)
        self.model_step.update_audio_duration(self.audio_duration)
        logger.debug("Refreshed model time estimates with calibrated values")

    def _on_calibration_failed(self, message: str):
        logger.warning(f"Hardware calibration failed, keeping placeholder estimates: {message}")
        # The "still measuring" note on step 2 (see ModelSelectStep) would
        # otherwise stay up forever, quietly promising a real number that's
        # never coming now that the benchmark itself has failed - swap it
        # for a permanent, honest "these are rough" resting state instead.
        self.model_step.mark_calibration_unmeasured()

    def center_on_screen(self):
        """Center window on screen."""
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        logger.debug(f"Window centered at ({x}, {y})")

    def _init_shortcuts(self):
        """Window-level keyboard shortcuts. Each is a QShortcut parented to
        the window with the default Qt.WindowShortcut context, so it fires
        whenever this window (or a descendant) has focus, regardless of
        which specific widget that is - the per-widget guards below (the
        text-entry check for Enter, the step check for Escape) are what
        keep that broad reach from firing somewhere it shouldn't, rather
        than narrowing the shortcut's context itself.

        References are kept on self even though QShortcut's Qt-parent
        already prevents garbage collection - documents what exists and
        makes them inspectable from a debugger or a test.
        """
        self._shortcut_browse = QShortcut(QKeySequence("Ctrl+O"), self)
        self._shortcut_browse.activated.connect(self._on_browse_shortcut)

        self._shortcut_toggle_language = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self._shortcut_toggle_language.activated.connect(self._toggle_language)

        # Return AND Enter - the numpad key sends Qt.Key_Enter, the main
        # keyboard's sends Qt.Key_Return, and QKeySequence("Return") only
        # matches one of them.
        self._shortcut_advance_return = QShortcut(QKeySequence(Qt.Key_Return), self)
        self._shortcut_advance_return.activated.connect(self._on_advance_shortcut)
        self._shortcut_advance_enter = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self._shortcut_advance_enter.activated.connect(self._on_advance_shortcut)

        self._shortcut_back = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_back.activated.connect(self._on_escape_shortcut)

    def _on_browse_shortcut(self):
        """Ctrl+O: open the file-picker dialog. Only meaningful on step 1."""
        if self.current_step == Step.FILE_SELECT:
            self.file_step.browse_for_files()

    def _on_advance_shortcut(self):
        """Enter/Return: equivalent to clicking Next, guarded against firing
        while the user is mid-entry in a text field (see
        _is_text_entry_widget - the speaker-count QSpinBox on step 2 is the
        case that matters: typing "10" and pressing Enter must confirm the
        number, not skip the screen).

        DropZone (gui/widgets.py) already wins this race on step 1 via its
        own ShortcutOverride handling, so Enter there opens the browse
        dialog instead of reaching this slot at all - see its docstring.

        Gated on next_btn's own visible+enabled state rather than switching
        on self.current_step: that state already encodes every reason
        Enter should be a no-op right now (no file chosen yet, no model
        chosen yet, a transcription in progress with Next hidden), so
        re-deriving the same conditions here would just be a second place
        for them to drift out of sync.
        """
        focused = QApplication.focusWidget()
        if _is_text_entry_widget(focused):
            return
        if self.next_btn.isVisible() and self.next_btn.isEnabled():
            self.next_btn.click()

    def _on_escape_shortcut(self):
        """Escape: go Back on step 2 (Choose Model); on step 3 (Transcribing),
        drive the same two-press Cancel confirmation the button itself
        uses (see _on_cancel_clicked).

        Step 3 was deliberately left unbound here for a while - Cancel used
        to stop a possibly long-running transcription with a single click
        and no confirmation prompt, so binding Escape to it would have let
        one stray keystroke throw away a run that might be 40 minutes in.
        That reason is gone now that Cancel itself requires two presses:
        routing Escape through _on_cancel_clicked gives a keyboard user the
        exact same arm-then-confirm safety net a mouse user gets, rather
        than leaving Escape as a second, inconsistent path.

        Step 1 has nothing behind it to go back TO, so it's left unbound
        there too rather than closing the window or doing nothing silently
        surprising.
        """
        if self.current_step == Step.MODEL_SELECT:
            self._go_back()
        elif self.current_step == Step.TRANSCRIPTION:
            self._on_cancel_clicked()

    def _init_ui(self):
        """Initialize UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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
        # Rendered as a pixmap, so retranslate() re-renders it on language switch.
        self.title_label = QLabel()
        self.title_label.setPixmap(
            theme.gradient_text_pixmap(
                t("app_title"), Fonts.SUBTITLE_BOLD, dpr=self.devicePixelRatioF()
            )
        )
        self.title_label.setStyleSheet("background: transparent;")
        self.title_label.setAlignment(Qt.AlignCenter)

        # EN/HE toggle at the trailing edge of the header (label shows the
        # TARGET language). A same-width invisible spacer at the leading edge
        # keeps the title optically centered.
        lang_btn_width = 52
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedSize(lang_btn_width, 30)
        self.lang_btn.setFont(Fonts.CAPTION_BOLD)
        self.lang_btn.setStyleSheet(theme.button_secondary_qss(padding="2px 4px"))
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        # Icon-only in effect: its visible text is a language code ("EN" /
        # "עב"), the TARGET language, which reads fine next to the app's
        # current language but says nothing about what clicking it does to
        # a screen reader with no visual context - see i18n's
        # toggle_language_name/_tooltip for why these are static rather
        # than re-derived per toggle direction.
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

        i18n.language_manager.language_changed.connect(self._on_language_changed)

        # Wizard step indicator - the only on-screen signal of where the
        # user is in the flow beyond the page heading each step used to
        # print itself (now removed - see gui/stepper.py's module
        # docstring for why one indicator replaces two copies of the same
        # name). Sits between the header and the stacked widget so it
        # reads as chrome framing the current page, not as part of any one
        # step's own content.
        self.step_indicator = StepIndicator()
        main_layout.addWidget(self.step_indicator)

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

        # Cancel button - only shown during Step.TRANSCRIPTION, in the same
        # slot as Back (which is hidden at that point). Stops the worker
        # process and returns to Choose Model rather than closing the app.
        #
        # Two-press, not a modal confirmation - see _on_cancel_clicked for
        # the full reasoning and ModelSelectStep.show_error's docstring for
        # why this app avoids QMessageBox generally. Kept at the fixed
        # nav_btn_size in both its resting and armed states: candidate
        # armed labels ("Press again to cancel" etc.) were measured against
        # this button and all came out too wide in at least one language,
        # so the label stays "Cancel" throughout and cancel_confirm_label
        # below carries the explanation instead - see button_danger_qss's
        # docstring for the measurements.
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

        nav_layout.addStretch()

        # Next button (text/icon set by _set_next_button_mode)
        self.next_btn = IconTextButton()
        self.next_btn.setFixedSize(*nav_btn_size)
        self.next_btn.setFont(Fonts.BODY_BOLD)
        self.next_btn.setStyleSheet(theme.button_primary_qss())
        self.next_btn.set_text_colors(COLORS["bg_primary"], disabled=COLORS["text_tertiary"])
        # Connected once, to a slot that dispatches on next_btn's current
        # role (see _on_next_clicked) - not reconnected per step the way
        # earlier revisions did. That disconnect/reconnect dance needed a
        # bare `except TypeError` in _return_to_model_select to survive
        # being called when nothing was connected yet; a single connection
        # that switches on self._next_btn_mode has no such edge case.
        self.next_btn.clicked.connect(self._on_next_clicked)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

        main_layout.addWidget(nav_widget)

        self._next_btn_mode = "next"
        self._retranslate_chrome()
        self._wire_tab_order()

    def _wire_tab_order(self):
        """Explicit Tab chain spanning the whole window, following visual
        order top to bottom: header language toggle, then each step's own
        internal chain (each step already wires its own controls in
        __init__/showEvent - see FileSelectStep and ModelSelectStep), then
        the nav bar.

        Chaining across all three steps in one sequence is safe even
        though only one is ever visible at a time: Qt's own Tab-key
        handling skips any widget that isn't visible, so the inactive
        steps' links in this chain are simply never used, and no per-step
        branching is needed here to keep them from interfering with each
        other.
        """
        first_model = next(iter(config.MODELS))
        last_model = list(config.MODELS)[-1]
        self.setTabOrder(self.lang_btn, self.file_step.drop_zone)
        self.setTabOrder(self.file_step.drop_zone, self.model_step.model_radios[first_model])
        self.setTabOrder(
            self.model_step.model_radios[last_model], self.model_step.identify_speakers_check
        )
        self.setTabOrder(self.model_step.speaker_count_spin, self.back_btn)
        self.setTabOrder(self.back_btn, self.cancel_btn)
        self.setTabOrder(self.cancel_btn, self.transcription_step.open_button)
        self.setTabOrder(self.transcription_step.open_button, self.transcription_step.folder_button)
        self.setTabOrder(self.transcription_step.folder_button, self.next_btn)
        self.setTabOrder(self.next_btn, self.lang_btn)

    def _retranslate_chrome(self):
        """(Re-)apply window title, header, and nav button text/icons/directions."""
        self.setWindowTitle(t("app_title"))
        self.title_label.setPixmap(
            theme.gradient_text_pixmap(
                t("app_title"), Fonts.SUBTITLE_BOLD, dpr=self.devicePixelRatioF()
            )
        )
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

    def _set_next_button_mode(self, mode: str):
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

    def _toggle_language(self):
        i18n.set_language("he" if i18n.get_language() == "en" else "en")

    def _on_language_changed(self, lang: str):
        """Apply app-wide layout direction and re-render every visible string."""
        from PyQt5.QtWidgets import QApplication

        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if lang == "he" else Qt.LeftToRight
        )
        self._retranslate_chrome()
        self.step_indicator.retranslate()
        for i in range(self.stacked_widget.count()):
            self.stacked_widget.widget(i).retranslate()
        # The RTL/LTR flip relocates the buttons (the toggle jumps to the
        # opposite side of the header) without Qt sending them a Leave
        # event, so the clicked button keeps its :hover styling until the
        # mouse happens to pass over it again. Clear the stale under-mouse
        # flag and re-polish so hover state matches reality.
        for btn in self.findChildren(QPushButton):
            btn.setAttribute(Qt.WA_UnderMouse, False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _on_files_selected(self, file_paths: list, total_duration: int):
        """Handle the file list changing (add, remove, or a folder drop)."""
        self.selected_files = list(file_paths)
        self.audio_duration = total_duration
        self.next_btn.setEnabled(bool(self.selected_files))
        logger.debug(f"Files selected: {len(self.selected_files)} file(s), {total_duration}s total")

    def _on_model_selected(self, model: str):
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
        focus_widget=None,
    ) -> None:
        """Single funnel for every wizard-navigation transition. Owns exactly
        the bookkeeping that was previously hand-written in five separate
        places (_go_back, _go_next, _start_transcription,
        _return_to_model_select, _reset - see this method's call sites
        below): current_step, the stack index, Back/Cancel/Next visibility
        and enablement, next_btn's mode, a seeded initial focus (only
        needed by the one step - Transcription - that has no showEvent of
        its own to seed it, see _start_transcription's call), and
        repainting the step indicator.

        Deliberately does NOT do any of the step-specific work that used
        to sit alongside that bookkeeping in the old methods - starting or
        tearing down the transcription thread, resetting file_step's
        state, showing the "no model selected" warning, and so on. Callers
        do that themselves, before or after calling this, exactly as they
        did before; this only absorbs the navigation plumbing that was
        identical in shape across all five.
        """
        self.current_step = step
        self.stacked_widget.setCurrentWidget(self.stacked_widget.widget(step.value))

        self.back_btn.setVisible(back_visible)
        if back_visible:
            self.back_btn.setEnabled(True)

        self.cancel_btn.setVisible(cancel_visible)
        # Every navigation away from (or back into) step 3 gets a fresh,
        # unarmed Cancel - an armed state left over from a previous run, or
        # from a stray press right before the run finished on its own,
        # should never carry forward into whatever comes next. Unconditional
        # rather than only when cancel_visible is False: it's a no-op when
        # already disarmed, and calling it here once covers every one of
        # _set_step's five call sites instead of needing each to remember.
        self._disarm_cancel()

        self._set_next_button_mode(next_mode)
        self.next_btn.setVisible(next_visible)
        self.next_btn.setEnabled(next_enabled)

        if focus_widget is not None:
            focus_widget.setFocus(Qt.OtherFocusReason)

        self.step_indicator.set_current(step)
        logger.debug(f"Navigated to: {step}")

    def _on_next_clicked(self):
        """next_btn's one and only clicked connection (see _init_ui) -
        dispatches on the button's current role instead of the
        disconnect/reconnect-a-different-slot dance this used to require.
        "next" is the forward-navigation role _go_next always handles;
        "new_file" is the post-completion reset role _on_transcription_complete
        switches the button into (see _set_next_button_mode).
        """
        if self._next_btn_mode == "new_file":
            self._reset()
        else:
            self._go_next()

    def _go_back(self):
        """Go to previous step."""
        if self.current_step == Step.MODEL_SELECT:
            self._set_step(
                Step.FILE_SELECT,
                back_visible=False,
                cancel_visible=False,
                next_visible=True,
                next_enabled=bool(self.selected_files),
            )

    def _go_next(self):
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

    def _start_transcription(self):
        """Start transcription thread."""
        self.model_step.clear_error()
        # Steps 1 and 2 seed a sensible Tab starting point in their own
        # showEvent (the drop zone / the selected radio - see
        # FileSelectStep.showEvent and ModelSelectStep.showEvent), because
        # each of those steps owns a widget worth landing on. Step 3 has no
        # such widget of its own while a run is in progress: the title,
        # file info, progress bar and status/time labels are all plain,
        # non-focusable QLabels/QProgressBar, and the result panel (the one
        # place with a real control, open_button) stays hidden until
        # show_result() runs, possibly tens of minutes from now. The only
        # thing on screen a keyboard user can actually act on during that
        # window is Cancel - which lives on MainWindow's own nav bar, not
        # inside TranscriptionStep, so TranscriptionStep has no showEvent of
        # its own that could seed it; this is the one place that already
        # knows both "step 3 just became current" and "cancel_btn just
        # became visible", so it's the one _set_step call that passes
        # focus_widget.
        self._set_step(
            Step.TRANSCRIPTION,
            back_visible=False,
            cancel_visible=True,
            next_visible=False,
            focus_widget=self.cancel_btn,
        )

        # Every decision this run needs, taken in one Qt-free place (see
        # gui/presenters/transcription.py). What is left below is only
        # widget and thread work. t is passed in rather than imported there
        # because gui.i18n imports PyQt5.
        request = build_transcription_request(
            files=self.selected_files,
            model=self.selected_model,
            durations=self.file_step.durations,
            hardware=self.hardware,
            identify_speakers=self.model_step.identify_speakers,
            num_speakers=self.model_step.num_speakers,
            translate=t,
        )

        self.transcription_step.set_file_info(request.file_summary, self.selected_model)
        # Filenames for the batch strip's tooltips come from here, not from
        # the worker - see TranscriptionStep.set_batch_files's docstring
        # for why. self.selected_files is exactly the list FileSelectStep
        # produced on step 1, in run order.
        self.transcription_step.set_batch_files(self.selected_files)
        self.transcription_step.start()

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
        self.transcription_thread.finished.connect(self._on_transcription_complete)
        self.transcription_thread.error.connect(self._on_transcription_error)
        self.transcription_thread.start()

    def _on_transcription_complete(self, output_file: str):
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

    def _on_transcription_error(self, error_key: str, error_params: dict):
        """Handle a genuine transcription failure (not a user cancel - that's
        handled separately by _cancel_transcription).

        Receives an i18n key + params (rendered at display time, so the
        banner survives a language toggle). Shows an inline banner on the
        Choose Model step instead of a modal QMessageBox, and returns there
        (rather than all the way back to file selection) so the user can
        retry - e.g. with a smaller model - without having to re-pick the file.
        """
        logger.error(f"Transcription error: {error_key} {error_params}")
        self.transcription_step.stop()
        self.model_step.show_error(error_key, error_params)
        self._return_to_model_select()

    def _on_cancel_clicked(self):
        """Cancel's actual clicked/Escape handler - a two-press control rather
        than the single click _cancel_transcription used to be wired
        directly to.

        Cancelling is destructive (a run can be 40+ minutes in) and this
        app deliberately never uses a modal QMessageBox to ask "are you
        sure" (see ModelSelectStep.show_error's docstring for why), so the
        confirmation has to live in the control itself: the first press
        arms it - _set_cancel_armed_visual gives the button a destructive
        colour treatment and shows cancel_confirm_label's explanation next
        to it, and _cancel_arm_timer starts a countdown - and only a second
        press while still armed calls through to _cancel_transcription.
        Arming times out on its own (see _disarm_cancel) so a single stray
        press doesn't leave the button looking permanently dangerous.
        """
        if not self._cancel_armed:
            self._arm_cancel()
            return
        self._cancel_arm_timer.stop()
        self._cancel_armed = False
        self._set_cancel_armed_visual(False)
        self._cancel_transcription()

    def _arm_cancel(self):
        self._cancel_armed = True
        self._set_cancel_armed_visual(True)
        self._cancel_arm_timer.start()

    def _disarm_cancel(self):
        """Revert Cancel to its resting state - called by the arm timer's own
        timeout, and unconditionally by _set_step on every navigation (see
        its comment) so an armed state never survives leaving step 3.
        Safe to call when already disarmed: stopping a timer that isn't
        running and hiding an already-hidden label are both no-ops.
        """
        self._cancel_arm_timer.stop()
        self._cancel_armed = False
        self._set_cancel_armed_visual(False)

    def _set_cancel_armed_visual(self, armed: bool):
        """Paint cancel_btn/cancel_confirm_label for `armed` - see _on_cancel_clicked."""
        if armed:
            self.cancel_btn.setStyleSheet(theme.button_danger_qss())
            self.cancel_btn.set_text_colors(COLORS["error"], hover=COLORS["error"])
            self.cancel_confirm_label.show()
        else:
            self.cancel_btn.setStyleSheet(theme.button_secondary_qss())
            self.cancel_btn.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
            self.cancel_confirm_label.hide()

    def _cancel_transcription(self):
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

    def _return_to_model_select(self):
        """Go back to the Choose Model step, keeping the selected file/model."""
        self._set_step(
            Step.MODEL_SELECT,
            back_visible=True,
            cancel_visible=False,
            next_visible=True,
            next_enabled=self.selected_model is not None,
        )

    def _reset(self):
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

    def _detach_calibration_thread(self):
        """Unwire and stop the background calibration, on the way out.

        The calibration thread outlives nothing gracefully on its own: it
        is started in __init__ and, unlike the transcription thread, has no
        user-facing cancel path, so a window closed while the benchmark is
        still running leaves a live thread whose `calibrated` signal calls
        _on_calibration_done - which writes straight into widgets
        (model_step.update_audio_duration) that Qt is by then destroying.

        Disconnecting matters as much as stopping, and comes first for the
        same reason it does in _cancel_transcription: stop() cannot un-emit
        a result that is already in flight, so the only way to be sure no
        slot touches a widget after teardown starts is to take the slots
        off the signals. gui/focus.py's _detach is the precedent for the
        whole shape - and this is the same class of gap it closed, though
        no crash has been observed from this one.

        Idempotent, and safe on a window that never started a calibration
        at all (a cached result, which is the common case).
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

    def closeEvent(self, event):
        """Stop any running transcription before the window closes.

        Deliberately NOT routed through the two-press arm/confirm flow
        Cancel and Escape use on step 3 (see _on_cancel_clicked) - closing
        the window is already an explicit, unambiguous act on the user's
        part (unlike a single Cancel click or Escape press, which could be
        a slip), so there is nothing left to confirm. The only mechanism
        available to ask "are you sure" here would be a modal QMessageBox,
        which this app deliberately avoids everywhere else (see
        ModelSelectStep.show_error's docstring) - introducing the one
        exception at the highest-stakes moment (the user is already
        leaving) would be a stranger inconsistency than simply trusting
        the close itself.

        The background calibration is torn down here too, unconditionally -
        see _detach_calibration_thread. closeEvent rather than
        QApplication.aboutToQuit (which is where gui/focus.py hooks its own
        detach) because the two modules are guarding different lifetimes:
        KeyboardFocusTracker has no window of its own and its danger window
        opens after exec_() returns, when Qt is destroying the widget tree,
        so aboutToQuit is the only moment left where everything is still
        alive. This thread's slots reach into THIS window's widgets, and
        closeEvent is the earliest point at which those widgets are known
        to be going away - unwiring here closes the gap before aboutToQuit
        would even fire, and keeps the teardown next to the transcription
        thread's, which is the other half of the same job.
        """
        if self.current_step == Step.TRANSCRIPTION and self.transcription_thread:
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        self._detach_calibration_thread()
        logger.info("Application closed by user")
        event.accept()


def configure_application(app: QApplication) -> None:
    """Apply the two pieces of process-wide setup every GUI entry point needs
    on a freshly-constructed QApplication, before any window is built:
    the app stylesheet and the persisted UI language.

    This used to live only in this module's own main() below, which is
    reachable exclusively via `python -m speech_to_text.gui.main_window` -
    a path nothing in the shipped app actually uses. speech_to_text/main.py
    (the real entry point behind run.ps1, run.bat, `python -m
    speech_to_text.main`, and the `speech-to-text` console script) built
    its own QApplication and never applied the stylesheet at all, so the
    entire themed look - peach checkbox tick, radio ring-and-dot, spin box
    frame and arrows, dark scrollbars, styled QToolTip, the kbdFocus ring on
    native controls - was silently absent from every real launch while
    still looking correct in this module's own main() and in any ad hoc
    script that happened to call app_stylesheet() itself. Centralizing the
    setup here, called by both entry points (and by anything else that
    stands up a QApplication for this GUI, e.g. screenshot/diagnostic
    scripts), is what keeps them from drifting apart again - adding the one
    missing line to main.py would have fixed today's symptom but left two
    independent call sites free to diverge on the next change.

    Must be called AFTER the QApplication is constructed (setStyleSheet and
    setLayoutDirection are instance calls) but this has no bearing on the
    high-DPI import-ordering constraint documented above
    (TestHighDpiEntryPointOrdering): that constraint is about *importing*
    this module before QApplication() runs, not about when this function is
    called relative to it.

    Also installs PaintedCheckboxStyle, wrapping whatever style the
    QApplication resolved on its own (the platform default unless
    overridden). This lives here rather than being folded into
    app_stylesheet() because it is not QSS at all - see
    checkbox_style.py's module docstring for why the checkbox tick moved
    off the QSS `image:` mechanism entirely - and this is the one place
    that already owns "everything a freshly-built QApplication needs before
    any window exists".
    """
    app.setStyleSheet(theme.app_stylesheet())
    app.setStyle(PaintedCheckboxStyle(app.style()))
    i18n.apply_saved_language(app)

    # One tracker per QApplication, not per window. It used to be installed
    # by MainWindow.__init__, which worked only because this app happens to
    # build exactly one window: anything else standing up a widget against
    # this QApplication - a second window, a dialog, a diagnostic script -
    # got no tracker and therefore no focus ring, with nothing reporting it.
    # That is the same shape of drift that left the stylesheet unapplied in
    # the shipped entry point for the whole redesign, so it belongs here
    # with the rest of the process-wide setup rather than inside a widget's
    # constructor. Guarded rather than assumed to run once, since calling
    # this twice on one QApplication should be harmless.
    if getattr(app, "_kbd_focus_tracker", None) is None:
        # Attribute name is a contract, not an implementation detail:
        # ModelSelectStep._sync_card_focus_ring reads it back off the
        # application to decide whether a model card should show its ring.
        app._kbd_focus_tracker = KeyboardFocusTracker(app)


def main():
    """Entry point for GUI."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    configure_application(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
