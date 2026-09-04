"""Wizard step indicator: the three-segment status strip shown between the
header and the stacked widget, naming where the user is in the
Select File -> Choose Model -> Transcribe flow.

This replaces each step's own Fonts.DISPLAY heading ("Specs", "Choose
Model", "Transcribing") rather than sitting alongside it - see the removal
of `self.title` in each of the three step widgets. A stepper that names the
steps while the page underneath ALSO prints its own name is the same fact
said twice in the same place on screen; carrying the naming job here once
is the point, not a compromise forced by the window's tight vertical
budget (though it also happens to solve that - removing a DISPLAY heading
plus its trailing spacer frees far more height than this strip costs).

A status display, not a control: built from a plain QHBoxLayout of QLabels,
nothing here is focusable or clickable, and there is deliberately no
QPushButton/QRadioButton anywhere in this file. QHBoxLayout mirrors
automatically under QApplication.setLayoutDirection - step 1's segment
lands on the trailing edge of the strip in Hebrew (the right side, since
Hebrew is RTL) with no direction-specific code needed here, the same
"mirrors for free" property every other QHBoxLayout in this app relies on.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

from speech_to_text.gui import theme
from speech_to_text.gui.i18n import t
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.steps import Step
from speech_to_text.gui.theme import COLORS, Fonts, Spacing

# Ordered (Step, i18n-key) pairs. The label text reuses each step's own
# former DISPLAY-heading key rather than inventing new copy: the whole
# point of this indicator is to carry that naming job instead of
# duplicating it - see the module docstring.
_STEP_LABELS = [
    (Step.FILE_SELECT, "specs_title"),
    (Step.MODEL_SELECT, "choose_model"),
    (Step.TRANSCRIPTION, "transcribing_title"),
]

# Small and deliberately so: this strip has to fit inside the ~23px of
# slack that removing a step's DISPLAY heading (45px title + 8px spacer)
# leaves over the stepper's own cost, once the window's height budget is
# divided between header, this strip, the stacked widget, and the nav bar
# - see probe2.py's before/after numbers in the redesign notes. 20px keeps
# the circle legible (a 1-digit numeral or the check glyph both read fine
# at this size) without pushing step 1 back into overflow.
#
# That budget used to be the window's fixed 650x600 size; the window is
# resizable now (see MainWindow.__init__ and config.py's GUI_WINDOW_*
# constants), with a real minimum height enforced instead of a hard cap -
# the badge size and its layout margins below (see __init__) are still
# sized against that same measured content floor, just re-measured against
# the current minimum rather than a fixed window.
_BADGE_SIZE = 20
_BADGE_RADIUS = _BADGE_SIZE // 2
_CHECK_ICON_SIZE = 12


class StepIndicator(QFrame):
    """Three-segment "where am I" strip: a number/check badge plus a label per step."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(theme.frame_bg_qss("bg_secondary"))
        self._current_step = Step.FILE_SELECT

        layout = QHBoxLayout(self)
        # Horizontal margins match the XXL used as the step pages' own side
        # margin, so the badges/labels line up under the content they
        # describe rather than reading as a separately-aligned strip.
        #
        # Vertical margin is Spacing.SM (8px) top and bottom, not zero.
        # It used to be zero on the theory that every pixel of height here
        # was a pixel taken from the stacked widget's own budget inside the
        # window's then-fixed 650x600 size - true at the time, but the very
        # next commit after that comment was written made the window
        # resizable with a real minimum instead of a hard cap (see
        # config.py's GUI_WINDOW_MIN_HEIGHT), which is exactly the budget
        # this zero was defending. Left at zero, the fixed 20px badge sat
        # flush against the header's `border-bottom: 1px solid accent` -
        # the single brightest line in the app - with no air between them
        # at all. Spacing.SM was chosen over the smaller Spacing.XS because
        # the complaint here is the strip reading as cramped, not merely
        # touching; XS (4px) would clear the divider but barely register
        # around a 20px badge. See GUI_WINDOW_MIN_HEIGHT's own comment in
        # config.py for the height budget this costs and where it was found
        # from.
        layout.setContentsMargins(Spacing.XXL, Spacing.SM, Spacing.XXL, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        self._badges: list[QLabel] = []
        self._texts: list[QLabel] = []

        for i, (_step, key) in enumerate(_STEP_LABELS):
            badge = QLabel()
            badge.setFixedSize(_BADGE_SIZE, _BADGE_SIZE)
            badge.setAlignment(Qt.AlignCenter)
            layout.addWidget(badge)
            self._badges.append(badge)

            text = QLabel(t(key))
            text.setFont(Fonts.CAPTION_BOLD)
            text.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            layout.addWidget(text)
            self._texts.append(text)

            # Segments fan out across the full strip width via a stretch
            # between each pair, rather than sitting clumped at the
            # leading edge - matches the visual weight of a real
            # multi-step progress bar without drawing an actual connecting
            # line (which would need its own fill-state per segment gap,
            # more moving parts than this status display earns).
            if i < len(_STEP_LABELS) - 1:
                layout.addStretch()

        self.set_current(Step.FILE_SELECT)

    def set_current(self, step: Step) -> None:
        """Repaint every segment for `step` being the current one."""
        self._current_step = step
        current_index = [s for s, _ in _STEP_LABELS].index(step)
        for i, ((_, key), badge, text) in enumerate(zip(_STEP_LABELS, self._badges, self._texts)):
            if i < current_index:
                self._paint_completed(badge, text, i, key)
            elif i == current_index:
                self._paint_current(badge, text, i, key)
            else:
                self._paint_pending(badge, text, i, key)

    def retranslate(self) -> None:
        """Re-render label text and per-state accessible names (live language toggle)."""
        self.set_current(self._current_step)

    def _paint_current(self, badge: QLabel, text: QLabel, index: int, key: str) -> None:
        badge.clear()  # drop any check pixmap left from a previous "completed" paint
        badge.setText(str(index + 1))
        badge.setFont(Fonts.CAPTION_BOLD)
        badge.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: {COLORS['accent_text']}; "
            f"border-radius: {_BADGE_RADIUS}px; border: none;"
        )
        text.setText(t(key))
        text.setStyleSheet(theme.text_qss("text_primary"))
        status = t("step_status_current")
        accessible = f"{t(key)} - {status}"
        badge.setAccessibleName(accessible)
        text.setAccessibleName(accessible)

    def _paint_completed(self, badge: QLabel, text: QLabel, index: int, key: str) -> None:
        badge.clear()
        badge.setPixmap(
            svg_to_pixmap(
                ICONS["check"], _CHECK_ICON_SIZE, COLORS["success"], dpr=self.devicePixelRatioF()
            )
        )
        badge.setStyleSheet(
            f"background-color: transparent; border-radius: {_BADGE_RADIUS}px; "
            f"border: {theme.Border.CONTROL}px solid {COLORS['success']};"
        )
        text.setText(t(key))
        text.setStyleSheet(theme.text_qss("text_secondary"))
        status = t("step_status_done")
        accessible = f"{t(key)} - {status}"
        badge.setAccessibleName(accessible)
        text.setAccessibleName(accessible)

    def _paint_pending(self, badge: QLabel, text: QLabel, index: int, key: str) -> None:
        badge.clear()  # drop any check pixmap left from a previous "completed" paint
        badge.setText(str(index + 1))
        badge.setFont(Fonts.CAPTION_BOLD)
        badge.setStyleSheet(
            f"background-color: transparent; color: {COLORS['text_tertiary']}; "
            f"border-radius: {_BADGE_RADIUS}px; border: {theme.Border.CONTROL}px solid transparent;"
        )
        text.setText(t(key))
        text.setStyleSheet(theme.text_qss("text_tertiary"))
        status = t("step_status_pending")
        accessible = f"{t(key)} - {status}"
        badge.setAccessibleName(accessible)
        text.setAccessibleName(accessible)
