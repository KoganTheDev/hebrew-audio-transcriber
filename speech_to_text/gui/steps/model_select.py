"""Step 2: model selection, with a live, data-driven recommendation."""

import logging
import os

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
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
from speech_to_text.gui.focus import PROPERTY as KBD_FOCUS_PROPERTY
from speech_to_text.gui.i18n import is_rtl, model_text, t
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)

def _model_is_downloaded(repo: str) -> bool:
    """
    Best-effort guess at whether `repo` already sits in faster-whisper's
    local download cache, so a model card can skip warning about a
    download that has already happened.

    This pokes directly at an IMPLEMENTATION DETAIL of a downstream
    library - huggingface_hub's on-disk cache layout, a folder named
    "models--<owner>--<repo>" per snapshot - not a documented, stable
    contract. faster-whisper resolves a bare size like "tiny" to
    "Systran/faster-whisper-tiny" before that layout is ever applied
    (config.MODELS' "repo" field mirrors that: bare sizes for stock
    Whisper, an explicit "owner/repo" for the ivrit.ai models), so this
    has to redo that same resolution to compute the folder name it's
    looking for.

    Fail-safe in ONE direction only, deliberately: any doubt at all -
    the folder's missing, a "snapshots" subfolder is missing or empty,
    the path can't even be listed, a future huggingface_hub version
    reshuffles this layout entirely - reports "not downloaded", never
    the reverse. Getting this wrong one way just means an already-cached
    model shows a redundant download-size note on its card (mildly
    annoying). Getting it wrong the other way would tell someone a
    multi-GB download isn't coming when it actually is, which is a wrong
    claim about to cost them real time - see this function's caller for
    where that asymmetry matters.

    Reads config.MODEL_DOWNLOAD_ROOT - the same absolute, resolved-once path
    core/transcriber.py hands WhisperModel's download_root - so this presence
    check and the real download always agree on where to look. That used to
    be two independent copies of the relative literal "./whisper_models",
    which meant a model downloaded during one working-directory session
    could read as "not downloaded" from another (the process's current
    working directory decided where the literal resolved, both for the real
    download and for this check). See config.MODEL_DOWNLOAD_ROOT's own
    comment for the resolution order and why it had to move to config.py
    rather than staying duplicated here.
    """
    try:
        repo_id = repo if "/" in repo else f"Systran/faster-whisper-{repo}"
        cache_dir_name = "models--" + repo_id.replace("/", "--")
        snapshots_dir = os.path.join(config.MODEL_DOWNLOAD_ROOT, cache_dir_name, "snapshots")
        return os.path.isdir(snapshots_dir) and bool(os.listdir(snapshots_dir))
    except OSError:
        return False


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
        self._radio_cards = {}  # QRadioButton -> its own QFrame card, for
        # _sync_card_focus_ring below - see that method's docstring for why
        # the card (not the radio Qt actually focuses) needs its own
        # keyboard-focus ring.
        self._badges = {}       # model_name -> "RECOMMENDED" QLabel (always created, shown/hidden)
        # Computed once at construction, not re-checked per card render: a
        # download completing mid-session (this app's own transcription run
        # is the only thing that would trigger one) is already covered by a
        # full model-select rebuild never happening without a restart, so
        # there's no live event this would need to react to. See
        # _model_is_downloaded's docstring for what "downloaded" means here
        # and why it's guesswork, not a guarantee.
        self._downloaded = {
            name: _model_is_downloaded(info["repo"]) for name, info in config.MODELS.items()
        }
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

        # No page title here any more - "Choose Model" is now carried by
        # the wizard step indicator above the stacked widget (see
        # gui/stepper.py). Dropping it also buys back height on the one
        # step that has none to spare (seven model cards already need a
        # QScrollArea to fit at 650x600 - see the room analysis in
        # theme.Spacing's docstring).

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
        error_icon.setPixmap(svg_to_pixmap(ICONS["alert_triangle"], 16, COLORS['error'], dpr=self.devicePixelRatioF()))
        error_icon.setStyleSheet("background: transparent;")
        error_layout.addWidget(error_icon)

        self.error_label = QLabel()
        self.error_label.setFont(Fonts.CAPTION)
        self.error_label.setStyleSheet(theme.text_qss("error"))
        self.error_label.setWordWrap(True)
        error_layout.addWidget(self.error_label, 1)

        layout.addWidget(self.error_banner)

        # Calibration note - every time estimate on this step is a
        # placeholder (config.SPEED_FACTORS's guessed constants, see
        # HardwareDetector.estimate_transcription_time) until the background
        # benchmark that started in MainWindow.__init__ finishes. Hidden
        # whenever hardware.tiny_seconds_per_audio_second is already known
        # (the common case - calibration usually finishes well before the
        # user reaches this step), shown otherwise; see
        # _set_calibration_note, update_audio_duration and
        # mark_calibration_unmeasured for the three states this can be in.
        self._calibration_note_key = None
        self.calibration_note = QLabel()
        self.calibration_note.setFont(Fonts.CAPTION)
        self.calibration_note.setStyleSheet(theme.text_qss("text_tertiary"))
        self.calibration_note.setWordWrap(True)
        self.calibration_note.hide()
        layout.addWidget(self.calibration_note)
        if hardware.tiny_seconds_per_audio_second is None:
            self._set_calibration_note("calibration_pending")

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
        # setWidgetResizable(True) re-fits the scrolled widget from
        # QScrollArea's OWN resizeEvent, which fires when the scroll area
        # changes size - not when the viewport alone shrinks because the
        # vertical scrollbar just appeared. So a bar that shows up because
        # the CONTENT grew (the common case here: _on_calibration_done
        # rewrites every card's estimate once the background benchmark
        # lands, and a longer line can wrap a card to a second row) narrows
        # the viewport by the bar's 10px while leaving the container at its
        # old width. The cards are then 10px wider than what's visible and,
        # with horizontal scrolling off, their right border is simply
        # clipped away - the card reads as an unfinished box open on one
        # side. Watching the viewport's own resize closes that gap; see
        # _sync_container_width.
        models_scroll.viewport().installEventFilter(self)

        # Model selection
        self.model_group = QButtonGroup()
        self.model_radios = {}
        recommended_model, _ = hardware.recommend_model(self.audio_duration)
        self.selected_model = recommended_model
        self._current_recommended = recommended_model

        for i, model_name in enumerate(config.MODELS):
            model_card = self._create_model_card(
                i, model_name,
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
        self.speaker_count_spin.setObjectName("speakerCountSpin")
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
        # Stepper buttons removed: the row reads as clutter next to an
        # otherwise clean checkbox+label, and 2-10 is a range typed faster
        # than clicked up to. NoButtons only hides the ::up-button/
        # ::down-button subcontrols - QAbstractSpinBox still owns Up/Down,
        # PageUp/PageDown, direct typing and the scroll wheel regardless of
        # setButtonSymbols, so nothing about how the value can be changed is
        # lost. Chosen over zeroing ::up-button/::down-button in QSS because
        # this is a per-widget behavioural setting, not a shared theme rule:
        # it doesn't touch app_stylesheet()'s QSpinBox block (which stays
        # correct for any spin box added later that DOES want buttons), and
        # it sidesteps re-balancing the field's padding by hand where a
        # subcontrol used to reserve space - Qt simply stops reserving it.
        #
        # This is also why the RTL button-mirroring fix that used to live
        # here as _apply_spin_button_direction() was deleted rather than
        # kept dormant: with no buttons, there is nothing left to mirror.
        # The Qt finding it recorded is still worth having on file, in case
        # a future spin box on this row (or elsewhere) brings buttons back
        # and hits the same bug fresh:
        #
        #   app_stylesheet()'s QSpinBox::up-button/::down-button rules never
        #   set subcontrol-position, so Qt falls back to its built-in default
        #   of "top right"/"bottom right" - and that default is NEVER
        #   logically re-resolved against the widget's layoutDirection, so
        #   the buttons stay physically right even under RTL. The tempting
        #   fix - branch on is_rtl() and hand the widget an explicit "top
        #   left"/"bottom left" for RTL - does NOT work: Qt mirrors an
        #   EXPLICITLY-declared subcontrol-position a SECOND time for RTL
        #   widgets (the same visualPos()/visualRect() logic a style uses for
        #   RTL generally), so a literal "left" fed to RTL gets flipped back
        #   to physical right, cancelling the fix against itself. Mirroring
        #   only engages once a value is actually declared - the undeclared
        #   built-in default never goes through it at all, which is the
        #   actual root cause. The correct fix is therefore simpler than the
        #   tempting one: declare the plain LTR-correct position ("top
        #   right"/"bottom right") unconditionally, once, per widget (an
        #   object-name-scoped stylesheet, since app_stylesheet() is shared
        #   across every QSpinBox), and let Qt's own mirroring - which only
        #   fires on a declared value - do the flip for RTL. No is_rtl()
        #   branch needed, and no re-declaration on a language toggle either,
        #   since the declared value itself never changes.
        layout.addWidget(self.speaker_count_spin)
        self.speaker_count_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        # Centred because the field is wider than most of what it holds.
        # QSpinBox sizes itself for its widest possible value ("10"), so a
        # single-digit count - which is every value from 2 to 9, i.e. almost
        # all of them - sat against the leading edge of a box with visible
        # empty space beside it. That read as an unfinished control once the
        # stepper buttons stopped filling that space. Centring is
        # direction-neutral, so it needs no RTL counterpart.
        self.speaker_count_spin.setAlignment(Qt.AlignCenter)

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

    def _info_note(self, name: str) -> str:
        """
        RAM (always) plus, for a model not yet cached locally, the full
        "not downloaded yet" sentence - the words the caption's terse
        "↓ {size}" arrow (see _desc_text) doesn't have room to spell out.
        Shared by the card's tooltip and the radio's accessible description
        so the two surfaces never drift out of sync with each other.
        """
        info = config.MODELS[name]
        note = t("model_ram_tooltip", ram=info["ram_required"])
        if not self._downloaded[name]:
            note = note + " " + t("model_download_tooltip", size=info["download_size"])
        return note

    def _create_model_card(self, idx: int, name: str, is_recommended: bool = False) -> QFrame:
        """Create and return a model selection card with radio button and details."""
        card = QFrame()
        object_name = f"modelCard_{name}"
        card.setObjectName(object_name)
        # Initially, the recommended model is also the selected one.
        card.setStyleSheet(theme.card_qss(object_name, selected=is_recommended))
        # Mouse-hover equivalent of the radio's accessible description
        # above - a sighted mouse user gets the same RAM (and, where it
        # applies, download) information a screen reader announces, without
        # any of it costing the caption's width.
        card.setToolTip(self._info_note(name))

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
        # RAM (and, when relevant, the pending-download sentence) lives here
        # and in the card's tooltip below rather than inline in the caption
        # text - see _desc_text's comment on why: RAM applies to every card,
        # always, and the caption doesn't have room to spell either out in
        # full for all seven without overflowing.
        radio.setAccessibleDescription(model_text(name, "description") + ". " + self._info_note(name))
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        # The card frame, not the radio, has to show the keyboard-focus ring
        # (see _sync_card_focus_ring's docstring) - the radio is what Qt
        # actually gives focus to (it's the only focusable widget on the
        # card), so this step has to react on the radio's behalf.
        self._radio_cards[radio] = card
        radio.installEventFilter(self)
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
        self._name_labels[name] = model_label

        # Name row: name label + RECOMMENDED badge, side by side. The badge
        # used to sit on the OUTER row, at the card's trailing edge, sharing
        # its width with the caption below via layout.addStretch() - fine
        # while the caption was short, but adding the RAM/download text (see
        # _desc_text) pushed the caption's own natural width past what was
        # left after the badge, on the exact card most likely to carry both:
        # the RECOMMENDED one. Measured before landing on this fix: on the
        # Ivrit Turbo card (this app's default recommendation) in English,
        # and on Ivrit Large in Hebrew, the badge was shoved half off the
        # visible card - not merely a tight fit, an actual clipped control.
        # Moving the badge here instead gives the caption row the card's
        # full width on every card, badge or not - the name row has plenty
        # of slack a two-or-three-word model name never gets close to using.
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(Spacing.XS)
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

        text_layout.addLayout(name_row)

        # Description + time estimate (kept up to date via update_audio_duration)
        desc_label = QLabel(self._desc_text(name))
        desc_label.setFont(Fonts.CAPTION)
        desc_label.setStyleSheet(theme.text_qss("text_secondary"))
        desc_label.setAlignment(self._card_text_alignment())
        text_layout.addWidget(desc_label)
        self._desc_labels[name] = desc_label

        layout.addLayout(text_layout, 1)

        # +2px over the pre-redesign 56: BODY_BOLD grew a point (11 -> 12pt,
        # see Fonts) and moved to DemiBold, so the name label needs a
        # little more room than before. Kept small deliberately - this is
        # the one step where extra height is not free (each px here is a
        # px the seven-card scroll area doesn't get - see the class
        # docstring on why the cards need a QScrollArea at all).
        card.setFixedHeight(58)
        self._cards[name] = card
        return card

    def eventFilter(self, obj, event):
        """
        Watches every model radio's own FocusIn/FocusOut (installed in
        _create_model_card), so the surrounding card can react to a focus
        change that lands on its child rather than on itself - see
        _sync_card_focus_ring for why that indirection is needed at all.
        Never claims the event: Tab navigation and the radio's own focus
        handling must proceed exactly as if this filter didn't exist.
        """
        card = self._radio_cards.get(obj)
        if card is not None and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self._sync_card_focus_ring(card, focused_in=event.type() == QEvent.FocusIn)
        elif event.type() == QEvent.Resize:
            scroll = getattr(self, "_scroll_area", None)
            # getattr, not a plain attribute: the filter is installed while
            # the scroll area is still a local in __init__, so the first
            # viewport resize can arrive before _scroll_area is bound.
            if scroll is not None and obj is scroll.viewport():
                self._sync_container_width()
        return super().eventFilter(obj, event)

    def _sync_container_width(self) -> None:
        """
        Keep the scrolled card container exactly as wide as the viewport.

        Only the width: the height stays whatever the container's own layout
        asked for, so this never fights setWidgetResizable's vertical half.
        Narrowing can make a description wrap and the container grow taller,
        which QScrollArea picks up through the layout request it already
        listens for. The widths converge in one step, so the
        resize -> scrollbar -> resize path cannot cycle.
        """
        container = self._scroll_area.widget()
        viewport = self._scroll_area.viewport()
        if container is None:
            return
        # A ceiling, not just a resize. QScrollArea's own updateScrollBars()
        # sizes the scrolled widget to the scroll area first and only then
        # decides a bar is needed, and it does not go back and re-size the
        # widget once that decision narrows the viewport - so a plain
        # resize() here is undone again on the very next layout pass, and
        # resizing back in a loop just trades the clipping for a fight with
        # Qt. A maximum width is a constraint Qt honours inside its own
        # pass, so the widget can never come back wider than what is
        # actually visible.
        container.setMaximumWidth(viewport.width())
        if container.width() > viewport.width():
            container.resize(viewport.width(), container.height())

    @staticmethod
    def _sync_card_focus_ring(card: QFrame, focused_in: bool) -> None:
        """
        Stamp the model card's own [kbdFocus] property (see theme.card_qss)
        from its RADIO's focus state, not the card's own - the radio is the
        card's only focusable child, so Qt gives real focus to it, and
        gui/focus.py's KeyboardFocusTracker only ever stamps the widget that
        actually receives focus. Left alone, tabbing onto a card would ring
        the small 18px indicator and leave the card itself - the thing a
        sighted keyboard user is actually scanning for "where am I" - looking
        identical to every other unselected card.

        This does NOT reuse the radio's own kbdFocus property value, even
        though the radio has one and it says the same thing eventually: by
        the time this runs (from FocusIn, delivered synchronously before
        KeyboardFocusTracker's focusChanged-driven update), the radio's own
        property may not be written yet - see
        KeyboardFocusTracker.is_keyboard_active's docstring for the exact
        ordering reason. Re-deriving "is a keyboard driving this" from the
        tracker's own live flag sidesteps that race instead of depending on
        a signal-connection order that happens to work today.

        Three-way distinction this has to preserve (see theme.card_qss):
        selected cards keep the accent border, plain unselected cards keep
        control_border, and this only ever overrides that with the focus
        colour - never with accent - so a focused-but-unselected card reads
        as "focused", not as "selected". A selected card that also gets
        keyboard focus shows the focus colour too (overriding accent for as
        long as focus stays there); that is an acceptable fourth state, not
        one this method needs to keep apart from the other three, since
        nothing above asks a selected+focused card to look distinct from a
        focused one - only "not to look selected" is a live requirement.
        """
        show_ring = False
        if focused_in:
            tracker = getattr(QApplication.instance(), "_kbd_focus_tracker", None)
            show_ring = bool(tracker is not None and tracker.is_keyboard_active())
        card.setProperty(KBD_FOCUS_PROPERTY, show_ring)
        card.style().unpolish(card)
        card.style().polish(card)
        card.update()

    def _set_calibration_note(self, key) -> None:
        """Show `key`'s text as the calibration note, or hide it when key is None."""
        self._calibration_note_key = key
        if key is None:
            self.calibration_note.hide()
        else:
            self.calibration_note.setText(t(key))
            self.calibration_note.show()

    def mark_calibration_unmeasured(self) -> None:
        """
        Called from MainWindow._on_calibration_failed: the background
        benchmark didn't just take a while, it actively failed, so
        hardware.tiny_seconds_per_audio_second will stay None for the rest
        of this run. Leaving the "still measuring" note up would keep
        promising a real number that is never coming; this swaps it for a
        resting message that states the permanent condition instead - the
        estimates are rough, not provisional.
        """
        self._set_calibration_note("calibration_unmeasured")

    def update_audio_duration(self, seconds: int) -> None:
        """
        Recompute time estimates and the real recommendation in place, once
        the actual audio duration (and possibly a freshly finished hardware
        calibration) is known.
        """
        self.audio_duration = seconds
        self._refresh_desc_labels(recompute=True)
        # Only clear the note here if calibration is now actually known -
        # this is also called on every step-1-to-2 advance regardless of
        # calibration state (see MainWindow._go_next), so blindly hiding it
        # would erase a still-accurate "these are provisional" note the
        # moment the user picks a file, well before the benchmark is done.
        if self.hardware.tiny_seconds_per_audio_second is not None:
            self._set_calibration_note(None)

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
        text = t("model_desc_est", desc=model_text(name, "description"), time=time_str)
        if not self._downloaded[name]:
            # Direct dict access, not .get() - a model added to config.MODELS
            # without a download_size should raise here at card-build time,
            # not render a blank/"None" note that's easy to miss in review.
            size = config.MODELS[name]["download_size"]
            # RAM (relevant to every card, always) lives in the card's
            # tooltip/accessible description instead of this line (see
            # _create_model_card) - putting both there and here was measured
            # to overflow the caption's ~520px budget on the recommended
            # card in Hebrew. Download size stays inline because it's the
            # one fact that changes a decision RIGHT NOW, for the one or two
            # models that actually need it - most cards carry no extra text
            # at all once they're cached locally.
            text = text + " " + t("model_download_pending", size=size)
        return text

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
            radio.setAccessibleDescription(model_text(name, "description") + ". " + self._info_note(name))
        for name, card in self._cards.items():
            card.setToolTip(self._info_note(name))
        self.identify_speakers_check.setText(t("identify_speakers"))
        self.speaker_count_label.setText(t("speaker_count"))
        self.speaker_count_spin.setAccessibleName(t("speaker_count"))
        self._refresh_desc_labels()
        if self._calibration_note_key is not None:
            self.calibration_note.setText(t(self._calibration_note_key))
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
