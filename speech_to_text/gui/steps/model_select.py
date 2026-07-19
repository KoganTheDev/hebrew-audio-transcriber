"""Step 2: model selection, with a live, data-driven recommendation."""

import logging

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.gui import theme
from speech_to_text.gui.i18n import t, model_text, is_rtl
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.icons import ICONS, svg_to_pixmap

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
        layout.setSpacing(Spacing.SM)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)

        # Title
        self.title = QLabel(t("choose_model"))
        self.title.setFont(Fonts.TITLE)
        self.title.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.title)

        # Error banner — shown inline (instead of a modal popup) if a
        # transcription attempt fails and the user is sent back here to
        # retry. Hidden until show_error() is called.
        self.error_banner = QFrame()
        self.error_banner.setObjectName("modelErrorBanner")
        self.error_banner.setStyleSheet(theme.error_banner_qss("modelErrorBanner"))
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

        # All model cards are laid out directly (no scroll area) — sized to
        # fit every option in the fixed window without needing to scroll.
        models_layout = QVBoxLayout()
        models_layout.setSpacing(Spacing.XS + 2)
        models_layout.setContentsMargins(0, 0, 0, 0)

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

        layout.addLayout(models_layout)
        layout.addStretch()

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
                # A real click (not our own programmatic re-sync) — stop
                # auto-following the recommendation as it updates.
                self._user_touched_model = True

    def _apply_selection(self, name: str) -> None:
        """Move the accent border to whichever card's radio is currently picked."""
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

        # Radio button
        radio = QRadioButton()
        radio.setChecked(is_recommended)
        radio.toggled.connect(lambda checked: self._on_radio_toggled(name, checked))
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        radio.setStyleSheet(f"QRadioButton {{ color: {COLORS['text_primary']}; }}")
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

        # Recommended badge — always created so update_audio_duration can
        # show/hide it as the real recommendation shifts, instead of only
        # ever reflecting the recommendation computed at construction time.
        badge = QLabel(t("recommended_badge"))
        badge.setStyleSheet(theme.badge_qss())
        badge.setVisible(is_recommended)
        layout.addWidget(badge)
        self._badges[name] = badge

        card.setFixedHeight(56)
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

    def _desc_text(self, name: str) -> str:
        """
        Compose one card's "description | Est: ..." line in the current
        language. The time estimate is cached: a language toggle only
        re-renders text, so it must not re-run (and re-log) the hardware
        estimator - only update_audio_duration recomputes.
        """
        time_str = self._time_strs.get(name)
        if time_str is None:
            time_est, _ = self.hardware.estimate_transcription_time(self.audio_duration, name)
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
        self._refresh_desc_labels()
        if self._error_key is not None:
            self.error_label.setText(
                t("transcription_failed", message=t(self._error_key, **self._error_params))
            )

    def _apply_recommendation(self, recommended_model: str) -> None:
        """
        Move the RECOMMENDED badge to recommended_model and, if the user
        hasn't manually picked a model yet, follow it with the selection.

        The accent border is a separate concept (see _apply_selection) —
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
