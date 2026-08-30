"""
UI internationalization: English/Hebrew string table and language state.

Hand-rolled rather than Qt Linguist (.ts/.qm) on purpose: the two hard
problems here are strings that originate in the transcription worker
process (speech_to_text.core must never import PyQt5, so it emits message
KEYS that the GUI renders at display time) and data-driven text for the
model cards - a plain dict handles both uniformly.

Nothing in speech_to_text.core may import this module.
"""

import logging

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

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

STRINGS = {
    # --- Main window ---
    "app_title": {"en": "Hebrew Audio Transcriber", "he": "מתמלל אודיו בעברית"},
    # The nav buttons are IconTextButtons (gui/widgets.py): plain words
    # here, the icons and their visual side are handled by the widget.
    "nav_back": {"en": "Back", "he": "חזרה"},
    "nav_cancel": {"en": "Cancel", "he": "ביטול"},
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
    "drop_main": {"en": "Drag your audio or video file here", "he": "גררו לכאן קובץ אודיו או וידאו"},
    "drop_formats": {"en": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV", "he": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV"},
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
    # a bare 20px "x" with no label of any kind before this step. {filename}
    # disambiguates which row's button this is once more than one file is
    # queued; a generic "Remove" would be indistinguishable across rows to
    # a screen reader jumping between controls rather than reading linearly.
    "remove_file": {"en": "Remove {filename}", "he": "הסרת {filename}"},
    "file_info": {
        "en": "{filename} | {minutes}m {seconds}s | {size} MB",
        "he": _RLM + "{filename} | {minutes} דק' {seconds} שנ' | {size} MB",
    },
    # Summary line above the file list. Unlike file_info, this doesn't open
    # with a filename - it opens with the count - so it needs no RLM anchor
    # (the Hebrew string already starts with a strong-RTL character).
    "files_summary": {
        "en": "{count} files selected | Total: {minutes}m {seconds}s",
        "he": "נבחרו {count} קבצים | סה\"כ: {minutes} דק' {seconds} שנ'",
    },
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
    "identify_speakers": {"en": "Identify speakers", "he": "זהה דוברים"},
    "speaker_count": {"en": "How many people:", "he": "כמה אנשים:"},
    "transcription_failed": {"en": "Transcription failed: {message}", "he": "התמלול נכשל: {message}"},
    "model_desc_est": {"en": "{desc} | Est: {time}", "he": "{desc} | משוער: {time}"},

    # --- Step 3: transcription ---
    "transcribing_title": {"en": "Transcribing", "he": "מתמלל"},
    "file_model_info": {"en": "{filename} | Model: {model}", "he": _RLM + "{filename} | מודל: {model}"},
    "elapsed": {"en": "Elapsed: {elapsed}", "he": "זמן שחלף: {elapsed}"},
    "elapsed_remaining": {
        "en": "Elapsed: {elapsed}  |  Est. remaining: {remaining}",
        "he": "זמן שחלף: {elapsed}  |  נותר (משוער): {remaining}",
    },
    "calculating": {"en": "calculating...", "he": "בחישוב..."},
    "transcription_complete": {"en": "Transcription Complete!", "he": "התמלול הושלם!"},
    "saved_to": {"en": "Saved to:\n{path}", "he": "נשמר אל:\n" + _RLM + "{path}"},
    "open_transcript": {"en": "Open transcript", "he": "פתיחת התמלול"},

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
    # core/assets/the page script (core/assets/js/) and core/formatting look up.
    "doc_toolbar": {"en": "Transcript tools", "he": "כלי תמלול"},
    "doc_search": {"en": "Search transcript", "he": "חיפוש בתמלול"},
    "doc_search_prev": {"en": "Previous match", "he": "התאמה קודמת"},
    "doc_search_next": {"en": "Next match", "he": "התאמה הבאה"},
    "doc_no_results": {"en": "No results", "he": "אין תוצאות"},
    "doc_show_uncertain": {"en": "Show uncertain words", "he": "הצג מילים לא ודאיות"},
    # Two keys, not one - the button names the action it is about to take, and
    # that action is the opposite of the current state. The page script (core/assets/js/) swaps
    # between them on click, alongside the existing aria-pressed/data-theme
    # handling - "Theme" told the reader nothing about what clicking it did.
    "doc_theme_light": {"en": "Light mode", "he": "מצב בהיר"},
    "doc_theme_dark": {"en": "Dark mode", "he": "מצב כהה"},
    "doc_toggle_theme": {"en": "Switch colour scheme", "he": "החלפת ערכת צבעים"},
    "doc_save_copy": {"en": "Save a copy", "he": "שמירת עותק"},
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
    "doc_copy_turn": {"en": "Copy this turn", "he": "העתקת פסקה"},
    "doc_copy_line": {"en": "Copy this sentence", "he": "העתקת המשפט"},
    "doc_turn_text": {"en": "Turn text", "he": "טקסט הפסקה"},
    "doc_play_from": {"en": "Play from {t}", "he": "נגן מ־{t}"},
    # The speaker menu's scope group, added once a bubble's own reassignment
    # control can move either a single sentence or the whole block of
    # sentences around it (see buildSpeakerMenu() in
    # js/24-speakers-menus.js) - the cluster header used to be the only way
    # to reassign a whole block, and that control is gone now that cards are
    # flat, so this replaces it rather than losing the feature.
    "doc_reassign_scope": {"en": "Apply to", "he": "החל על"},
    "doc_reassign_scope_line": {"en": "This sentence", "he": "המשפט הזה"},
    "doc_reassign_scope_block": {"en": "This whole block", "he": "כל הקטע הזה"},
    # Two keys, not one - same "the button names the action it is about to
    # take" reasoning as doc_theme_light/doc_theme_dark above. The page script (core/assets/js/)
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
    "doc_copied": {"en": "Copied", "he": "הועתק"},
    "doc_add_speaker": {"en": "Add speaker", "he": "הוספת דובר"},
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
        "en": "Highlights the words the model itself was least sure about, "
              "with a tinted, dotted underline - worth a second look before "
              "you trust them.",
        "he": "מדגיש את המילים שהמודל היה הכי פחות בטוח לגביהן, בקו תחתון "
              "מנוקד וצבוע - כדאי לבדוק אותן שוב לפני שסומכים עליהן.",
    },
    "doc_help_theme_title": {"en": "Light / dark mode", "he": "מצב בהיר / כהה"},
    "doc_help_theme_desc": {
        "en": "Switches this page's colour scheme and remembers your choice "
              "in this browser, independent of your system's own setting.",
        "he": "מחליף את ערכת הצבעים של הדף וזוכר את הבחירה בדפדפן הזה, "
              "בנפרד מהגדרת המערכת שלכם.",
    },
    "doc_help_save_title": {"en": "Save a copy", "he": "שמירת עותק"},
    "doc_help_save_desc": {
        "en": "Downloads a fresh copy of this page with every edit baked "
              "in. Opened from a file, the page can only save your edits "
              "to this browser automatically - this is what actually "
              "writes them to a file on disk.",
        "he": "מוריד עותק חדש של הדף עם כל השינויים משולבים בו. כשהדף נפתח "
              "מקובץ, הוא יכול לשמור את השינויים באופן אוטומטי רק בדפדפן "
              "הזה - זו הפעולה שבאמת כותבת אותם לקובץ בדיסק.",
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
        "he": "לחצו על חותמת הזמן של משפט כדי להשמיע רק אותו; ההשמעה "
              "נעצרת שוב בסופו.",
    },
    "doc_help_editing_title": {"en": "Editing the transcript", "he": "עריכת התמלול"},
    "doc_help_editing_desc": {
        "en": "Click into any turn's text to correct it directly, the same "
              "way you would edit a document. Changes save automatically "
              "to this browser as you type - use \"Save a copy\" to write "
              "them into a file you can keep or share.",
        "he": "לחצו לתוך הטקסט של כל פסקה כדי לתקן אותו ישירות, כמו עריכת "
              "מסמך רגיל. השינויים נשמרים אוטומטית בדפדפן תוך כדי ההקלדה - "
              "השתמשו ב\"שמירת עותק\" כדי לכתוב אותם לקובץ שאפשר לשמור או "
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
    # Bound entirely in the page script (core/assets/js/) (bindTour()) - #tour-start above is the
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
        "en": "This button highlights the words the model itself was "
              "least sure about, so you know what's worth a second look.",
        "he": "הכפתור הזה מדגיש את המילים שהמודל היה הכי פחות בטוח "
              "לגביהן, כך שתדעו מה כדאי לבדוק שוב.",
    },
    "doc_tour_export_title": {"en": "Save a copy", "he": "שמירת עותק"},
    "doc_tour_export_body": {
        "en": "This page can only save your edits to this browser "
              "automatically. \"Save a copy\" is what actually writes them "
              "into a real file you can keep or share.",
        "he": "הדף הזה יכול לשמור את השינויים באופן אוטומטי רק בדפדפן. "
              "\"שמירת עותק\" היא הפעולה שבאמת כותבת אותם לקובץ אמיתי "
              "שאפשר לשמור או לשתף.",
    },

    # --- Worker / thread progress messages (keys cross the process boundary) ---
    "w_starting_thread": {"en": "Starting...", "he": "מתחיל..."},
    "w_initializing": {"en": "Initializing...", "he": "מאתחל..."},
    "w_loading_model": {"en": "Loading {model} model...", "he": "טוען מודל {model}..."},
    "w_model_loaded": {"en": "Model loaded: {model}", "he": "המודל {model} נטען"},
    "w_error_loading": {"en": "Error loading model: {detail}", "he": "שגיאה בטעינת המודל: {detail}"},
    "w_model_not_loaded": {"en": "Model not loaded", "he": "המודל לא נטען"},
    "w_starting": {"en": "Starting transcription...", "he": "מתחיל תמלול..."},
    "w_transcribing_time": {
        "en": "Transcribing audio... {position} / {total}",
        "he": "מתמלל אודיו... {position} / {total}",
    },
    "w_transcribing_seg": {"en": "Transcribing audio... segment {n}", "he": "מתמלל אודיו... מקטע {n}"},
    "w_transcription_done": {"en": "Transcription complete", "he": "התמלול הסתיים"},
    "w_analyzing_audio": {"en": "Analyzing audio...", "he": "מנתח את האודיו..."},
    "w_stereo_detected": {
        "en": "Separate channel per speaker detected - exact speaker labels",
        "he": "זוהה ערוץ נפרד לכל דובר - זיהוי דוברים מדויק",
    },
    "w_identifying_speakers": {"en": "Identifying speakers...", "he": "מזהה דוברים..."},
    "w_downloading_diarization": {
        "en": "Downloading speaker models (one time, ~36 MB)...",
        "he": "מוריד מודלים לזיהוי דוברים (חד-פעמי, כ-36 MB)...",
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
    "w_file_progress": {"en": "File {i}/{n}: {name}", "he": "קובץ {i} מתוך {n}: {name}"},
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
    "err_transcription_failed": {"en": "Transcription failed", "he": "התמלול נכשל"},
    "err_worker_exited": {
        "en": "Transcription worker process exited unexpectedly",
        "he": "תהליך התמלול הסתיים באופן בלתי צפוי",
    },
    "err_cancelled": {"en": "Transcription cancelled", "he": "התמלול בוטל"},
    # Raw exception text stays untranslated - it's inherently English.
    "err_generic": {"en": "{detail}", "he": "{detail}"},
}

