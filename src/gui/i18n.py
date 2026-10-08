"""UI internationalization: English/Hebrew string table and language state.

Hand-rolled rather than Qt Linguist (.ts/.qm) on purpose: the two hard
problems here are strings that originate in the transcription worker
process (core must never import PyQt5, so it emits message
KEYS that the GUI renders at display time) and data-driven text for the
model cards - a plain dict handles both uniformly.

Nothing in core may import this module.
"""

import logging
from typing import TYPE_CHECKING, cast

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

if TYPE_CHECKING:
    # Type-only: neither name is needed at import time, and the layout
    # direction helper deliberately imports Qt lazily inside its body.
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

# QSettings identity is passed explicitly so persistence works no matter
# whether QCoreApplication org/app names have been set yet.
_SETTINGS_ORG = "HebrewAudioTranscriber"
_SETTINGS_APP = "Hebrew Audio Transcriber"
_SETTINGS_KEY = "ui/language"

SUPPORTED_LANGUAGES = ("en", "he")

# ‏ (RLM) anchors lines that start with Latin text (filenames, paths)
# so they still lay out right-to-left as a whole in the Hebrew UI.
_RLM = "‏"

# LRI/PDI (U+2066/U+2069) fence a Latin quantity - "145 MB", "1 GB" - that
# sits inside a Hebrew sentence.
#
# Without them the pair comes out backwards, reading "MB 145". The Unicode
# bidi algorithm has European numbers influence neighbouring neutrals as if
# they were right-to-left (rule N1), so the ordinary space between "145" and
# "MB" is flanked by an R-acting number on one side and a real L letter on
# the other, matches neither, and falls back to the paragraph direction -
# RTL. That single RTL space splits what should be one left-to-right run in
# two and swaps them. A non-breaking space does not help: it is the same
# bidi class as a normal one. An isolate is what fixes it, and it has to be
# an isolate rather than the older LRE/PDF embedding, which leaks: an
# embedding pulls whatever Latin text happens to sit next to it into the
# same run, so a neighbouring "|" or unit word drifts to the wrong side.
# Both were rendered side by side before choosing.
_LRI = "⁦"
_PDI = "⁩"
# FSI (U+2068) for a value whose script is not known in advance - a user's
# term can be Hebrew or Latin - so the isolate takes the direction of the
# value's own first strong letter instead of assuming LTR as LRI does.
_FSI = "⁨"

