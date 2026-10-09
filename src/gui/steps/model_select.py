"""Step 2: model selection, with a live, data-driven recommendation."""

import logging
import os
from typing import cast

from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QMargins,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QIcon, QMouseEvent, QResizeEvent, QShowEvent
from PyQt5.QtWidgets import (
    QWIDGETSIZE_MAX,
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config
from gui import motion, theme
from gui.focus import PROPERTY as KBD_FOCUS_PROPERTY
from gui.i18n import format_duration, is_rtl, model_text, t
from gui.icons import ICONS, svg_to_pixmap
from gui.motion import with_alpha
from gui.terms_dialog import TermsDialog, read_term_list
from gui.theme import COLORS, Fonts, Motion, Spacing
from gui.widgets import make_label
from hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)


def _model_is_downloaded(repo: str) -> bool:
    """Best-effort guess at whether `repo` is in faster-whisper's cache, so a
    card can skip its download warning.

    Reads huggingface_hub's undocumented "models--owner--repo/snapshots"
    layout under config.MODEL_DOWNLOAD_ROOT (the loader's own root). Fails
    toward "not downloaded" on any doubt: a redundant note is mildly annoying,
    but promising no multi-GB download when one is coming would cost real time.
    """
    try:
        repo_id = repo if "/" in repo else f"Systran/faster-whisper-{repo}"
        cache_dir_name = "models--" + repo_id.replace("/", "--")
        snapshots_dir = os.path.join(config.MODEL_DOWNLOAD_ROOT, cache_dir_name, "snapshots")
        return os.path.isdir(snapshots_dir) and bool(os.listdir(snapshots_dir))
    except OSError:
        return False


# The speaker count's range. One person means "skip speaker identification":
# there is nobody to tell apart, and it is how a run turns the second pass
# off now that there is no separate checkbox for it. Ten keeps the clustering
# meaningful - beyond that the count is realistically unknown.
MIN_SPEAKERS = 1
MAX_SPEAKERS = 10
DEFAULT_SPEAKERS = 2

# Chips past this many are never built, however wide the panel gets: the
# "+N more" label covers the rest, and a list can run to hundreds of terms.
_MAX_CHIPS = 12