# Per-model card texts, keyed by the model names in config.MODELS. Model
# names themselves stay Latin in both languages (they're technical
# identifiers, like the Whisper model names they map to). Only "name" and
# "description" are rendered in the GUI today; the rest mirror
# config.MODELS so any future card expansion is already translated.
MODEL_STRINGS = {
    "tiny": {
        "name": {"en": "Tiny", "he": "Tiny"},
        "description": {"en": "Ultra-fast, lowest quality", "he": "מהיר במיוחד, האיכות הנמוכה ביותר"},
        "pros": [
            {"en": "✓ Fastest option (~30 min for 60-min audio)", "he": "✓ האפשרות המהירה ביותר (כ-30 דק' לשעת אודיו)"},
            {"en": "✓ Minimal RAM (1 GB)", "he": "✓ זיכרון מינימלי (1 GB)"},
            {"en": "✓ Good for: Quick rough drafts, testing", "he": "✓ מתאים לטיוטות מהירות ובדיקות"},
        ],
        "cons": [
            {"en": "✗ Lowest accuracy", "he": "✗ הדיוק הנמוך ביותר"},
            {"en": "✗ Many errors and misheard words", "he": "✗ שגיאות רבות ומילים שגויות"},
            {"en": "✗ Poor Hebrew support", "he": "✗ תמיכה חלשה בעברית"},
        ],
        "time_estimate": {"en": "~30 minutes", "he": "כ-30 דקות"},
        "best_for": {"en": "Quick testing only", "he": "בדיקות מהירות בלבד"},
    },
    "base": {
        "name": {"en": "Base", "he": "Base"},
        "description": {"en": "Good balance of speed and quality", "he": "איזון טוב בין מהירות לאיכות"},
        "pros": [
            {"en": "✓ Reasonable speed (3-5 hours)", "he": "✓ מהירות סבירה (3-5 שעות)"},
            {"en": "✓ Moderate RAM (2 GB)", "he": "✓ זיכרון בינוני (2 GB)"},
            {"en": "✓ Better than tiny, acceptable for casual use", "he": "✓ טוב מ-Tiny, מספיק לשימוש יומיומי"},
        ],
        "cons": [
            {"en": "✗ Moderate accuracy (some errors)", "he": "✗ דיוק בינוני (מעט שגיאות)"},
            {"en": "✗ Not ideal for Hebrew", "he": "✗ לא אידיאלי לעברית"},
            {"en": "✗ Professional users may notice mistakes", "he": "✗ משתמשים מקצועיים יבחינו בטעויות"},
        ],
        "time_estimate": {"en": "~3-5 hours", "he": "כ-3-5 שעות"},
        "best_for": {"en": "Casual transcription", "he": "תמלול יומיומי"},
    },
    "small": {
        "name": {"en": "Small", "he": "Small"},
        "description": {"en": "Better accuracy for Hebrew", "he": "דיוק משופר לעברית"},
        "pros": [
            {"en": "✓ Good accuracy for Hebrew", "he": "✓ דיוק טוב לעברית"},
            {"en": "✓ Reasonable time (8-10 hours)", "he": "✓ זמן סביר (8-10 שעות)"},
            {"en": "✓ 3 GB RAM, manageable", "he": "✓ 3 GB זיכרון, סביר"},
        ],
        "cons": [
            {"en": "✗ Slower than base", "he": "✗ איטי מ-Base"},
            {"en": "✗ Still not perfect accuracy", "he": "✗ הדיוק עדיין אינו מושלם"},
            {"en": "✗ Not recommended for critical content", "he": "✗ לא מומלץ לתוכן קריטי"},
        ],
        "time_estimate": {"en": "~8-10 hours", "he": "כ-8-10 שעות"},
        "best_for": {"en": "Good quality transcription", "he": "תמלול באיכות טובה"},
    },
    "medium": {
        "name": {"en": "Medium", "he": "Medium"},
        "description": {"en": "High accuracy general-purpose model", "he": "מודל כללי בדיוק גבוה"},
        "pros": [
            {"en": "✓ Good accuracy across languages", "he": "✓ דיוק טוב במגוון שפות"},
            {"en": "✓ Professional quality results", "he": "✓ תוצאות באיכות מקצועית"},
            {"en": "✓ Good balance of quality/time", "he": "✓ איזון טוב בין איכות לזמן"},
        ],
        "cons": [
            {"en": "✗ Longer processing (~20-24 hours)", "he": "✗ עיבוד ממושך (כ-20-24 שעות)"},
            {"en": "✗ Requires 5 GB RAM", "he": "✗ דורש 5 GB זיכרון"},
            {"en": "✗ Slower and less accurate on Hebrew than Ivrit Turbo",
             "he": "✗ איטי ופחות מדויק בעברית מ-Ivrit Turbo"},
        ],
        "time_estimate": {"en": "~20-24 hours", "he": "כ-20-24 שעות"},
        "best_for": {"en": "General-purpose transcription", "he": "תמלול כללי"},
    },
    "large": {
        "name": {"en": "Large", "he": "Large"},
        "description": {"en": "Best general-purpose model, very slow",
                        "he": "המודל הכללי הטוב ביותר, איטי מאוד"},
        "pros": [
            {"en": "✓ Highest accuracy of the general-purpose models",
             "he": "✓ הדיוק הגבוה ביותר מבין המודלים הכלליים"},
            {"en": "✓ Handles mixed-language audio well", "he": "✓ מתמודד היטב עם אודיו רב-לשוני"},
            {"en": "✓ Fewest errors outside Hebrew", "he": "✓ הכי מעט שגיאות מחוץ לעברית"},
        ],
        "cons": [
            {"en": "✗ Very slow (40+ hours)", "he": "✗ איטי מאוד (מעל 40 שעות)"},
            {"en": "✗ High RAM requirement (8 GB)", "he": "✗ דרישת זיכרון גבוהה (8 GB)"},
            {"en": "✗ May run out of memory on limited systems", "he": "✗ הזיכרון עלול להיגמר במערכות מוגבלות"},
            {"en": "✗ Still trained mostly on non-Hebrew speech",
             "he": "✗ אומן בעיקר על דיבור שאינו עברית"},
        ],
        "time_estimate": {"en": "~40+ hours", "he": "מעל כ-40 שעות"},
        "best_for": {"en": "Mixed-language or non-Hebrew content", "he": "תוכן רב-לשוני או שאינו עברית"},
    },
    "ivrit-turbo": {
        "name": {"en": "Ivrit Turbo", "he": "Ivrit Turbo"},
        "description": {"en": "Hebrew-tuned, fast and accurate (recommended)",
                        "he": "מותאם לעברית, מהיר ומדויק (מומלץ)"},
        "pros": [
            {"en": "✓ Trained specifically on Hebrew speech", "he": "✓ אומן במיוחד על דיבור בעברית"},
            {"en": "✓ Far fewer misheard Hebrew words than any model above",
             "he": "✓ הרבה פחות מילים שגויות בעברית מכל מודל שמעליו"},
            {"en": "✓ Turbo decoder: faster than Medium despite being larger",
             "he": "✓ מפענח Turbo: מהיר מ-Medium למרות שהוא גדול יותר"},
            {"en": "✓ Best choice for Hebrew content", "he": "✓ הבחירה הטובה ביותר לתוכן בעברית"},
        ],
        "cons": [
            {"en": "✗ One-time 1.6 GB download on first use",
             "he": "✗ הורדה חד-פעמית של 1.6 GB בשימוש הראשון"},
            {"en": "✗ Requires 3 GB RAM", "he": "✗ דורש 3 GB זיכרון"},
            {"en": "✗ Hebrew only - weaker on other languages than Large",
             "he": "✗ עברית בלבד - חלש יותר משפות אחרות מ-Large"},
        ],
        "time_estimate": {"en": "~8-12 hours", "he": "כ-8-12 שעות"},
        "best_for": {"en": "Hebrew transcription (RECOMMENDED)", "he": "תמלול בעברית (מומלץ)"},
    },
    "ivrit-large": {
        "name": {"en": "Ivrit Large", "he": "Ivrit Large"},
        "description": {"en": "Hebrew-tuned, highest accuracy, slow",
                        "he": "מותאם לעברית, הדיוק הגבוה ביותר, איטי"},
        "pros": [
            {"en": "✓ Most accurate Hebrew option available",
             "he": "✓ האפשרות המדויקת ביותר לעברית"},
            {"en": "✓ Best for critical or hard-to-hear recordings",
             "he": "✓ הטוב ביותר להקלטות קריטיות או קשות לשמיעה"},
        ],
        "cons": [
            {"en": "✗ One-time 3.1 GB download on first use",
             "he": "✗ הורדה חד-פעמית של 3.1 GB בשימוש הראשון"},
            {"en": "✗ Very slow (40+ hours)", "he": "✗ איטי מאוד (מעל 40 שעות)"},
            {"en": "✗ High RAM requirement (8 GB)", "he": "✗ דרישת זיכרון גבוהה (8 GB)"},
            {"en": "✗ Rarely worth it over Ivrit Turbo", "he": "✗ לרוב לא שווה את זה לעומת Ivrit Turbo"},
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


def layout_direction():
    """Qt layout direction matching the current UI language."""
    from PyQt5.QtCore import Qt
    return Qt.RightToLeft if is_rtl() else Qt.LeftToRight


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def load_saved_language() -> str:
    """Read the persisted language choice; English on first-ever launch."""
    lang = str(_settings().value(_SETTINGS_KEY, "en"))
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def apply_saved_language(app) -> None:
    """
    Bootstrap the persisted UI language onto a fresh QApplication, before
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


def t(key: str, **fmt) -> str:
    """
    Translate a key in the current language, applying str.format params.
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


def document_strings() -> dict:
    """
    Every string the generated transcript page needs, in the current language.

    Returned with the "doc_" prefix stripped, because the keys the renderer
    and the page script (core/assets/js/) look up are the bare names - the prefix only exists to
    keep this group identifiable in STRINGS.

    Placeholders are left unsubstituted on purpose: "Play from {t}" is filled
    in per turn by the renderer, which knows the timestamp.
    """
    return {
        key[len(_DOC_PREFIX):]: t(key)
        for key in STRINGS
        if key.startswith(_DOC_PREFIX)
    }


def model_text(model: str, field: str, index: int = None) -> str:
    """Translated text for a config.MODELS-derived field (e.g. card description)."""
    entry = MODEL_STRINGS[model][field]
    if index is not None:
        entry = entry[index]
    return entry.get(_current_lang) or entry["en"]