STRINGS = {
    # --- Main window ---
    "app_title": {"en": "Hebrew Audio Transcriber", "he": "מתמלל אודיו בעברית"},
    # The nav buttons are IconTextButtons (gui/widgets.py): plain words
    # here, the icons and their visual side are handled by the widget.
    "nav_back": {"en": "Back", "he": "חזרה"},
    "nav_cancel": {"en": "Cancel", "he": "ביטול"},
    # Shown beside Cancel once it's armed (first press) during step 3 - see
    # MainWindow._on_cancel_clicked. The button's own label deliberately
    # stays "Cancel" (every longer phrase measured too wide for the fixed
    # 130x36 nav button in one or both languages - see button_danger_qss),
    # so the actual explanation lives here instead, where there's real room
    # for a sentence.
    "cancel_confirm_hint": {
        "en": "Click Cancel again to stop",
        "he": "לחצו שוב על ביטול כדי לעצור",
    },
    "nav_next": {"en": "Next", "he": "הבא"},
    "nav_new_file": {"en": "New File", "he": "קובץ חדש"},
    "no_model_title": {"en": "No Model", "he": "לא נבחר מודל"},
    "no_model_body": {"en": "Please select a model", "he": "אנא בחרו מודל"},
    # Header language toggle - accessible name/tooltip. The button's own
    # visible text already shows the TARGET language ("EN"/"עב" - see
    # MainWindow._retranslate_chrome), which reads fine visually next to
    # the app's current language, but says nothing about what the control
    # DOES to a screen reader with no visual context, so this names the
    # action instead. Static across both languages' target rather than
    # re-derived per toggle - "switches the interface language" is true
    # regardless of which direction it's about to switch.
    "toggle_language_name": {"en": "Toggle interface language", "he": "החלפת שפת הממשק"},
    "toggle_language_tooltip": {
        "en": "Switch interface language (Ctrl+Shift+L)",
        "he": "החלפת שפת הממשק (Ctrl+Shift+L)",
    },
    # Wizard step indicator (gui/stepper.py) - per-segment accessible-name
    # suffixes. The badge/label color already carries this distinction for
    # sighted users (peach fill, a check glyph, dimmed text - see
    # StepIndicator's _paint_* methods), but a screen reader has no way to
    # read a border color or an icon shape, so each segment's state is
    # spelled out in words here too.
    "step_status_current": {"en": "Current step", "he": "השלב הנוכחי"},
    "step_status_done": {"en": "Completed", "he": "הושלם"},
    "step_status_pending": {"en": "Not started", "he": "טרם התחיל"},
    # --- Step 1: file selection ---
    "specs_title": {"en": "Specs", "he": "מפרט מערכת"},
    "select_audio_file": {"en": "Select Audio File", "he": "בחירת קובץ אודיו"},
    "drop_main": {
        "en": "Drag your audio or video file here",
        "he": "גררו לכאן קובץ אודיו או וידאו",
    },
    "drop_formats": {
        "en": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV",
        "he": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV",
    },
    "drop_alt": {"en": "or click anywhere here to browse", "he": "או לחצו כאן כדי לבחור קובץ"},
    "no_file_selected": {"en": "No file selected", "he": "לא נבחר קובץ"},
    # Drop zone accessibility. Read together by a screen reader (name then
    # description) when the zone receives focus, so the description spells
    # out both input paths (keyboard AND drag/drop) even though only the
    # keyboard one is reachable without a mouse - a sighted keyboard user
    # scanning past this control by ear should still learn drag-and-drop
    # exists.
    "drop_zone_name": {"en": "Audio file drop zone", "he": "אזור גרירת קובץ אודיו"},
    "drop_zone_desc": {
        "en": "Press Enter or Space to browse for a file, or drag and drop a file or folder here.",
        "he": "לחצו Enter או Space כדי לבחור קובץ, או גררו לכאן קובץ או תיקייה.",
    },
    # Per-file remove button in the selected-files list (file_select.py) -
    # a bare 20px "x" with no visible label of its own. {filename}
    # disambiguates which row's button this is once more than one file is
    # queued; a generic "Remove" would be indistinguishable across rows to
    # a screen reader jumping between controls rather than reading linearly.
    # Shown on a file whose container PyAV could not open. Deliberately
    # hedged - a probe failure is not proof faster-whisper will fail too.
    "file_unreadable_tip": {
        "en": "This file could not be read, so its length is a guess. It may fail to transcribe.",
        "he": "לא ניתן לקרוא את הקובץ, ולכן אורכו הוא הערכה בלבד. ייתכן שהתמלול שלו ייכשל.",
    },
    "remove_file": {"en": "Remove {filename}", "he": "הסרת {filename}"},
    "file_info": {
        "en": "{filename} | {minutes}m {seconds}s | {size} MB",
        "he": _RLM
        + _LRI
        + "{filename}"
        + _PDI
        + " | {minutes} דק' {seconds} שנ' | "
        + _LRI
        + "{size} MB"
        + _PDI,
    },
    # Shown in a file's row while its length is still being read off disk.
    # Deliberately the same shape as file_info minus the two facts it does not
    # have yet, and isolated the same way, so the row does not reflow when the
    # real values arrive.
    "file_info_probing": {
        "en": "{filename} | reading length...",
        "he": _RLM + _LRI + "{filename}" + _PDI + " | קורא אורך...",
    },
    # Summary line above the file list. Unlike file_info, this doesn't open
    # with a filename - it opens with the count - so it needs no RLM anchor
    # (the Hebrew string already starts with a strong-RTL character).
    "files_summary": {
        "en": "{count} files selected | Total: {minutes}m {seconds}s",
        "he": "נבחרו {count} קבצים | סה\"כ: {minutes} דק' {seconds} שנ'",
    },
    # Singular counterparts. Worth the extra keys rather than a bare "{count}
    # files": a single dropped file is an ordinary case, not an edge one, and
    # "1 files selected" is the kind of detail that makes an interface feel
    # unfinished. Hebrew is not simply the same string with a different
    # number either - the verb and the noun both change (נבחרו/נבחר,
    # קבצים/קובץ), so a count-agnostic template could not have been right in
    # both languages anyway.
    "files_summary_one": {
        "en": "1 file selected | Total: {minutes}m {seconds}s",
        "he": "נבחר קובץ אחד | סה\"כ: {minutes} דק' {seconds} שנ'",
    },
    # Appended to the line above (or to no_file_selected) when a direct file
    # drop skipped something outside config.SUPPORTED_FORMATS - see
    # FileSelectStep._drop. Count only, no filenames: this line has little
    # width to spare (see file_select.py's layout comments).
    "files_skipped": {"en": "({count} skipped)", "he": "({count} דולגו)"},
    "files_skipped_one": {"en": "(1 skipped)", "he": "(קובץ אחד דולג)"},
    # Short "N files" label - used as the filename slot of file_model_info
    # (step 3's header) when a batch, rather than a single file, is running.
    "files_count_label": {"en": "{count} files", "he": "{count} קבצים"},
    "file_dialog_title": {"en": "Select File", "he": "בחירת קובץ"},
    "file_dialog_filter": {"en": "Audio/Video Files", "he": "קובצי אודיו/וידאו"},
    "hw_cpu_cores": {"en": "CPU CORES", "he": "ליבות מעבד"},
    "hw_ram": {"en": "RAM", "he": "זיכרון RAM"},
    "hw_gpu": {"en": "GPU", "he": "כרטיס מסך"},
    "hw_no_gpu": {"en": "No GPU", "he": "ללא GPU"},
    # --- Step 2: model selection ---
    "choose_model": {"en": "Choose Model", "he": "בחירת מודל"},
    "recommended_badge": {"en": "RECOMMENDED", "he": "מומלץ"},
    # The four facts under each model card's purpose line.
    "model_fact_time": {"en": "Est. time", "he": "זמן משוער"},
    "model_fact_accuracy": {"en": "Accuracy", "he": "דיוק"},
    "model_fact_memory": {"en": "Memory", "he": "זיכרון"},
    "model_fact_first_use": {"en": "First use", "he": "שימוש ראשון"},
    "model_ready": {"en": "Ready", "he": "מוכן"},
    # The "First use" fact for a model not in the local download cache yet
    # (see model_select.py's _model_is_downloaded). model_download_tooltip
    # below spells the same fact out in words.
    "model_download_fact": {"en": "↓ {size}", "he": "↓ " + _LRI + "{size}" + _PDI},
    # Under the cards: what the estimates above assume. Speaker
    # identification is a second pass over the audio, so it changes them.
    "estimate_footnote_speakers": {
        "en": "Times are estimated for {duration} of audio, with speaker labels.",
        "he": "הזמנים משוערים ל-{duration} של אודיו, כולל סימון דוברים.",
    },
    "estimate_footnote": {
        "en": "Times are estimated for {duration} of audio.",
        "he": "הזמנים משוערים ל-{duration} של אודיו.",
    },
    # --- Step 2: the speakers panel ---
    "speakers_title": {"en": "Speakers", "he": "דוברים"},
    "speakers_sub": {
        "en": "Marks who is talking in each part of the transcript.",
        "he": "מסמן מי מדבר בכל קטע בתמלול.",
    },
    # A count of one is how the run skips speaker identification.
    "speakers_sub_one": {
        "en": "One person, so no speaker labels.",
        "he": "אדם אחד, ולכן בלי סימון דוברים.",
    },
    "speaker_count": {"en": "People", "he": "אנשים"},
    "speakers_fewer": {"en": "Fewer people", "he": "פחות אנשים"},
    "speakers_more": {"en": "More people", "he": "יותר אנשים"},
    # --- Step 2: the custom terms panel, and the dialog it opens (gui/terms_dialog.py) ---
    "terms_sub": {
        "en": "Names and jargon the app fixes when the model is unsure.",
        "he": "שמות ומונחים שהאפליקציה מתקנת כשהמודל לא בטוח.",
    },
    "terms_edit": {"en": "Edit", "he": "עריכה"},
    # Hebrew opens with a Hebrew word: a leading "+4" is all weak characters
    # and lands on whichever side the bidi pass resolves it to.
    "terms_more": {"en": "+{n} more", "he": "ועוד {n}"},
    "terms_none": {"en": "No terms yet.", "he": "אין עדיין מונחים."},
    "terms_button_tooltip": {
        "en": "Names, places and jargon the app corrects in transcripts. Saved in {path}",
        "he": "שמות, מקומות ומונחים שהאפליקציה מתקנת בתמלול. נשמר ב-" + _LRI + "{path}" + _PDI,
    },
    "terms_title": {"en": "Custom terms", "he": "מונחים מותאמים"},
    "terms_hint": {
        "en": "Names, places and jargon only.",
        "he": "שמות, מקומות ומונחים מקצועיים בלבד.",
    },
    "terms_placeholder": {"en": "Type a term and press Enter", "he": "הקלידו מונח ולחצו Enter"},
    "terms_add": {"en": "Add", "he": "הוספה"},
    "terms_done": {"en": "Done", "he": "סיום"},
    "terms_count": {"en": "{n} terms", "he": "{n} מונחים"},
    "terms_count_one": {"en": "1 term", "he": "מונח אחד"},
    "terms_empty": {
        "en": "No terms yet.\nAdd a name the model got wrong in your last transcript.",
        "he": "אין עדיין מונחים.\nהוסיפו שם שהמודל טעה בו בתמלול האחרון.",
    },
    # Opens with a word in the UI's own language so the line takes that
    # direction; the term is isolated so a Hebrew term inside English (or the
    # reverse) cannot reorder the words around it.
    "terms_duplicate": {
        "en": "Already in the list: " + _FSI + "{term}" + _PDI,
        "he": "כבר ברשימה: " + _FSI + "{term}" + _PDI,
    },
    "terms_comment": {
        "en": "A term can't start with #, which marks a comment in the file.",
        "he": "מונח לא יכול להתחיל ב-#, שמסמן הערה בקובץ.",
    },
    "terms_save_failed": {
        "en": "Couldn't save the list: {error}",
        "he": "לא ניתן לשמור את הרשימה: {error}",
    },
    "terms_remove": {
        "en": "Remove " + _FSI + "{term}" + _PDI,
        "he": "הסרת " + _FSI + "{term}" + _PDI,
    },
    "transcription_failed": {
        "en": "Transcription failed: {message}",
        "he": "התמלול נכשל: {message}",
    },
    # Duration units, for format_duration() below. The abbreviations match
    # file_info/files_summary above on purpose: a Hebrew user reading a
    # file's length on step 1 and the model card's estimate on step 2 sees
    # one notation for the unit, not "1 דק' 35 שנ'" against "משוער: 1m 46s".
    "dur_s": {"en": "{seconds}s", "he": "{seconds} שנ'"},
    "dur_m": {"en": "{minutes}m", "he": "{minutes} דק'"},
    "dur_ms": {"en": "{minutes}m {seconds}s", "he": "{minutes} דק' {seconds} שנ'"},
    "dur_h": {"en": "{hours}h", "he": "{hours} שע'"},
    "dur_hm": {"en": "{hours}h {minutes}m", "he": "{hours} שע' {minutes} דק'"},
    # RAM required and, below, the download note: the card's tooltip and its
    # radio's accessible description, the spoken form of the card's facts.
    "model_ram_tooltip": {
        "en": "Requires {ram} RAM",
        "he": "דורש " + _LRI + "{ram}" + _PDI + " זיכרון RAM",
    },
    "model_download_tooltip": {
        "en": "Not downloaded yet - {size} on first use",
        "he": "טרם הורד - " + _LRI + "{size}" + _PDI + " בשימוש הראשון",
    },
    # Calibration note (ModelSelectStep.calibration_note) - see
    # HardwareDetector.tiny_seconds_per_audio_second and CalibrationThread.
    # "_pending" is the transient state while the background benchmark is
    # still running; "_unmeasured" is the permanent resting state once it's
    # known to have failed outright (see MainWindow._on_calibration_failed).
    "calibration_pending": {
        "en": "Measuring this machine's speed - estimates below are provisional",
        "he": "מודד את מהירות המחשב - האומדנים למטה זמניים",
    },
    "calibration_unmeasured": {
        "en": "Couldn't measure this machine's speed - estimates below are rough guesses",
        "he": "לא ניתן היה למדוד את מהירות המחשב - האומדנים למטה משוערים בגסות",
    },
    # --- Step 3: transcription ---
    "transcribing_title": {"en": "Transcribing", "he": "מתמלל"},
    "file_model_info": {
        "en": "{filename} | Model: {model}",
        "he": _RLM + "{filename} | מודל: {model}",
    },
    "elapsed": {"en": "Elapsed: {elapsed}", "he": "זמן שחלף: {elapsed}"},
    "elapsed_remaining": {
        "en": "Elapsed: {elapsed}  |  Est. remaining: {remaining}",
        "he": "זמן שחלף: {elapsed}  |  נותר (משוער): {remaining}",
    },
    "calculating": {"en": "calculating...", "he": "בחישוב..."},
    "transcription_complete": {"en": "Transcription Complete!", "he": "התמלול הושלם!"},
    # Caption shown above the (now single-line, middle-elided) path label -
    # see TranscriptionStep._render_result_path for why the path is not part
    # of this same string. "saved_to" below is the full, untruncated
    # "Saved to:\n<path>" text for the tooltip and accessible description,
    # where there is no width to elide against and the whole point is to
    # hand back what the on-screen ellipsis hid.
    "saved_to_caption": {"en": "Saved to:", "he": "נשמר אל:"},
    "saved_to": {"en": "Saved to:\n{path}", "he": "נשמר אל:\n" + _RLM + "{path}"},
    "open_transcript": {"en": "Open transcript", "he": "פתיחת התמלול"},
    # Secondary action beside "Open transcript" - reveals the containing
    # folder instead of the transcript itself (see
    # TranscriptionStep._open_folder).
    "show_in_folder": {"en": "Show in folder", "he": "הצגה בתיקייה"},
    # Batch progress strip (only shown for n > 1 - see
    # TranscriptionStep.set_batch_files). Pure digits and a slash, so -
    # unlike file_model_info/saved_to above - it needs no RLM anchor even
    # though it sits in the Hebrew UI: there's no Latin filename inside it
    # to anchor.
    "batch_progress_readout": {"en": "{i} / {n}", "he": "{i} / {n}"},
    # Speaker name template written into the transcript file itself, not shown
    # in the GUI. Rendered here and passed to the worker as data: core/ has no
    # access to this module (see core/worker.py) and cannot translate anything.
    # {n} is 1-based - "Speaker 0" reads like a bug to a non-programmer.
    "speaker_label": {"en": "Speaker {n}", "he": "דובר {n}"},
    # Notice rendered into the HTML output itself for a batch file whose
    # transcription failed - same "GUI renders, worker just embeds data"
    # pattern as speaker_label. Deliberately has no {message} placeholder:
    # unlike the transcription_failed banner below (a live error with a
    # specific cause), this is a static notice with nothing more specific
    # to say - the worker already logs the real exception.
    "file_failed_notice": {
        "en": "Transcription failed for this file.",
        "he": "התמלול עבור קובץ זה נכשל.",
    },
    # --- Transcript document chrome -----------------------------------------
    # The generated HTML is a small application with visible text of its own,
    # and it is rendered in the worker process, which cannot translate. These
    # are collected by TranscriptionThread and passed down as data, exactly
    # like speaker_label and file_failed_notice. Keys must match the ones
    # core/formatting and the page script (core/assets/js/) look up.
    "doc_toolbar": {"en": "Transcript tools", "he": "כלי תמלול"},
    "doc_search": {"en": "Search transcript", "he": "חיפוש בתמלול"},
    # The #search input's visible placeholder - shorter than doc_search on
    # purpose. #search is the toolbar's deliberate "release valve" (see
    # #search's own comment in core/assets/css/16-toolbar.css): it is allowed
    # to shrink below its placeholder's natural width so the row holds one
    # line down to the stacking breakpoint, and a shorter placeholder means
    # that shrinking has to go a lot further before anything clips at all.
    # doc_search itself stays the full phrase for the input's aria-label and
    # the toolbar's own accessible name (chrome.py:239's markup sets both
    # from the same translated string on purpose, but they don't have to be
    # the same string) - a screen reader has no width constraint to economise
    # against, so there is nothing to gain by shortening what it announces.
    "doc_search_placeholder": {"en": "Search", "he": "חיפוש"},
    "doc_search_prev": {"en": "Previous match", "he": "התאמה קודמת"},
    "doc_search_next": {"en": "Next match", "he": "התאמה הבאה"},
    "doc_no_results": {"en": "No results", "he": "אין תוצאות"},
    "doc_show_uncertain": {"en": "Show uncertain words", "he": "הצג מילים לא ודאיות"},
    # Two keys, not one - the button names the action it is about to take, and
    # that action is the opposite of the current state. The page script swaps
    # between them on click, alongside the aria-pressed/data-theme handling.
    "doc_theme_light": {"en": "Light mode", "he": "מצב בהיר"},
    "doc_theme_dark": {"en": "Dark mode", "he": "מצב כהה"},
    "doc_toggle_theme": {"en": "Switch colour scheme", "he": "החלפת ערכת צבעים"},
    "doc_save_copy": {"en": "Save a copy", "he": "שמירת עותק"},
    # Shown instead of doc_save_copy once the page script finds this browser
    # can write files directly (File System Access API) - see
    # syncSaveLabel() in core/assets/js/72-chrome.js. Two keys, not a
    # capability-aware label built at render time: core/formatting cannot
    # know the reader's browser, only the page script running in it can.
    "doc_save": {"en": "Save", "he": "שמירה"},
    "doc_status_saved": {"en": "Saved", "he": "נשמר"},
    "doc_status_saving": {"en": "Saving...", "he": "שומר..."},
    # The state the reader is usually in, and the one worth being precise
    # about: the edit is safe in this browser, but the .html on disk does not
    # contain it. A plain "Saved" there would imply the file had been updated,
    # which is exactly what a page opened from file:// cannot do.
    "doc_status_local": {"en": "Saved in browser", "he": "נשמר בדפדפן"},
    "doc_status_error": {"en": "Could not save", "he": "השמירה נכשלה"},
    "doc_files": {"en": "Files", "he": "קבצים"},
    "doc_speakers": {"en": "Speakers", "he": "דוברים"},
    "doc_apply_names_all": {
        "en": "Use these names in all files",
        "he": "השתמש בשמות האלה בכל הקבצים",
    },
    "doc_copy_line": {"en": "Copy this sentence", "he": "העתקת המשפט"},
    "doc_turn_text": {"en": "Turn text", "he": "טקסט הפסקה"},
    "doc_play_from": {"en": "Play from {t}", "he": "נגן מ־{t}"},
    # The speaker menu's scope group: a bubble's own reassignment control
    # moves either a single sentence or the whole block of sentences around
    # it (see buildSpeakerMenu() in js/24-speakers-menus.js).
    "doc_reassign_scope": {"en": "Apply to", "he": "החל על"},
    "doc_reassign_scope_line": {"en": "This sentence", "he": "המשפט הזה"},
    "doc_reassign_scope_block": {"en": "This whole block", "he": "כל הקטע הזה"},
    # Two keys, not one - same "the button names the action it is about to
    # take" reasoning as doc_theme_light/doc_theme_dark above. The page script
    # swaps between them on the audio element's own play/pause events (see
    # bindAudio()), alongside the #i-play/#i-pause glyph swap, so a
    # programmatic pause (the range-bound stop in the timeupdate handler)
    # updates the accessible name too, not just a click on the button.
    "doc_play_pause": {"en": "Play", "he": "נגן"},
    "doc_pause": {"en": "Pause", "he": "השהה"},
    "doc_seek": {"en": "Seek", "he": "החלקה בהקלטה"},
    "doc_plain_text": {"en": "Plain text", "he": "טקסט רגיל"},
    "doc_plain_hint": {
        "en": "to paste into another app",
        "he": "להעתקה לאפליקציה אחרת",
    },
    "doc_opt_timestamps": {"en": "Timestamps", "he": "חותמות זמן"},
    "doc_opt_speakers": {"en": "Speaker names", "he": "שמות דוברים"},
    "doc_copy_all": {"en": "Copy all", "he": "העתקת הכול"},
    "doc_confidence": {"en": "confidence", "he": "ביטחון"},
    # Shown as a toast when localStorage refuses a write, which in practice
    # means the quota is full. Chrome pools every file:// document into one
    # origin, so this page shares a few megabytes with every transcript ever
    # opened on the machine. Names the way out rather than just reporting
    # the failure, because the edits are still in memory at this point and
    # exporting a copy saves them.
    "doc_save_failed": {
        "en": 'Could not save in the browser - use "Save a copy" to keep your edits.',
        "he": 'לא ניתן לשמור בדפדפן - השתמשו ב"שמירת עותק" כדי לשמור את השינויים.',
    },
    "doc_copied": {"en": "Copied", "he": "הועתק"},
    "doc_add_speaker": {"en": "Add speaker", "he": "הוספת דובר"},
    # The chip a sentence card shows when speaker_attribution.py found no
    # diarization span to attribute it to (see _render_bubble_html() in
    # core/formatting/document.py) - a real, clickable label rather than a
    # blank chip, since a blank one hides the only way to fix such a card by
    # hand.
    "doc_unattributed_speaker": {"en": "Unknown speaker", "he": "דובר לא ידוע"},
    # Hidden while a file has only two speakers - see _render_speakers_html().
    "doc_remove_speaker": {"en": "Remove speaker", "he": "הסרת דובר"},
    "doc_remove_speaker_confirm": {
        "en": "Remove this speaker? Their sentences become unassigned.",
        "he": "להסיר את הדובר? המשפטים שלו יסומנו כדובר לא ידוע.",
    },
    "doc_speaker_colour": {"en": "Speaker colour", "he": "צבע הדובר"},
    "doc_outline": {"en": "Files and speakers", "he": "קבצים ודוברים"},
    "doc_reassign": {"en": "Reassign to", "he": "שיוך ל־"},
    "doc_reassign_line": {"en": "Reassign this sentence", "he": "שיוך המשפט הזה לדובר אחר"},
    "doc_file_position": {"en": "{i} / {n}", "he": "{i} / {n}"},
    # --- Help panel -----------------------------------------------------
    # The toolbar button and the panel it opens - see _render_help_html() in
    # core/formatting, which builds the panel server-side from these same
    # keys (via document_strings(), same as every other doc_ key above).
    "doc_help": {"en": "Help", "he": "עזרה"},
    "doc_help_title": {"en": "Help", "he": "עזרה"},
    "doc_help_close": {"en": "Close help", "he": "סגירת העזרה"},
    "doc_tour_start": {"en": "Start guided tour", "he": "התחלת סיור מודרך"},
    "doc_help_search_title": {"en": "Search", "he": "חיפוש"},
    "doc_help_search_desc": {
        "en": "Type to search every turn in this recording. The chevrons - "
        "or Enter and Shift+Enter - jump to the next or previous "
        "match.",
        "he": "הקלידו כדי לחפש בכל הפסקאות בהקלטה. החצים - או Enter ו-"
        "Shift+Enter - עוברים להתאמה הבאה או הקודמת.",
    },
    "doc_help_flags_title": {"en": "Show uncertain words", "he": "הצגת מילים לא ודאיות"},
    "doc_help_flags_desc": {
        "en": "On by default: words the model was least sure about get a "
        "tinted, dotted underline, and words the app corrected from your "
        "term list a solid one. Click one to pick a fix, type your own "
        "word, or keep it.",
        "he": "פעיל כברירת מחדל: מילים שהמודל היה הכי פחות בטוח לגביהן "
        "מסומנות בקו תחתון מנוקד וצבוע, ומילים שהאפליקציה תיקנה לפי "
        "רשימת המונחים שלכם - בקו מלא. לחיצה על מילה פותחת תיקון: "
        "בחירה מהרשימה, הקלדת מילה אחרת או השארה כמו שהיא.",
    },
    # --- Click-to-fix menu on an uncertain word (js/42-fix-menu.js) ---
    "doc_fix_menu": {"en": "Fix this word", "he": "תיקון המילה"},
    "doc_fix_unsure": {"en": "The model was unsure", "he": "המודל לא היה בטוח"},
    "doc_fix_autofixed": {"en": "Auto-corrected from", "he": "תוקן אוטומטית, במקור:"},
    "doc_fix_terms": {"en": "From your terms", "he": "מהמונחים שלך"},
    "doc_fix_none": {"en": "No close term in your list.", "he": "אין מונח קרוב ברשימה שלך."},
    "doc_fix_restore": {"en": "Restore original", "he": "החזרת המקור"},
    "doc_fix_other": {"en": "Another word…", "he": "מילה אחרת…"},
    "doc_fix_keep": {"en": "Keep as is", "he": "להשאיר כמו שזה"},
    "doc_help_theme_title": {"en": "Light / dark mode", "he": "מצב בהיר / כהה"},
    "doc_help_theme_desc": {
        "en": "Switches this page's colour scheme and remembers your choice "
        "in this browser, independent of your system's own setting.",
        "he": "מחליף את ערכת הצבעים של הדף וזוכר את הבחירה בדפדפן הזה, בנפרד מהגדרת המערכת שלכם.",
    },
    "doc_help_save_title": {"en": "Saving", "he": "שמירה"},
    "doc_help_save_desc": {
        "en": "Writes this page's edits to a file. Where your browser "
        'supports it, this button reads "Save", and Ctrl+S writes to '
        "the same file every time once you have chosen one; "
        "Ctrl+Shift+S always asks for a different file, without "
        "changing where Ctrl+S goes. Otherwise both download a fresh "
        "copy with every edit baked in - opened from a file, this "
        "page can only save automatically to this browser, so that "
        "download is what actually writes your edits to disk.",
        "he": "כותב את השינויים בדף לקובץ. בדפדפן שתומך בכך הכפתור נקרא "
        '"שמירה", ו-Ctrl+S כותב לאותו קובץ בכל פעם לאחר שנבחר קובץ '
        "כזה; Ctrl+Shift+S תמיד מבקש קובץ אחר, מבלי לשנות לאן Ctrl+S "
        "כותב. בדפדפן אחר שני הקיצורים מורידים עותק חדש עם כל השינויים "
        "משולבים בו - כשהדף נפתח מקובץ, הוא יכול לשמור את השינויים "
        "באופן אוטומטי רק בדפדפן הזה, כך שההורדה הזו היא הפעולה "
        "שבאמת כותבת אותם לקובץ בדיסק.",
    },
    "doc_help_outline_title": {"en": "Files and speakers", "he": "קבצים ודוברים"},
    "doc_help_outline_desc": {
        "en": "Lists every file in this batch and, for each one, the "
        "speakers detected in it. Click a filename to jump straight "
        "to it.",
        "he": "מציג את כל הקבצים באצווה ואת הדוברים שזוהו בכל אחד מהם. "
        "לחיצה על שם קובץ קופצת אליו ישירות.",
    },
    "doc_help_speakers_title": {"en": "Speaker names and colours", "he": "שמות וצבעי דוברים"},
    "doc_help_speakers_desc": {
        "en": "Rename a speaker by typing over their name in this list, "
        "and recolour them from the swatch beside it. Every sentence "
        "carries its own speaker chip - click it to reassign just "
        "that sentence, or the whole block of sentences around it, "
        "to someone else.",
        "he": "שנו את שם הדובר על ידי הקלדה מעל השם ברשימה, והחליפו את "
        "צבעו דרך העיגול הצבעוני שלצידו. לכל משפט יש תגית דובר "
        "משלו - לחצו עליה כדי לשייך רק את המשפט הזה, או את כל הקטע "
        "שסביבו, לדובר אחר.",
    },
    "doc_help_playback_title": {"en": "Play a moment", "he": "השמעת רגע"},
    "doc_help_playback_desc": {
        "en": "Click a sentence's own timestamp to play just that "
        "sentence; playback stops again at its end.",
        "he": "לחצו על חותמת הזמן של משפט כדי להשמיע רק אותו; ההשמעה נעצרת שוב בסופו.",
    },
    "doc_help_editing_title": {"en": "Editing the transcript", "he": "עריכת התמלול"},
    "doc_help_editing_desc": {
        "en": "Click into any turn's text to correct it directly, the same "
        "way you would edit a document. Changes save automatically "
        'to this browser as you type - use "Save a copy" to write '
        "them into a file you can keep or share.",
        "he": "לחצו לתוך הטקסט של כל פסקה כדי לתקן אותו ישירות, כמו עריכת "
        "מסמך רגיל. השינויים נשמרים אוטומטית בדפדפן תוך כדי ההקלדה - "
        'השתמשו ב"שמירת עותק" כדי לכתוב אותם לקובץ שאפשר לשמור או '
        "לשתף.",
    },
    "doc_help_plain_title": {"en": "Plain text", "he": "טקסט רגיל"},
    "doc_help_plain_desc": {
        "en": "Every sentence has its own copy button too, for just that "
        "one sentence. A copy-friendly version of the whole "
        "recording sits at the bottom of the page, with its own "
        "toggles for timestamps and speaker names - edit it there "
        "directly, or copy it out with one click.",
        "he": "לכל משפט יש גם כפתור העתקה משלו, רק בשבילו. גרסה נוחה "
        "להעתקה של ההקלטה כולה נמצאת בתחתית הדף, עם מתגים משלה "
        "לחותמות זמן ולשמות דוברים - אפשר לערוך אותה שם ישירות, או "
        "להעתיק אותה בלחיצה אחת.",
    },
    # --- Guided tour ------------------------------------------------------
    # Bound entirely in the page script (bindTour()) - #tour-start above is the
    # only server-rendered hook; every spotlight step, its caption card, and
    # this copy are built by script. Steps are worded as direct address
    # ("this sidebar", "click a timestamp") rather than the help panel's
    # third-person reference style ("Lists every file..."), since a tour step
    # is spoken while the reader is looking straight at the control, not
    # reading a list of them afterward.
    "doc_tour_next": {"en": "Next", "he": "הבא"},
    "doc_tour_back": {"en": "Back", "he": "הקודם"},
    "doc_tour_skip": {"en": "Skip", "he": "דילוג"},
    "doc_tour_done": {"en": "Done", "he": "סיום"},
    "doc_tour_step_position": {"en": "{i} / {n}", "he": "{i} / {n}"},
    "doc_tour_file_title": {"en": "This recording", "he": "ההקלטה הזו"},
    "doc_tour_file_body": {
        "en": "This bar stays on screen and names the file you're reading - "
        "in a batch, it also shows its position among the others.",
        "he": "הסרגל הזה נשאר צמוד למסך ומציג את שם הקובץ שבו אתם צופים "
        "כרגע - באצווה, הוא גם מציג את מיקומו מבין שאר הקבצים.",
    },
    "doc_tour_outline_title": {"en": "Files and speakers", "he": "קבצים ודוברים"},
    "doc_tour_outline_body": {
        "en": "This sidebar lists every file in the batch and, for each "
        "one, the speakers detected inside it. Click a filename to "
        "jump straight to it.",
        "he": "בסרגל הצד הזה רשומים כל הקבצים באצווה, ולכל אחד מהם - "
        "הדוברים שזוהו בו. לחיצה על שם קובץ קופצת אליו ישירות.",
    },
    "doc_tour_search_title": {"en": "Search", "he": "חיפוש"},
    "doc_tour_search_body": {
        "en": "Type here to search every turn in this recording. The "
        "chevrons - or Enter and Shift+Enter - jump to the next or "
        "previous match.",
        "he": "הקלידו כאן כדי לחפש בכל הפסקאות בהקלטה. החצים - או Enter "
        "ו-Shift+Enter - עוברים להתאמה הבאה או הקודמת.",
    },
    "doc_tour_speakers_title": {"en": "Speaker names and colours", "he": "שמות וצבעי דוברים"},
    "doc_tour_speakers_body": {
        "en": "Rename a speaker here, or recolour them from the swatch "
        "beside their name. Clicking a sentence's own speaker chip "
        "reassigns just that sentence, or the whole block around it, "
        "to someone else.",
        "he": "כאן אפשר לשנות את שם הדובר, או להחליף את צבעו דרך העיגול "
        "הצבעוני שלצידו. לחיצה על תגית הדובר של משפט משייכת רק "
        "אותו, או את כל הקטע שסביבו, לדובר אחר.",
    },
    "doc_tour_playback_title": {"en": "Play a moment", "he": "השמעת רגע"},
    "doc_tour_playback_body": {
        "en": "Click a sentence's own timestamp to play the recording from "
        "there - a small player appears, and stops again at the "
        "sentence's own end.",
        "he": "לחיצה על חותמת הזמן של משפט משמיעה את ההקלטה משם - נגן קטן "
        "מופיע, ועוצר שוב בסוף אותו משפט.",
    },
    "doc_tour_editing_title": {"en": "Editing the transcript", "he": "עריכת התמלול"},
    "doc_tour_editing_body": {
        "en": "Click into any turn's text to correct it directly. Changes "
        "save automatically to this browser as you type.",
        "he": "לחצו לתוך הטקסט של כל פסקה כדי לתקן אותו ישירות. השינויים "
        "נשמרים אוטומטית בדפדפן תוך כדי ההקלדה.",
    },
    "doc_tour_flags_title": {"en": "Show uncertain words", "he": "הצגת מילים לא ודאיות"},
    "doc_tour_flags_body": {
        "en": "Words the model was least sure about are highlighted, so "
        "you know what's worth a second look - click one to fix it. This "
        "button turns the highlighting off and on.",
        "he": "מילים שהמודל היה הכי פחות בטוח לגביהן מודגשות, כך שתדעו "
        "מה כדאי לבדוק שוב - לחצו על מילה כדי לתקן אותה. הכפתור הזה "
        "מכבה ומדליק את ההדגשה.",
    },
    "doc_tour_export_title": {"en": "Save a copy", "he": "שמירת עותק"},
    "doc_tour_export_body": {
        "en": "This page can only save your edits to this browser "
        'automatically. "Save a copy" is what actually writes them '
        "into a real file you can keep or share.",
        "he": "הדף הזה יכול לשמור את השינויים באופן אוטומטי רק בדפדפן. "
        '"שמירת עותק" היא הפעולה שבאמת כותבת אותם לקובץ אמיתי '
        "שאפשר לשמור או לשתף.",
    },
    # --- Worker / thread progress messages (keys cross the process boundary) ---
    "w_starting_thread": {"en": "Starting...", "he": "מתחיל..."},
    "w_initializing": {"en": "Initializing...", "he": "מאתחל..."},
    "w_loading_model": {"en": "Loading {model} model...", "he": "טוען מודל {model}..."},
    # First run only: the weights are 1.6-3.1 GB and this can take tens of
    # minutes. The progress is a FILE count, not a percentage of bytes -
    # see Transcriber._fetch_weights for why that is the only signal
    # huggingface_hub exposes to a caller. {size} carries the total so the
    # message still says how much is coming. Latin quantities inside Hebrew
    # text are isolated, like every other number in this table.
    "w_downloading_model": {
        "en": "Downloading model ({size}, one time): file {done} of {total}",
        "he": "מוריד מודל ("
        + _LRI
        + "{size}"
        + _PDI
        + ", חד-פעמי): קובץ "
        + _LRI
        + "{done} מתוך {total}"
        + _PDI,
    },
    "w_model_loaded": {"en": "Model loaded: {model}", "he": "המודל {model} נטען"},
    "w_error_loading": {
        "en": "Error loading model: {detail}",
        "he": "שגיאה בטעינת המודל: {detail}",
    },
    "w_model_not_loaded": {"en": "Model not loaded", "he": "המודל לא נטען"},
    "w_starting": {"en": "Starting transcription...", "he": "מתחיל תמלול..."},
    "w_transcribing_time": {
        "en": "Transcribing audio... {position} / {total}",
        "he": "מתמלל אודיו... {position} / {total}",
    },
    "w_transcribing_seg": {
        "en": "Transcribing audio... segment {n}",
        "he": "מתמלל אודיו... מקטע {n}",
    },
    "w_transcription_done": {"en": "Transcription complete", "he": "התמלול הסתיים"},
    "w_analyzing_audio": {"en": "Analyzing audio...", "he": "מנתח את האודיו..."},
    "w_stereo_detected": {
        "en": "Separate channel per speaker detected - exact speaker labels",
        "he": "זוהה ערוץ נפרד לכל דובר - זיהוי דוברים מדויק",
    },
    "w_identifying_speakers": {"en": "Identifying speakers...", "he": "מזהה דוברים..."},
    "w_downloading_diarization": {
        "en": "Downloading speaker models (one time, ~36 MB)...",
        "he": "מוריד מודלים לזיהוי דוברים (חד-פעמי, כ-" + _LRI + "36 MB" + _PDI + ")...",
    },
    # Shown when diarization failed. The transcript itself is fine, so this is
    # phrased as a missing extra rather than an error.
    "w_speakers_unavailable": {
        "en": "Speaker identification unavailable - transcript saved without labels",
        "he": "זיהוי דוברים אינו זמין - התמלול נשמר ללא תוויות",
    },
    "w_correcting_terms": {"en": "Checking Hebrew terms...", "he": "בודק מונחים בעברית..."},
    # Per-file status during a batch run. Opens with a Hebrew word in both
    # languages, so - like w_loading_model above - it needs no RLM anchor
    # even though {name} at the end is a filename.
    "w_file_progress": {
        "en": "File {i}/{n}: {name}",
        "he": "קובץ {i} מתוך {n}: " + _LRI + "{name}" + _PDI,
    },
    "w_formatting": {"en": "Formatting output...", "he": "מעצב את הפלט..."},
    "w_saving": {"en": "Saving output file...", "he": "שומר את קובץ הפלט..."},
    "w_complete": {"en": "Complete!", "he": "הושלם!"},
    "w_error": {"en": "Error: {detail}", "he": "שגיאה: {detail}"},
    "status_analyzing": {"en": "Analyzing audio near {time}...", "he": "מנתח אודיו סביב {time}..."},
    "status_retry_compression": {
        "en": "Unclear audio - retrying at a higher decoding temperature ({temp})...",
        "he": "אודיו לא ברור - מנסה שוב בטמפרטורת פענוח גבוהה יותר ({temp})...",
    },
    "status_retry_logprob": {
        "en": "Low-confidence result - retrying at a higher decoding temperature ({temp})...",
        "he": "תוצאה בביטחון נמוך - מנסה שוב בטמפרטורת פענוח גבוהה יותר ({temp})...",
    },
    # --- Errors surfaced in the GUI ---
    "err_load_model": {"en": "Failed to load transcription model", "he": "טעינת מודל התמלול נכשלה"},
    # Split from err_load_model because the two ask for opposite things from
    # the user. A model that will not load is a reason to pick another one; a
    # model that cannot be REACHED is a reason to check the connection and
    # try the same one again. The first run of a model is the only time this
    # can happen - once the weights are cached, loading never touches the
    # network at all, which is what the second sentence is telling the user.
    "err_load_model_offline": {
        "en": (
            "Could not download the model - no connection to the internet. "
            "Once a model has been downloaded once, it works offline."
        ),
        "he": (
            "לא ניתן להוריד את המודל - אין חיבור לאינטרנט. "
            "לאחר הורדה ראשונה, המודל עובד גם ללא חיבור."
        ),
    },
    "err_transcription_failed": {
        "en": "Transcription failed: {detail}",
        "he": "התמלול נכשל: {detail}",
    },
    "err_worker_exited": {
        "en": "Transcription worker process exited unexpectedly",
        "he": "תהליך התמלול הסתיים באופן בלתי צפוי",
    },
    "err_cancelled": {"en": "Transcription cancelled", "he": "התמלול בוטל"},
    # Raw exception text stays untranslated - it's inherently English.
    "err_generic": {"en": "{detail}", "he": "{detail}"},
    "copy_error_details": {"en": "Copy details", "he": "העתק פרטים"},
    "error_details_copied": {"en": "Copied!", "he": "הועתק!"},
}