class _TermChips(QWidget):
    """A single row of term chips, as many as fit, then "+N more".

    Qt has no flow layout, and a wrapping one would make the panel's height
    depend on the term list. One row whose chip count follows the width keeps
    the panel a fixed height in both languages and at any window size.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._terms: list[str] = []
        self._chips: list[QLabel] = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(Spacing.XS + 2)
        self._more = make_label(font=Fonts.CAPTION, color="text_tertiary")
        self._row.addWidget(self._more)
        self._row.addStretch()
        # Ignored, not Preferred: the chips' own widths must never push the
        # panel (and with it the window's minimum width) wider - the panel
        # decides the width, and _fit decides how many chips fill it.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_terms(self, terms: list[str]) -> None:
        for chip in self._chips:
            self._row.removeWidget(chip)
            chip.deleteLater()
        self._terms = list(terms)
        self._chips = []
        for i, term in enumerate(self._terms[:_MAX_CHIPS]):
            chip = QLabel(term)
            chip.setFont(Fonts.CAPTION)
            chip.setStyleSheet(theme.term_chip_qss())
            self._row.insertWidget(i, chip)
            self._chips.append(chip)
        self._fit()

    def sizeHint(self) -> QSize:
        return QSize(0, self._more.sizeHint().height() + 6)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._fit()

    def retranslate(self) -> None:
        self._fit()

    def _more_text(self, hidden: int) -> str:
        return t("terms_more", n=hidden)

    def _fit(self) -> None:
        if not self._terms:
            for chip in self._chips:
                chip.hide()
            self._more.setText(t("terms_none"))
            self._more.show()
            return
        spacing = self._row.spacing()
        metrics = self._more.fontMetrics()
        width = self.width()
        used = 0
        shown = 0
        for i, chip in enumerate(self._chips):
            need = chip.sizeHint().width() + (spacing if i else 0)
            rest = len(self._terms) - (i + 1)
            reserve = metrics.horizontalAdvance(self._more_text(rest)) + spacing if rest else 0
            if used + need + reserve > width:
                break
            used += need
            shown += 1
        for i, chip in enumerate(self._chips):
            chip.setVisible(i < shown)
        hidden = len(self._terms) - shown
        self._more.setText(self._more_text(hidden))
        self._more.setVisible(hidden > 0)


class ModelSelectStep(QFrame):
    """Step 2: Model Selection with recommendation and time estimates."""

    model_selected = pyqtSignal(str)  # model_size

    def __init__(self, hardware: HardwareDetector, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hardware = hardware
        self._init_card_state()
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = self._build_page_layout()
        self._build_error_banner(layout)
        self._build_calibration_note(layout)
        self._build_model_cards(layout)
        self._build_tab_chain()

    def _init_card_state(self) -> None:
        """The per-model bookkeeping every card and every refresh reads.

        All of it has to exist before the first card is built, since
        _create_model_card populates these as it goes.
        """
        self.audio_duration = 0
        self._time_labels: dict[str, QLabel] = {}  # model -> its "Est. time" value
        self._first_use_labels: dict[str, QLabel] = {}  # model -> "Ready" / "↓ 1.6 GB"
        self._purpose_labels: dict[str, QLabel] = {}
        self._accuracy_labels: dict[str, QLabel] = {}
        # (label, i18n key) for every fact caption, so retranslate() can
        # re-render them without knowing which card each belongs to.
        self._fact_captions: list[tuple[QLabel, str]] = []
        # Every label pinned with _card_text_alignment(): retranslate() has
        # to flip all of them when the language (and so the side) changes.
        self._aligned_labels: list[QLabel] = []
        self._card_radios: dict[QObject, QRadioButton] = {}  # card -> its radio
        self._speaker_count = DEFAULT_SPEAKERS
        # model_name -> last computed estimate, in SECONDS. Seconds, not the
        # rendered string: the units are translated (see i18n.format_duration),
        # so a cached string would survive a language toggle - retranslate()
        # deliberately re-renders text without recomputing estimates, and
        # would have left every card reading "Est: 1m 46s" in a Hebrew UI.
        self._time_secs: dict[str, int] = {}
        self._name_labels: dict[str, QLabel] = {}  # model_name -> the model name QLabel
        self._cards: dict[str, QFrame] = {}  # model_name -> QFrame card
        self._radio_cards: dict[QObject, QFrame] = {}  # radio -> its own card, for
        # _sync_card_focus_ring below - see that method's docstring for why
        # the card (not the radio Qt actually focuses) needs its own
        # keyboard-focus ring.
        # model_name -> "RECOMMENDED" QLabel (always created, shown/hidden)
        self._badges: dict[str, QLabel] = {}
        # Checked once: nothing downloads a model mid-session without a restart.
        # str(): MODELS values type as object, but "repo" is always a string.
        self._downloaded = {
            name: _model_is_downloaded(str(info["repo"])) for name, info in config.MODELS.items()
        }
        # (key, params) of the last shown error, for retranslation. Annotated
        # rather than left to inference: mypy only widens a bare `= None` to
        # an optional when the assignment sits in __init__ itself, so moving
        # this line here would otherwise pin the attribute to None and make
        # show_error's assignment an error.
        self._error_key: str | None = None
        self._error_params: dict[str, object] = {}
        self._user_touched_model = False  # True once the user manually picks a model
        self._syncing = False  # True while we're programmatically re-checking a radio

    def _build_page_layout(self) -> QVBoxLayout:
        """The step's layout, on the tightest page: cards, speaker row and the
        error/calibration strips share 600 px, so spacing is tighter here.
        """
        layout = QVBoxLayout(self)
        # Tighter than steps 1/3 (XS, not SM) - every px of vertical gap
        # here is a px the card list's scroll area doesn't get.
        layout.setSpacing(Spacing.XS)
        # Wide side margins (free), tight vertical ones (scarce here).
        layout.setContentsMargins(Spacing.XXL, Spacing.SM, Spacing.XXL, Spacing.SM)

        # No page title here any more - "Choose Model" is now carried by
        # the wizard step indicator above the stacked widget (see
        # gui/stepper.py). Dropping it also buys back height on the one
        # step that has the least to spare (see the room analysis in
        # theme.Spacing's docstring).
        return layout

    def _build_error_banner(self, layout: QVBoxLayout) -> None:
        """The inline failure strip at the top of the page."""
        # Error banner - shown inline (instead of a modal popup) if a
        # transcription attempt fails and the user is sent back here to
        # retry. Hidden until show_error() is called.
        self.error_banner = QFrame()
        self.error_banner.setObjectName("modelErrorBanner")
        self.error_banner.setStyleSheet(theme.error_banner_qss("modelErrorBanner"))
        # Second (and last) surface that gets the drop shadow - see
        # theme.elevation_shadow's docstring. Subtler than the result
        # panel's default: the banner is a slim single-line strip, not a
        # big centered block, so a shadow as strong as the result panel's
        # would read as heavier than the banner's own visual weight.
        self.error_banner.setGraphicsEffect(
            theme.elevation_shadow(blur_radius=20, y_offset=6, alpha=110)
        )
        self.error_banner.hide()
        error_layout = QHBoxLayout(self.error_banner)
        error_layout.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
        error_layout.setSpacing(Spacing.XS)

        error_icon = QLabel()
        error_icon.setPixmap(
            svg_to_pixmap(ICONS["alert_circle"], 16, COLORS["error"], dpr=self.devicePixelRatioF())
        )
        error_icon.setStyleSheet("background: transparent;")
        error_layout.addWidget(error_icon)

        self.error_label = make_label(font=Fonts.CAPTION, color="error")
        self.error_label.setWordWrap(True)
        error_layout.addWidget(self.error_label, 1)

        # Copies the rendered message plus whatever raw detail/traceback the
        # failure carried, plus the log file path - so a bug report has the
        # real error text instead of whatever the user happens to have on
        # their clipboard. Hidden until show_error() shows it alongside the
        # label; clear_error() hides it again.
        self.copy_error_btn = QPushButton(t("copy_error_details"))
        self.copy_error_btn.clicked.connect(self._on_copy_error_details)
        error_layout.addWidget(self.copy_error_btn)

        layout.addWidget(self.error_banner)
        self._banner_reveal: QParallelAnimationGroup | None = None

    def _build_calibration_note(self, layout: QVBoxLayout) -> None:
        """The "these estimates are guesses so far" line under the banner."""
        # Calibration note: estimates are placeholders until the background
        # benchmark lands (usually before this step is reached). States in
        # _set_calibration_note and mark_calibration_unmeasured.
        self._calibration_note_key: str | None = None
        self.calibration_note = make_label(font=Fonts.CAPTION, color="text_tertiary")
        self.calibration_note.setWordWrap(True)
        self.calibration_note.hide()
        layout.addWidget(self.calibration_note)
        if self.hardware.tiny_seconds_per_audio_second is None:
            self._set_calibration_note("calibration_pending")

    def _build_model_cards(self, layout: QVBoxLayout) -> None:
        """The scrollable page body: the model cards, the line saying what
        their estimates assume, and the speakers and custom terms panels.
        """
        # One scroll area for all of it, so a short window scrolls the page
        # rather than squeezing or clipping the panels at the bottom.
        models_container = QWidget()
        models_layout = QVBoxLayout(models_container)
        models_layout.setSpacing(Spacing.SM + 2)
        models_layout.setContentsMargins(0, 0, 0, 0)

        models_scroll = self._build_models_scroll(models_container)

        # Model selection
        self.model_group = QButtonGroup()
        self.model_radios: dict[str, QRadioButton] = {}
        recommended_model, _ = self.hardware.recommend_model(self.audio_duration)
        self.selected_model = recommended_model
        self._current_recommended = recommended_model

        for i, model_name in enumerate(config.MODELS):
            model_card = self._create_model_card(
                i, model_name, is_recommended=(model_name == recommended_model)
            )
            models_layout.addWidget(model_card)

        self.estimate_footnote = self._aligned_label(Fonts.CAPTION, "text_tertiary")
        self.estimate_footnote.setWordWrap(True)
        models_layout.addWidget(self.estimate_footnote)
        self._refresh_footnote()

        models_layout.addStretch()
        models_layout.addWidget(self._build_options_row())
        # Stretch factor 1: the scroll area takes the leftover vertical space,
        # so the page grows with the window instead of scrolling needlessly.
        layout.addWidget(models_scroll, 1)

        # Scroll the recommended card into view on first show: in a short
        # window it can start off below the fold.
        self._scroll_area = models_scroll

    def _build_models_scroll(self, models_container: QWidget) -> QScrollArea:
        """The scroll area wrapping the card list, watching its own viewport."""
        models_scroll = QScrollArea()
        models_scroll.setWidget(models_container)
        models_scroll.setWidgetResizable(True)
        models_scroll.setFrameShape(QFrame.NoFrame)
        models_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        models_scroll.setStyleSheet("background: transparent;")
        # setWidgetResizable only re-fits on the scroll area's own resize, not
        # when a scrollbar appears and narrows the viewport (e.g. once the
        # calibration lengthens the estimates) - the cards then overflow and
        # lose their right border. Watching the viewport's resize fixes that.
        viewport = models_scroll.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)
        return models_scroll

    def _build_tab_chain(self) -> None:
        """Wire Tab to follow the page's visual order, not creation order."""
        # Every model radio in config.MODELS order, then the speaker count's
        # - and + buttons, then the custom terms Edit button - top to bottom,
        # then leading to trailing edge.
        radios_in_order = [self.model_radios[name] for name in config.MODELS]
        for earlier, later in zip(radios_in_order, radios_in_order[1:]):
            self.setTabOrder(earlier, later)
        self.setTabOrder(radios_in_order[-1], self.speakers_minus_btn)
        self.setTabOrder(self.speakers_minus_btn, self.speakers_plus_btn)
        self.setTabOrder(self.speakers_plus_btn, self.terms_button)

    def _aligned_label(self, font: QFont, color: str, text: str = "") -> QLabel:
        """A label pinned to the radio's side of the card (see
        _card_text_alignment), registered so retranslate() can re-pin it.
        """
        label = make_label(text, font=font, color=color, align=self._card_text_alignment())
        self._aligned_labels.append(label)
        return label

    def _build_options_row(self) -> QWidget:
        """The speakers and custom terms panels, side by side.

        Under the cards rather than beside them because both apply to the run
        as a whole, not to whichever model is picked.
        """
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)
        layout.addWidget(self._build_speakers_panel(), 1)
        layout.addWidget(self._build_terms_panel(), 1)
        return row

    def _option_panel(
        self, object_name: str, icon: str, title: QLabel
    ) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
        """A panel frame with its icon-and-title header row already in place;
        the header comes back too, for a panel that adds to its end.
        """
        panel = QFrame()
        panel.setObjectName(object_name)
        panel.setStyleSheet(theme.option_panel_qss(object_name))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.XS + 2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(Spacing.SM)
        icon_label = QLabel()
        icon_label.setPixmap(
            svg_to_pixmap(ICONS[icon], 20, COLORS["accent"], dpr=self.devicePixelRatioF())
        )
        icon_label.setStyleSheet("background: transparent;")
        header.addWidget(icon_label)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        return panel, layout, header

    def _build_speakers_panel(self) -> QFrame:
        """The speaker count, as a - n + stepper: the exact count is the biggest
        diarization accuracy lever, and buttons cannot be mistyped.
        """
        self.speakers_title = self._aligned_label(
            Fonts.BODY_BOLD, "text_primary", t("speakers_title")
        )
        panel, layout, _ = self._option_panel("speakersPanel", "users", self.speakers_title)

        self.speakers_sub = self._aligned_label(Fonts.CAPTION, "text_secondary")
        self.speakers_sub.setWordWrap(True)
        layout.addWidget(self.speakers_sub)
        # Pushes the count row to the bottom edge, so it lines up with the
        # chips row in the terms panel beside it.
        layout.addStretch()

        count_row = QHBoxLayout()
        count_row.setContentsMargins(0, 0, 0, 0)
        count_row.setSpacing(Spacing.SM)
        self.speaker_count_label = self._aligned_label(
            Fonts.CAPTION, "text_tertiary", t("speaker_count")
        )
        self.speaker_count_label.setWordWrap(True)
        count_row.addWidget(self.speaker_count_label, 1)

        self.speakers_minus_btn = self._speaker_step_button("minus", -1)
        count_row.addWidget(self.speakers_minus_btn)
        self.speaker_count_value = make_label(
            font=Fonts.SUBTITLE_BOLD, color="text_primary", align=Qt.AlignmentFlag.AlignCenter
        )
        self.speaker_count_value.setMinimumWidth(28)
        count_row.addWidget(self.speaker_count_value)
        self.speakers_plus_btn = self._speaker_step_button("plus", 1)
        count_row.addWidget(self.speakers_plus_btn)
        layout.addLayout(count_row)

        self._sync_speaker_controls()
        return panel

    def _speaker_step_button(self, icon: str, step: int) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(32, 32)
        button.setIcon(
            QIcon(
                svg_to_pixmap(ICONS[icon], 14, COLORS["text_primary"], dpr=self.devicePixelRatioF())
            )
        )
        button.setIconSize(QSize(14, 14))
        button.setStyleSheet(theme.round_button_qss())
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._step_speakers(step))
        return button

    def _step_speakers(self, step: int) -> None:
        count = max(MIN_SPEAKERS, min(MAX_SPEAKERS, self._speaker_count + step))
        if count == self._speaker_count:
            return
        self._speaker_count = count
        self._sync_speaker_controls()
        # Speaker identification is a second pass over the audio, so going to
        # or from one person changes every card's estimate.
        self._refresh_desc_labels(recompute=True)
        self._refresh_footnote()

    def _sync_speaker_controls(self) -> None:
        """Count, the sentence above it, the buttons' limits and their names."""
        count = self._speaker_count
        self.speaker_count_value.setText(str(count))
        self.speaker_count_value.setAccessibleName(t("speaker_count"))
        self.speakers_sub.setText(t("speakers_sub" if count > 1 else "speakers_sub_one"))
        self.speakers_minus_btn.setEnabled(count > MIN_SPEAKERS)
        self.speakers_plus_btn.setEnabled(count < MAX_SPEAKERS)
        self.speakers_minus_btn.setAccessibleName(t("speakers_fewer"))
        self.speakers_plus_btn.setAccessibleName(t("speakers_more"))

    def _build_terms_panel(self) -> QFrame:
        """The custom term list at a glance: how many, the first few, Edit."""
        self.terms_title = self._aligned_label(Fonts.BODY_BOLD, "text_primary", t("terms_title"))
        panel, layout, header = self._option_panel("termsPanel", "tag", self.terms_title)

        self.terms_count_label = QLabel()
        self.terms_count_label.setStyleSheet(theme.count_pill_qss())
        # Straight after the title, ahead of the header's trailing stretch.
        header.insertWidget(header.indexOf(self.terms_title) + 1, self.terms_count_label)

        self.terms_button = QPushButton(t("terms_edit"))
        self.terms_button.setObjectName("termsButton")
        self.terms_button.setFont(Fonts.CAPTION_BOLD)
        self.terms_button.setStyleSheet(theme.button_secondary_qss(padding="0px 12px"))
        # Exactly twice Radius.CONTROL: Qt draws no rounding at all once a
        # radius exceeds half the button's height, so a shorter button would
        # come out square-cornered.
        self.terms_button.setFixedHeight(2 * theme.Radius.CONTROL)
        self.terms_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.terms_button.clicked.connect(self._open_terms)
        header.addWidget(self.terms_button)

        self.terms_sub = self._aligned_label(Fonts.CAPTION, "text_secondary", t("terms_sub"))
        self.terms_sub.setWordWrap(True)
        layout.addWidget(self.terms_sub)
        layout.addStretch()

        self.term_chips = _TermChips()
        layout.addWidget(self.term_chips)
        self._refresh_terms()
        return panel

    def _refresh_terms(self) -> None:
        """Count, chips and tooltip from the list as it is on disk right now."""
        terms = read_term_list()
        self.terms_count_label.setText(str(len(terms)))
        self.term_chips.set_terms(terms)
        self.terms_button.setToolTip(t("terms_button_tooltip", path=config.resolve_terms_path()))
        self.terms_button.setAccessibleName(t("terms_title") + ": " + t("terms_edit"))

    def _open_terms(self) -> None:
        TermsDialog(self).exec_()
        self._refresh_terms()

    @property
    def identify_speakers(self) -> bool:
        return self._speaker_count > 1

    @property
    def num_speakers(self) -> int:
        return self._speaker_count

    def show_error(self, key: str, params: dict[str, object]) -> None:
        """Show an inline failure banner (used instead of a modal popup).
        Takes an i18n key + params (see TranscriptionThread.error) so the
        banner can be re-rendered if the language is toggled while shown.
        """
        self._error_key = key
        self._error_params = dict(params)
        self.error_label.setText(t("transcription_failed", message=t(key, **params)))
        already_shown = not self.error_banner.isHidden()
        self.error_banner.show()
        if not already_shown:
            self._reveal_banner()

    def clear_error(self) -> None:
        self._error_key = None
        self._error_params = {}
        self._end_banner_reveal()
        self.error_banner.hide()

    def _reveal_banner(self) -> None:
        """Grow the banner open while its message fades in.

        The fade is the label's ink alpha, not an opacity effect: the banner
        already holds its drop shadow, and a widget carries one effect.
        """
        self._end_banner_reveal()
        if not motion.animations_enabled():
            return
        # The wrapped height at the page's width; sizeHint() is unwrapped and
        # taller, so the grow would stall at the layout's cap.
        layout = self.layout()
        margins = layout.contentsMargins() if layout is not None else QMargins()
        width = self.width() - margins.left() - margins.right()
        height = (
            self.error_banner.heightForWidth(width) if self.error_banner.hasHeightForWidth() else -1
        )
        if height <= 0:
            height = self.error_banner.sizeHint().height()
        group = QParallelAnimationGroup(self)
        grow = QPropertyAnimation(self.error_banner, b"maximumHeight", group)
        grow.setStartValue(0)
        grow.setEndValue(height)
        grow.setDuration(Motion.BANNER_MS)
        grow.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade = QVariantAnimation(group)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(int(Motion.BANNER_MS * 1.4))
        fade.valueChanged.connect(self._set_banner_ink)
        group.addAnimation(grow)
        group.addAnimation(fade)
        group.finished.connect(self._end_banner_reveal)
        self._banner_reveal = group
        self._set_banner_ink(0.0)
        group.start()

    def _set_banner_ink(self, alpha: float) -> None:
        color = with_alpha("error", alpha)
        self.error_label.setStyleSheet(
            f"color: {color.name(QColor.NameFormat.HexArgb)}; background: transparent;"
        )

    def _end_banner_reveal(self) -> None:
        """Stop any reveal and leave the banner at its natural size and ink."""
        if self._banner_reveal is not None:
            self._banner_reveal.stop()
            self._banner_reveal.deleteLater()
            self._banner_reveal = None
        self.error_banner.setMaximumHeight(QWIDGETSIZE_MAX)
        self.error_label.setStyleSheet(theme.text_qss("error"))

    def _on_copy_error_details(self) -> None:
        """Copy the real error text/traceback/log path, not just the friendly banner text."""
        if self._error_key is None:
            return
        rendered = t("transcription_failed", message=t(self._error_key, **self._error_params))
        parts = [rendered]
        detail = self._error_params.get("detail")
        if detail:
            parts.append(str(detail))
        tb = self._error_params.get("traceback")
        if tb:
            parts.append(str(tb))
        parts.append(f"Log file: {config.resolve_log_path()}")
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n\n".join(parts))

        original_text = self.copy_error_btn.text()
        self.copy_error_btn.setText(t("error_details_copied"))
        QTimer.singleShot(1500, lambda: self.copy_error_btn.setText(original_text))

    def _on_radio_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self.selected_model = name
            self.model_selected.emit(name)
            self._apply_selection(name)
            if not self._syncing:
                # A real click (not our own programmatic re-sync) - stop
                # auto-following the recommendation as it updates.
                self._user_touched_model = True

    def _apply_selection(self, name: str) -> None:
        """Accent the selected card's border and time estimate. (A drop shadow
        was tried: the scroll area clips it, so it was invisible.)
        """
        for card_name, card in self._cards.items():
            selected = card_name == name
            card.setStyleSheet(theme.card_qss(f"modelCard_{card_name}", selected=selected))
            self._time_labels[card_name].setStyleSheet(
                theme.text_qss("accent" if selected else "text_primary")
            )

    def _describe_radio(self, name: str, radio: QRadioButton) -> None:
        """Name the radio and give it the spoken form of the facts row (RAM,
        pending download), which a screen reader would otherwise read as eight
        unrelated labels.
        """
        radio.setAccessibleName(model_text(name, "name"))
        radio.setAccessibleDescription(
            model_text(name, "description") + ". " + self._info_note(name)
        )

    def _info_note(self, name: str) -> str:
        """RAM, plus the download sentence for an uncached model - shared by
        the tooltip and the accessible description so they cannot drift.
        """
        info = config.MODELS[name]
        note = t("model_ram_tooltip", ram=info["ram_required"])
        if not self._downloaded[name]:
            note = note + " " + t("model_download_tooltip", size=info["download_size"])
        return note

    def _create_model_card(self, idx: int, name: str, is_recommended: bool = False) -> QFrame:
        """A model card: radio, name and badge; a sentence on when to pick
        it; and a row of facts - time, accuracy, memory, download.
        """
        card = QFrame()
        object_name = f"modelCard_{name}"
        card.setObjectName(object_name)
        # Initially, the recommended model is also the selected one.
        card.setStyleSheet(theme.card_qss(object_name, selected=is_recommended))
        # Mouse-hover equivalent of the radio's accessible description (set
        # in _build_card_radio).
        card.setToolTip(self._info_note(name))
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.XS + 2)

        radio = self._build_card_radio(idx, name, card, is_recommended)
        layout.addLayout(self._build_card_name_row(name, radio, is_recommended))

        # The purpose line and facts start under the name, not under the
        # radio, so the card reads as one indented block beside its control.
        indent = radio.sizeHint().width() + Spacing.SM
        purpose = self._aligned_label(Fonts.CAPTION, "text_secondary", model_text(name, "purpose"))
        purpose.setWordWrap(True)
        self._purpose_labels[name] = purpose
        layout.addLayout(self._indented(purpose, indent))
        layout.addLayout(self._indented(self._build_card_facts(name, is_recommended), indent))

        # The whole card picks its model, not just the 18px radio: with a
        # sentence and four facts on it, the card is what people aim at.
        card.installEventFilter(self)
        self._card_radios[card] = radio
        self._cards[name] = card
        return card

    @staticmethod
    def _indented(widget: QWidget, indent: int) -> QHBoxLayout:
        """`widget` behind a leading gap. A row, not a left margin: an
        QHBoxLayout mirrors under RTL, so the gap moves to the radio's side.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addSpacing(indent)
        row.addWidget(widget, 1)
        return row

    def _build_card_facts(self, name: str, is_recommended: bool) -> QFrame:
        """Four captioned facts in a row, under a hairline."""
        facts = QFrame()
        object_name = f"modelFacts_{name}"
        facts.setObjectName(object_name)
        facts.setStyleSheet(theme.card_facts_qss(object_name))
        grid = QGridLayout(facts)
        grid.setContentsMargins(0, Spacing.SM, 0, 0)
        grid.setHorizontalSpacing(Spacing.MD)
        grid.setVerticalSpacing(2)

        info = config.MODELS[name]
        time_value = self._aligned_label(
            Fonts.BODY_BOLD_SMALL, "accent" if is_recommended else "text_primary"
        )
        self._time_labels[name] = time_value
        time_value.setText(self._time_text(name))
        accuracy_value = self._aligned_label(
            Fonts.BODY_BOLD_SMALL, "text_primary", model_text(name, "accuracy")
        )
        self._accuracy_labels[name] = accuracy_value
        memory_value = self._aligned_label(
            Fonts.BODY_BOLD_SMALL, "text_primary", str(info["ram_required"])
        )
        first_use_value = self._aligned_label(
            Fonts.BODY_BOLD_SMALL, "success" if self._downloaded[name] else "text_primary"
        )
        first_use_value.setText(self._first_use_text(name))
        self._first_use_labels[name] = first_use_value

        columns = (
            ("model_fact_time", time_value),
            ("model_fact_accuracy", accuracy_value),
            ("model_fact_memory", memory_value),
            ("model_fact_first_use", first_use_value),
        )
        for col, (key, value) in enumerate(columns):
            caption = self._aligned_label(Fonts.CAPTION, "text_tertiary", t(key))
            self._fact_captions.append((caption, key))
            grid.addWidget(caption, 0, col)
            grid.addWidget(value, 1, col)
            grid.setColumnStretch(col, 1)
        return facts

    def _first_use_text(self, name: str) -> str:
        if self._downloaded[name]:
            return t("model_ready")
        # Direct dict access, not .get() - a model added to config.MODELS
        # without a download_size should raise here at card-build time,
        # not render a blank/"None" fact that's easy to miss in review.
        return t("model_download_fact", size=config.MODELS[name]["download_size"])

    def _build_card_radio(
        self, idx: int, name: str, card: QFrame, is_recommended: bool
    ) -> QRadioButton:
        """The card's radio, and the registrations that let the rest of the
        step find it again: the button group, model_radios, and the
        radio -> card mapping the focus ring needs.
        """
        # Radio button. It carries no text of its own - the model name and
        # description are separate QLabels beside it - so without an explicit
        # accessible name a screen reader would announce every one of these
        # radios identically as just "radio button".
        radio = QRadioButton()
        radio.setChecked(is_recommended)
        radio.toggled.connect(lambda checked: self._on_radio_toggled(name, checked))
        self._describe_radio(name, radio)
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        # The card frame, not the radio, has to show the keyboard-focus ring
        # (see _sync_card_focus_ring's docstring) - the radio is what Qt
        # actually gives focus to (it's the only focusable widget on the
        # card), so this step has to react on the radio's behalf.
        self._radio_cards[radio] = card
        radio.installEventFilter(self)
        return radio

    def _build_card_name_row(
        self, name: str, radio: QRadioButton, is_recommended: bool
    ) -> QHBoxLayout:
        """The radio, the model name and its RECOMMENDED badge, side by side."""
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(Spacing.SM)
        name_row.addWidget(radio)

        model_label = self._aligned_label(Fonts.BODY_BOLD, "text_primary", model_text(name, "name"))
        self._name_labels[name] = model_label
        name_row.addWidget(model_label)

        # Recommended badge - always created so update_audio_duration can
        # show/hide it as the real recommendation shifts, instead of only
        # ever reflecting the recommendation computed at construction time.
        badge = QLabel(t("recommended_badge"))
        badge.setStyleSheet(theme.badge_qss())
        badge.setVisible(is_recommended)
        name_row.addWidget(badge)
        name_row.addStretch()
        self._badges[name] = badge

        return name_row

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        """Forward each radio's focus changes to its card's focus ring (see
        _sync_card_focus_ring). Never consumes the event.
        """
        if obj is None or event is None:
            return super().eventFilter(obj, event)
        # Bound once rather than repeated in both branches below.
        focus_in = QEvent.Type.FocusIn
        focus_out = QEvent.Type.FocusOut
        resize = QEvent.Type.Resize
        card = self._radio_cards.get(obj)
        card_radio = self._card_radios.get(obj)
        if card is not None and event.type() in (focus_in, focus_out):
            self._sync_card_focus_ring(card, focused_in=event.type() == focus_in)
        elif card_radio is not None and event.type() == QEvent.Type.MouseButtonRelease:
            if cast(QMouseEvent, event).button() == Qt.MouseButton.LeftButton:
                card_radio.setChecked(True)
        elif event.type() == resize:
            scroll = getattr(self, "_scroll_area", None)
            # getattr, not a plain attribute: the filter is installed while
            # the scroll area is still a local in __init__, so the first
            # viewport resize can arrive before _scroll_area is bound.
            if scroll is not None and obj is scroll.viewport():
                self._sync_container_width()
        return super().eventFilter(obj, event)

    def _sync_container_width(self) -> None:
        """Keep the card container as wide as the viewport (width only, so the
        layout's height is untouched; it converges in one step).
        """
        container = self._scroll_area.widget()
        viewport = self._scroll_area.viewport()
        # Both are Optional as far as Qt is concerned. There is nothing to
        # size against without a viewport, so bail rather than dereference.
        if container is None or viewport is None:
            return
        # A maximum, not a resize: QScrollArea sizes the widget before adding
        # the scrollbar and never re-sizes it, so a resize is undone next pass.
        container.setMaximumWidth(viewport.width())
        if container.width() > viewport.width():
            container.resize(viewport.width(), container.height())

    @staticmethod
    def _sync_card_focus_ring(card: QFrame, focused_in: bool) -> None:
        """Ring the card when its radio has keyboard focus - Qt focuses the
        18 px radio, but the card is what a keyboard user scans for.

        Reads the tracker's live flag, not the radio's own property, which may
        not be set yet at FocusIn (see is_keyboard_active). Uses the focus
        colour, never the accent, so a focused card never reads as selected.
        """
        show_ring = False
        if focused_in:
            tracker = getattr(QApplication.instance(), "_kbd_focus_tracker", None)
            show_ring = bool(tracker is not None and tracker.is_keyboard_active())
        card.setProperty(KBD_FOCUS_PROPERTY, show_ring)
        # QWidget.style() is Optional (a widget with no style has nothing to
        # re-polish), so the repaint below is conditional on there being one.
        style = card.style()
        if style is not None:
            style.unpolish(card)
            style.polish(card)
        card.update()

    def _set_calibration_note(self, key: str | None) -> None:
        """Show `key`'s text as the calibration note, or hide it when key is None."""
        self._calibration_note_key = key
        if key is None:
            self.calibration_note.hide()
        else:
            self.calibration_note.setText(t(key))
            self.calibration_note.show()

    def mark_calibration_unmeasured(self) -> None:
        """The benchmark failed, so estimates stay rough for this run: replace
        "still measuring" with a resting note.
        """
        self._set_calibration_note("calibration_unmeasured")

    def update_audio_duration(self, seconds: int) -> None:
        """Recompute time estimates and the real recommendation in place, once
        the actual audio duration (and possibly a freshly finished hardware
        calibration) is known.
        """
        self.audio_duration = seconds
        self._refresh_desc_labels(recompute=True)
        self._refresh_footnote()
        # Only clear the note here if calibration is now actually known -
        # this is also called on every step-1-to-2 advance regardless of
        # calibration state (see MainWindow._go_next), so blindly hiding it
        # would erase a still-accurate "these are provisional" note the
        # moment the user picks a file, well before the benchmark is done.
        if self.hardware.tiny_seconds_per_audio_second is not None:
            self._set_calibration_note(None)

        recommended_model, _ = self.hardware.recommend_model(seconds)
        self._apply_recommendation(recommended_model)

    def showEvent(self, event: QShowEvent | None) -> None:
        """Scroll the recommended card into view, and put the first Tab stop on
        the selected model's radio (whichever the user picked, not
        necessarily the recommendation).
        """
        super().showEvent(event)
        self._scroll_to_recommended()
        radio = self.model_radios.get(self.selected_model)
        if radio is not None:
            radio.setFocus(Qt.FocusReason.OtherFocusReason)

    def _scroll_to_recommended(self) -> None:
        card = self._cards.get(self._current_recommended)
        if card is not None:
            self._scroll_area.ensureWidgetVisible(card)

    def _time_text(self, name: str) -> str:
        """One card's time estimate in the current language. The estimate is
        cached in seconds: a language toggle only re-renders text, so it must
        not re-run (and re-log) the hardware estimator - only
        update_audio_duration and a speaker count change recompute.
        """
        seconds = self._time_secs.get(name)
        if seconds is None:
            seconds, _ = self.hardware.estimate_transcription_time(
                self.audio_duration, name, identify_speakers=self.identify_speakers
            )
            self._time_secs[name] = seconds
        return format_duration(seconds)

    def _refresh_desc_labels(self, recompute: bool = False) -> None:
        if recompute:
            self._time_secs.clear()
        for name, label in self._time_labels.items():
            label.setText(self._time_text(name))

    def _refresh_footnote(self) -> None:
        """Say what the estimates assume, once there is a real duration."""
        if self.audio_duration <= 0:
            self.estimate_footnote.hide()
            return
        key = "estimate_footnote_speakers" if self.identify_speakers else "estimate_footnote"
        self.estimate_footnote.setText(t(key, duration=format_duration(self.audio_duration)))
        self.estimate_footnote.show()

    @staticmethod
    def _card_text_alignment() -> Qt.Alignment:
        """Absolute alignment beside the radio: right in Hebrew, left in English.
        Not AlignLeading, which follows each label's own text direction.
        """
        side: Qt.AlignmentFlag = (
            Qt.AlignmentFlag.AlignRight if is_rtl() else Qt.AlignmentFlag.AlignLeft
        )
        extra = cast(
            Qt.AlignmentFlag, Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        )
        # cast, not Qt.Alignment(...): PyQt5's stubs model each flag as a
        # plain int subclass and never give it an __or__ returning the flag
        # type, so an OR of two of them widens to int. The runtime value is
        # already exactly what setAlignment wants - only the static type is
        # lost - so this stays a compile-time statement with no new call.
        return cast(Qt.Alignment, side | extra)

    def retranslate(self) -> None:
        """Re-render all text in the current UI language (live toggle)."""
        alignment = self._card_text_alignment()
        for label in self._aligned_labels:
            label.setAlignment(alignment)
        self._retranslate_cards()
        self._retranslate_options()
        self._refresh_desc_labels()
        self._refresh_footnote()
        if self._calibration_note_key is not None:
            self.calibration_note.setText(t(self._calibration_note_key))
        if self._error_key is not None:
            self.error_label.setText(
                t("transcription_failed", message=t(self._error_key, **self._error_params))
            )

    def _retranslate_cards(self) -> None:
        for name, label in self._name_labels.items():
            label.setText(model_text(name, "name"))
        for name, label in self._purpose_labels.items():
            label.setText(model_text(name, "purpose"))
        for name, label in self._accuracy_labels.items():
            label.setText(model_text(name, "accuracy"))
        for name, label in self._first_use_labels.items():
            label.setText(self._first_use_text(name))
        for caption, key in self._fact_captions:
            caption.setText(t(key))
        for badge in self._badges.values():
            badge.setText(t("recommended_badge"))
        for name, radio in self.model_radios.items():
            self._describe_radio(name, radio)
        for name, card in self._cards.items():
            card.setToolTip(self._info_note(name))

    def _retranslate_options(self) -> None:
        self.speakers_title.setText(t("speakers_title"))
        self.speaker_count_label.setText(t("speaker_count"))
        self._sync_speaker_controls()
        self.terms_title.setText(t("terms_title"))
        self.terms_sub.setText(t("terms_sub"))
        self.terms_button.setText(t("terms_edit"))
        self._refresh_terms()
        self.term_chips.retranslate()

    def _apply_recommendation(self, recommended_model: str) -> None:
        """Move the RECOMMENDED badge, and the selection too unless the user has
        picked a model (the accent border follows the selection, not this).
        """
        if recommended_model == self._current_recommended:
            return
        self._current_recommended = recommended_model

        for name, badge in self._badges.items():
            badge.setVisible(name == recommended_model)

        if not self._user_touched_model:
            self._syncing = True
            self.model_radios[recommended_model].setChecked(True)
            self._syncing = False
            self._scroll_to_recommended()
