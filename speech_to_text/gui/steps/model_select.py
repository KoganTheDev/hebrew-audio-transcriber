"""Step 2: model selection, with a live, data-driven recommendation."""

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from speech_to_text import config
from speech_to_text.gui import theme
from speech_to_text.gui.i18n import is_rtl, model_text, t
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)


class ModelSelectStep(QFrame):
    """Step 2: Model Selection with recommendation and time estimates."""

    model_selected = pyqtSignal(str)  # model_size

    def __init__(self, hardware: HardwareDetector, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.audio_duration = 0
        self._desc_labels = {}  # model_name -> QLabel showing "description | Est: ..."
        self._time_strs = {}    # model_name -> last computed time-estimate display string
        self._name_labels = {}  # model_name -> QLabel showing the model name
        self._cards = {}        # model_name -> QFrame card
        self._badges = {}       # model_name -> "RECOMMENDED" QLabel (always created, shown/hidden)
        self._error_key = None      # (key, params) of the last shown error, for retranslation
        self._error_params = {}
        self._user_touched_model = False  # True once the user manually picks a model
        self._syncing = False   # True while we're programmatically re-checking a radio
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = QVBoxLayout(self)
        # Tighter than steps 1/3 (XS, not SM) - every px of vertical gap
        # here is a px the seven-card scroll area doesn't get.
        layout.setSpacing(Spacing.XS)
        # Horizontal margin widened XL -> XXL like the other two steps (it
        # costs no vertical room, which is the scarce resource on this
        # page). Vertical margin pulled in to SM, tighter than before
        # (was MD) to buy back some of the room the taller DISPLAY heading
        # spends - see the title comment above on why step 2 stays
        # conservative.
        layout.setContentsMargins(Spacing.XXL, Spacing.SM, Spacing.XXL, Spacing.SM)

        # Title. Uses Fonts.DISPLAY like the other two steps' headings for
        # a consistent hierarchy across the flow, even though step 2 is the
        # conservative one on spacing - see the room analysis in
        # theme.Spacing's docstring: seven model cards already need a
        # QScrollArea to fit, so the size increase here isn't paired with
        # the same margin/gap increases steps 1 and 3 get.
        self.title = QLabel(t("choose_model"))
        self.title.setFont(Fonts.DISPLAY)
        self.title.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.title)

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
        self.error_banner.setGraphicsEffect(theme.elevation_shadow(blur_radius=20, y_offset=6, alpha=110))
        self.error_banner.hide()
        error_layout = QHBoxLayout(self.error_banner)
        error_layout.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
        error_layout.setSpacing(Spacing.XS)

        error_icon = QLabel()
        error_icon.setPixmap(svg_to_pixmap(ICONS["alert_triangle"], 16, COLORS['error']))
        error_icon.setStyleSheet("background: transparent;")
        error_layout.addWidget(error_icon)

        self.error_label = QLabel()
        self.error_label.setFont(Fonts.CAPTION)
        self.error_label.setStyleSheet(theme.text_qss("error"))
        self.error_label.setWordWrap(True)
        error_layout.addWidget(self.error_label, 1)

        layout.addWidget(self.error_banner)

        # The cards used to be laid out directly, sized so all five fit the
        # fixed window without scrolling. Adding the two Hebrew-tuned models
        # broke that: seven cards overflow a 600px window and the last ones
        # became unreachable. They now live in a scroll area, which keeps every
        # option reachable at any window size instead of silently clipping.
        models_container = QWidget()
        models_layout = QVBoxLayout(models_container)
        models_layout.setSpacing(Spacing.XS + 2)
        models_layout.setContentsMargins(0, 0, 0, 0)

        # Built before the cards, not after: each card's time estimate depends
        # on whether speaker identification is on, so the controls have to
        # exist before _desc_text runs.
        speaker_row = self._build_speaker_row()

        models_scroll = QScrollArea()
        models_scroll.setWidget(models_container)
        models_scroll.setWidgetResizable(True)
        models_scroll.setFrameShape(QFrame.NoFrame)
        models_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        models_scroll.setStyleSheet("background: transparent;")

        # Model selection
        self.model_group = QButtonGroup()
        self.model_radios = {}
        recommended_model, _ = hardware.recommend_model(self.audio_duration)
        self.selected_model = recommended_model
        self._current_recommended = recommended_model

        for i, (model_name, model_info) in enumerate(config.MODELS.items()):
            model_card = self._create_model_card(
                i, model_name, model_info,
                is_recommended=(model_name == recommended_model)
            )
            models_layout.addWidget(model_card)

        models_layout.addStretch()
        # Stretch factor 1: the scroll area takes the leftover vertical space
        # rather than the trailing spacer, so the card list grows with the
        # window instead of staying short and scrolling unnecessarily.
        layout.addWidget(models_scroll, 1)
        layout.addWidget(speaker_row)

        # Scroll the recommended card into view on first show. It is no longer
        # guaranteed to be among the first few cards, and a user who never
        # scrolls should still see what the app is recommending.
        self._scroll_area = models_scroll

        # Explicit Tab chain, matching the page's visual top-to-bottom order:
        # every model radio in config.MODELS order, then the speaker-identify
        # checkbox, then the speaker-count spin box below the card list. Not
        # left to Qt's default (creation-order) chain because the speaker row
        # is built BEFORE the cards (see the comment above speaker_row) so
        # its widgets would otherwise sit ahead of the cards in the implicit
        # chain - backwards from how the page reads top to bottom.
        radios_in_order = [self.model_radios[name] for name in config.MODELS]
        for earlier, later in zip(radios_in_order, radios_in_order[1:]):
            self.setTabOrder(earlier, later)
        self.setTabOrder(radios_in_order[-1], self.identify_speakers_check)
        self.setTabOrder(self.identify_speakers_check, self.speaker_count_spin)

    def _build_speaker_row(self) -> QFrame:
        """
        The "identify speakers" toggle and speaker count.

        Sits below the model list because it applies to the run as a whole
        rather than to any one model. The count is a spin box rather than free
        text because telling the clustering step exactly how many people are
        present is the single biggest accuracy lever in diarization, and a
        typo'd value would quietly degrade every label.
        """
        row = QFrame()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        self.identify_speakers_check = QCheckBox(t("identify_speakers"))
        self.identify_speakers_check.setChecked(True)
        self.identify_speakers_check.setFont(Fonts.BODY)
        self.identify_speakers_check.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.identify_speakers_check)

        self.speaker_count_label = QLabel(t("speaker_count"))
        self.speaker_count_label.setFont(Fonts.BODY)
        self.speaker_count_label.setStyleSheet(theme.text_qss("text_secondary"))
        layout.addWidget(self.speaker_count_label)

        self.speaker_count_spin = QSpinBox()
        # Lower bound 2: diarizing a single speaker is a contradiction, and the
        # app is for conversations. Upper bound 10 keeps the clustering
        # meaningful - beyond that the count is realistically unknown.
        self.speaker_count_spin.setRange(2, 10)
        self.speaker_count_spin.setValue(2)
        self.speaker_count_spin.setFont(Fonts.BODY)
        # speaker_count_label is a plain QLabel, not a buddy - QSpinBox has
        # no visible label of its own baked into the control the way
        # identify_speakers_check's QCheckBox(text) does, so without this a
        # screen reader would announce it as an unlabelled number field.
        self.speaker_count_spin.setAccessibleName(t("speaker_count"))
        layout.addWidget(self.speaker_count_spin)

        layout.addStretch()

        self.identify_speakers_check.toggled.connect(self._on_identify_toggled)
        self._on_identify_toggled(True)
        return row

    def _on_identify_toggled(self, enabled: bool) -> None:
        """Speaker count is meaningless when identification is off."""
        self.speaker_count_label.setEnabled(enabled)
        self.speaker_count_spin.setEnabled(enabled)
        # Speaker identification adds a second pass over the audio, so every
        # card's time estimate changes with this toggle.
        self._refresh_desc_labels(recompute=True)

    @property
    def identify_speakers(self) -> bool:
        return self.identify_speakers_check.isChecked()

    @property
    def num_speakers(self) -> int:
        return self.speaker_count_spin.value()

    def show_error(self, key: str, params: dict) -> None:
        """
        Show an inline failure banner (used instead of a modal popup).
        Takes an i18n key + params (see TranscriptionThread.error) so the
        banner can be re-rendered if the language is toggled while shown.
        """
        self._error_key = key
        self._error_params = dict(params)
        self.error_label.setText(t("transcription_failed", message=t(key, **params)))
        self.error_banner.show()

    def clear_error(self) -> None:
        self._error_key = None
        self._error_params = {}
        self.error_banner.hide()

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
        """
        Move the accent border to whichever card's radio is currently picked.

        Tried and dropped: a drop shadow on the selected card, matching the
        result panel's. Screenshotted it (see the redesign notes) and it
        was invisible - QGraphicsDropShadowEffect paints outside the
        widget's own rect, and this card lives inside models_scroll's
        QScrollArea with no margin reserved for a shadow to bleed into, so
        the viewport clips it away entirely. All cost (still a candidate
        repaint-artifact source per QGraphicsDropShadowEffect-in-a-
        QScrollArea) and no visible benefit, so the accent border alone
        carries "this one is selected" here.
        """
        for card_name, card in self._cards.items():
            card.setStyleSheet(theme.card_qss(f"modelCard_{card_name}", selected=(card_name == name)))

    def _create_model_card(self, idx: int, name: str, info: dict, is_recommended: bool = False) -> QFrame:
        """Create and return a model selection card with radio button and details."""
        card = QFrame()
        object_name = f"modelCard_{name}"
        card.setObjectName(object_name)
        # Initially, the recommended model is also the selected one.
        card.setStyleSheet(theme.card_qss(object_name, selected=is_recommended))

        layout = QHBoxLayout(card)
        layout.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        layout.setSpacing(Spacing.MD)

        # Radio button. It carries no text of its own - the model name and
        # description are separate QLabels beside it (below) - so without
        # an explicit accessible name a screen reader would announce every
        # one of these seven radios identically as just "radio button".
        radio = QRadioButton()
        radio.setChecked(is_recommended)
        radio.toggled.connect(lambda checked: self._on_radio_toggled(name, checked))
        radio.setAccessibleName(model_text(name, "name"))
        radio.setAccessibleDescription(model_text(name, "description"))
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        # No per-widget setStyleSheet here anymore: app_stylesheet() now has
        # an app-wide QRadioButton color rule (plus the ::indicator rules a
        # per-widget QRadioButton {} sheet couldn't touch anyway), so this
        # would only have duplicated theme.py's COLORS['text_primary'].
        layout.addWidget(radio)

        # Model name and description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        # Explicit absolute alignment (see _card_text_alignment): without
        # it each QLabel aligns by its own text's content direction (Latin
        # model names one way, Hebrew descriptions the other), scattering
        # the card's text block in RTL mode.
        model_label = QLabel(model_text(name, "name"))
        model_label.setFont(Fonts.BODY_BOLD)
        model_label.setStyleSheet(theme.text_qss("text_primary"))
        model_label.setAlignment(self._card_text_alignment())
        text_layout.addWidget(model_label)
        self._name_labels[name] = model_label

        # Description + time estimate (kept up to date via update_audio_duration)
        desc_label = QLabel(self._desc_text(name))
        desc_label.setFont(Fonts.CAPTION)
        desc_label.setStyleSheet(theme.text_qss("text_secondary"))
        desc_label.setAlignment(self._card_text_alignment())
        text_layout.addWidget(desc_label)
        self._desc_labels[name] = desc_label

        layout.addLayout(text_layout)
        layout.addStretch()

        # Recommended badge - always created so update_audio_duration can
        # show/hide it as the real recommendation shifts, instead of only
        # ever reflecting the recommendation computed at construction time.
        badge = QLabel(t("recommended_badge"))
        badge.setStyleSheet(theme.badge_qss())
        badge.setVisible(is_recommended)
        layout.addWidget(badge)
        self._badges[name] = badge

        # +2px over the pre-redesign 56: BODY_BOLD grew a point (11 -> 12pt,
        # see Fonts) and moved to DemiBold, so the name label needs a
        # little more room than before. Kept small deliberately - this is
        # the one step where extra height is not free (each px here is a
        # px the seven-card scroll area doesn't get - see the class
        # docstring on why the cards need a QScrollArea at all).
        card.setFixedHeight(58)
        self._cards[name] = card
        return card

    def update_audio_duration(self, seconds: int) -> None:
        """
        Recompute time estimates and the real recommendation in place, once
        the actual audio duration (and possibly a freshly finished hardware
        calibration) is known.
        """
        self.audio_duration = seconds
        self._refresh_desc_labels(recompute=True)

        recommended_model, _ = self.hardware.recommend_model(seconds)
        self._apply_recommendation(recommended_model)

    def showEvent(self, event) -> None:
        """
        Bring the recommended card into view whenever this step is shown.

        With seven cards behind a scroll area the recommendation can start off
        below the fold, and a user who doesn't scroll would never see it.

        Also seeds Tab's starting point at the currently-selected model's
        radio (see FileSelectStep.showEvent for why this doesn't paint a
        ring on its own - the same reasoning applies here). Whichever radio
        is actually checked, not necessarily the recommended one - a user
        who already picked a different model on a previous visit to this
        step shouldn't have Tab silently reset them to the recommendation.
        """
        super().showEvent(event)
        self._scroll_to_recommended()
        radio = self.model_radios.get(self.selected_model)
        if radio is not None:
            radio.setFocus(Qt.OtherFocusReason)

    def _scroll_to_recommended(self) -> None:
        card = self._cards.get(self._current_recommended)
        if card is not None:
            self._scroll_area.ensureWidgetVisible(card)

    def _desc_text(self, name: str) -> str:
        """
        Compose one card's "description | Est: ..." line in the current
        language. The time estimate is cached: a language toggle only
        re-renders text, so it must not re-run (and re-log) the hardware
        estimator - only update_audio_duration recomputes.
        """
        time_str = self._time_strs.get(name)
        if time_str is None:
            time_est, _ = self.hardware.estimate_transcription_time(
                self.audio_duration, name, identify_speakers=self.identify_speakers
            )
            time_str = self.hardware.get_time_estimate_display(time_est)
            self._time_strs[name] = time_str
        return t("model_desc_est", desc=model_text(name, "description"), time=time_str)

    def _refresh_desc_labels(self, recompute: bool = False) -> None:
        if recompute:
            self._time_strs.clear()
        for name, label in self._desc_labels.items():
            label.setText(self._desc_text(name))

    @staticmethod
    def _card_text_alignment():
        """
        Visual (absolute) alignment that puts card text next to the radio
        button in the current language: right in Hebrew's mirrored layout,
        left in English. AlignLeading doesn't work here - QLabel resolves
        it against each label's own text direction, so Latin model names
        and Hebrew descriptions end up on different sides (verified
        empirically).
        """
        side = Qt.AlignRight if is_rtl() else Qt.AlignLeft
        return side | Qt.AlignAbsolute | Qt.AlignVCenter

    def retranslate(self) -> None:
        """Re-render all text in the current UI language (live toggle)."""
        self.title.setText(t("choose_model"))
        alignment = self._card_text_alignment()
        for name, label in self._name_labels.items():
            label.setText(model_text(name, "name"))
            label.setAlignment(alignment)
        for label in self._desc_labels.values():
            label.setAlignment(alignment)
        for badge in self._badges.values():
            badge.setText(t("recommended_badge"))
        for name, radio in self.model_radios.items():
            radio.setAccessibleName(model_text(name, "name"))
            radio.setAccessibleDescription(model_text(name, "description"))
        self.identify_speakers_check.setText(t("identify_speakers"))
        self.speaker_count_label.setText(t("speaker_count"))
        self.speaker_count_spin.setAccessibleName(t("speaker_count"))
        self._refresh_desc_labels()
        if self._error_key is not None:
            self.error_label.setText(
                t("transcription_failed", message=t(self._error_key, **self._error_params))
            )

    def _apply_recommendation(self, recommended_model: str) -> None:
        """
        Move the RECOMMENDED badge to recommended_model and, if the user
        hasn't manually picked a model yet, follow it with the selection.

        The accent border is a separate concept (see _apply_selection) -
        it always tracks whichever card's radio is actually checked, not
        the recommendation, so a manually-picked model stays highlighted
        even after the recommendation moves elsewhere.
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