# Per-model card texts, keyed by the model names in config.MODELS. Model
# names themselves stay Latin in both languages (they're technical
# identifiers, like the ivrit.ai repo names they map to). "name",
# "description", "purpose" and "accuracy" are rendered in the GUI; the rest mirror
# config.MODELS so any future card expansion is already translated.
# dict[str, str] values are a single per-language string; the
# list[dict[str, str]] ones (pros, cons) hold one such dict per bullet.
MODEL_STRINGS: dict[str, dict[str, dict[str, str] | list[dict[str, str]]]] = {
    "ivrit-turbo": {
        "name": {"en": "Ivrit Turbo", "he": "Ivrit Turbo"},
        "description": {
            "en": "Hebrew-tuned, fast and accurate",
            "he": "מותאם לעברית, מהיר ומדויק",
        },
        "purpose": {
            "en": "The right choice for almost every recording: Hebrew-tuned, and about 5x faster than Ivrit Large.",
            # Isolated, with a non-breaking space: otherwise the line can
            # break inside the Latin name and the bidi pass reorders the
            # halves ("Ivrit-מ" ... "Large").
            "he": "הבחירה הנכונה כמעט לכל הקלטה: מותאם לעברית, ומהיר פי 5 בערך מ-"
            + _LRI
            + "Ivrit Large"
            + _PDI
            + ".",
        },
        "accuracy": {"en": "High", "he": "גבוה"},
        "pros": [
            {
                "en": "✓ Trained specifically on Hebrew speech",
                "he": "✓ אומן במיוחד על דיבור בעברית",
            },
            {
                "en": "✓ Far fewer misheard Hebrew words than stock Whisper",
                "he": "✓ הרבה פחות מילים שגויות בעברית מ-Whisper הרגיל",
            },
            {
                "en": "✓ Turbo decoder: about 5x faster than Ivrit Large",
                "he": "✓ מפענח Turbo: מהיר פי 5 בערך מ-Ivrit Large",
            },
            {"en": "✓ Best choice for Hebrew content", "he": "✓ הבחירה הטובה ביותר לתוכן בעברית"},
        ],
        "cons": [
            {
                "en": "✗ One-time 1.6 GB download on first use",
                "he": "✗ הורדה חד-פעמית של 1.6 GB בשימוש הראשון",
            },
            {"en": "✗ Requires 3 GB RAM", "he": "✗ דורש 3 GB זיכרון"},
            {
                "en": "✗ Slightly less accurate than Ivrit Large on hard audio",
                "he": "✗ מעט פחות מדויק מ-Ivrit Large באודיו קשה",
            },
        ],
        "time_estimate": {"en": "~8-12 hours", "he": "כ-8-12 שעות"},
        "best_for": {"en": "Hebrew transcription (RECOMMENDED)", "he": "תמלול בעברית (מומלץ)"},
    },
    "ivrit-large": {
        "name": {"en": "Ivrit Large", "he": "Ivrit Large"},
        "description": {
            "en": "Hebrew-tuned, highest accuracy, slow",
            "he": "מותאם לעברית, הדיוק הגבוה ביותר, איטי",
        },
        "purpose": {
            "en": "For hard-to-hear or critical recordings, when you can wait. Slightly more accurate, much slower.",
            "he": "להקלטות קשות לשמיעה או קריטיות, כשאפשר לחכות. מעט מדויק יותר, איטי בהרבה.",
        },
        "accuracy": {"en": "Highest", "he": "הגבוה ביותר"},
        "pros": [
            {
                "en": "✓ Most accurate Hebrew option available",
                "he": "✓ האפשרות המדויקת ביותר לעברית",
            },
            {
                "en": "✓ Best for critical or hard-to-hear recordings",
                "he": "✓ הטוב ביותר להקלטות קריטיות או קשות לשמיעה",
            },
        ],
        "cons": [
            {
                "en": "✗ One-time 3.1 GB download on first use",
                "he": "✗ הורדה חד-פעמית של 3.1 GB בשימוש הראשון",
            },
            {"en": "✗ Very slow (40+ hours)", "he": "✗ איטי מאוד (מעל 40 שעות)"},
            {"en": "✗ High RAM requirement (8 GB)", "he": "✗ דרישת זיכרון גבוהה (8 GB)"},
            {
                "en": "✗ Rarely worth it over Ivrit Turbo",
                "he": "✗ לרוב לא שווה את זה לעומת Ivrit Turbo",
            },
        ],
        "time_estimate": {"en": "~40+ hours", "he": "מעל כ-40 שעות"},
        "best_for": {"en": "Critical Hebrew content", "he": "תוכן קריטי בעברית"},
    },
}

