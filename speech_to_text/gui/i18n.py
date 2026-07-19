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

    # --- Step 1: file selection ---
    "specs_title": {"en": "Specs", "he": "מפרט מערכת"},
    "select_audio_file": {"en": "Select Audio File", "he": "בחירת קובץ אודיו"},
    "drop_main": {"en": "Drag your audio or video file here", "he": "גררו לכאן קובץ אודיו או וידאו"},
    "drop_formats": {"en": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV", "he": "MP3, WAV, M4A, FLAC, OGG, MP4, MKV"},
    "drop_alt": {"en": "or click anywhere here to browse", "he": "או לחצו כאן כדי לבחור קובץ"},
    "no_file_selected": {"en": "No file selected", "he": "לא נבחר קובץ"},
    "file_info": {
        "en": "{filename} | {minutes}m {seconds}s | {size} MB",
        "he": _RLM + "{filename} | {minutes} דק' {seconds} שנ' | {size} MB",
    },
    "file_dialog_title": {"en": "Select File", "he": "בחירת קובץ"},
    "file_dialog_filter": {"en": "Audio/Video Files", "he": "קובצי אודיו/וידאו"},
    "hw_cpu_cores": {"en": "CPU CORES", "he": "ליבות מעבד"},
    "hw_ram": {"en": "RAM", "he": "זיכרון RAM"},
    "hw_gpu": {"en": "GPU", "he": "כרטיס מסך"},
    "hw_no_gpu": {"en": "No GPU", "he": "ללא GPU"},

    # --- Step 2: model selection ---
    "choose_model": {"en": "Choose Model", "he": "בחירת מודל"},
    "recommended_badge": {"en": "RECOMMENDED", "he": "מומלץ"},
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
        "description": {"en": "High accuracy, recommended default", "he": "דיוק גבוה, ברירת המחדל המומלצת"},
        "pros": [
            {"en": "✓ High accuracy for Hebrew (recommended!)", "he": "✓ דיוק גבוה לעברית (מומלץ!)"},
            {"en": "✓ Professional quality results", "he": "✓ תוצאות באיכות מקצועית"},
            {"en": "✓ Good balance of quality/time", "he": "✓ איזון טוב בין איכות לזמן"},
            {"en": "✓ Best choice for most users", "he": "✓ הבחירה הטובה ביותר לרוב המשתמשים"},
        ],
        "cons": [
            {"en": "✗ Longer processing (~20-24 hours)", "he": "✗ עיבוד ממושך (כ-20-24 שעות)"},
            {"en": "✗ Requires 5 GB RAM", "he": "✗ דורש 5 GB זיכרון"},
            {"en": "✗ Not for immediate results", "he": "✗ לא לתוצאות מיידיות"},
        ],
        "time_estimate": {"en": "~20-24 hours", "he": "כ-20-24 שעות"},
        "best_for": {"en": "Professional quality (RECOMMENDED)", "he": "איכות מקצועית (מומלץ)"},
    },
    "large": {
        "name": {"en": "Large", "he": "Large"},
        "description": {"en": "Highest accuracy, very slow", "he": "הדיוק הגבוה ביותר, איטי מאוד"},
        "pros": [
            {"en": "✓ Highest accuracy possible", "he": "✓ הדיוק הגבוה ביותר האפשרי"},
            {"en": "✓ Best for critical/important content", "he": "✓ הטוב ביותר לתוכן חשוב וקריטי"},
            {"en": "✓ Excellent Hebrew support", "he": "✓ תמיכה מצוינת בעברית"},
            {"en": "✓ Fewest errors", "he": "✓ הכי מעט שגיאות"},
        ],
        "cons": [
            {"en": "✗ Very slow (40+ hours)", "he": "✗ איטי מאוד (מעל 40 שעות)"},
            {"en": "✗ High RAM requirement (8 GB)", "he": "✗ דרישת זיכרון גבוהה (8 GB)"},
            {"en": "✗ May run out of memory on limited systems", "he": "✗ הזיכרון עלול להיגמר במערכות מוגבלות"},
            {"en": "✗ Not practical for most users", "he": "✗ לא מעשי לרוב המשתמשים"},
        ],
        "time_estimate": {"en": "~40+ hours", "he": "מעל כ-40 שעות"},
        "best_for": {"en": "Highest quality, critical content", "he": "האיכות הגבוהה ביותר, תוכן קריטי"},
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


def model_text(model: str, field: str, index: int = None) -> str:
    """Translated text for a config.MODELS-derived field (e.g. card description)."""
    entry = MODEL_STRINGS[model][field]
    if index is not None:
        entry = entry[index]
    return entry.get(_current_lang) or entry["en"]