_current_lang = "en"


class LanguageManager(QObject):
    """Qt signal hub so widgets can react to language switches."""

    language_changed = pyqtSignal(str)


language_manager = LanguageManager()


def get_language() -> str:
    return _current_lang


def is_rtl() -> bool:
    return _current_lang == "he"


def layout_direction() -> "Qt.LayoutDirection":
    """Qt layout direction matching the current UI language."""
    from PyQt5.QtCore import Qt

    return Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def load_saved_language() -> str:
    """Read the persisted language choice; English on first-ever launch."""
    lang = str(_settings().value(_SETTINGS_KEY, "en"))
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def apply_saved_language(app: "QGuiApplication") -> None:
    """Bootstrap the persisted UI language onto a fresh QApplication, before
    any widget is built: loads the saved choice (English on first-ever
    launch), sets it without re-saving, and applies the matching app-wide
    layout direction. Called by every GUI entry point.
    """
    set_language(load_saved_language(), save=False)
    app.setLayoutDirection(layout_direction())


def set_language(lang: str, save: bool = True) -> None:
    """Switch the UI language, optionally persisting it, and notify widgets."""
    global _current_lang
    if lang not in SUPPORTED_LANGUAGES:
        logger.warning(f"Unsupported UI language {lang!r}, falling back to 'en'")
        lang = "en"
    if lang == _current_lang:
        return
    _current_lang = lang
    if save:
        _settings().setValue(_SETTINGS_KEY, lang)
    logger.info(f"UI language set to {lang}")
    language_manager.language_changed.emit(lang)


def t(key: str, **fmt: object) -> str:
    """Translate a key in the current language, applying str.format params.
    Falls back to English if the key has no entry for the current language,
    and to the bare key if it's unknown entirely (visible, but non-fatal).
    """
    entry = STRINGS.get(key)
    if entry is None:
        logger.warning(f"Unknown i18n key: {key!r}")
        return key
    text = entry.get(_current_lang) or entry["en"]
    return text.format(**fmt) if fmt else text


_DOC_PREFIX = "doc_"


def document_strings() -> dict[str, str]:
    """Every string the generated transcript page needs, in the current language.

    Returned with the "doc_" prefix stripped, because the keys the renderer
    and the page script (core/assets/js/) look up are the bare names - the prefix only exists to
    keep this group identifiable in STRINGS.

    Placeholders are left unsubstituted on purpose: "Play from {t}" is filled
    in per turn by the renderer, which knows the timestamp.
    """
    return {key[len(_DOC_PREFIX) :]: t(key) for key in STRINGS if key.startswith(_DOC_PREFIX)}


def format_duration(seconds: int, elide_zero: bool = True) -> str:
    """A duration in the current language: "1m 46s" / "1 דק' 46 שנ'".

    The same <60s / <1h / else ladder as
    hardware_detection._format_duration, and the same elide_zero meaning -
    drop a trailing zero component ("5m", not "5m 0s") when the string is
    going in front of a user. That function stays where it is and keeps its
    English output: it also builds the debug "reason" line that goes to the
    log, which should not follow the UI language. This is the display half,
    and it lives here because the unit words are string-table data like any
    other.
    """
    if seconds < 60:
        return t("dur_s", seconds=seconds)
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        if elide_zero and secs == 0:
            return t("dur_m", minutes=minutes)
        return t("dur_ms", minutes=minutes, seconds=secs)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if elide_zero and minutes == 0:
        return t("dur_h", hours=hours)
    return t("dur_hm", hours=hours, minutes=minutes)


def model_text(model: str, field: str, index: int | None = None) -> str:
    """Translated text for a config.MODELS-derived field (e.g. card description).

    `index` picks one bullet out of a list-valued field (pros, cons); every
    other field holds a single per-language dict and takes no index. Which
    fields are lists is a fixed property of the table above, so the pairing
    is a fact about the call site rather than something to re-check at
    runtime - hence casts rather than isinstance guards.
    """
    value = MODEL_STRINGS[model][field]
    entry = (
        cast("list[dict[str, str]]", value)[index]
        if index is not None
        else cast("dict[str, str]", value)
    )
    return entry.get(_current_lang) or entry["en"]
