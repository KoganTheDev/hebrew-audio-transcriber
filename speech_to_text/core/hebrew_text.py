"""
Shared Hebrew text handling.

Both the correction pass (core/hebrew_correct.py) and the evaluation metrics
(tests/eval/hebrew_metrics.py) need to decide when two spellings are "the same
word". They had grown their own copies of that logic, which is exactly the kind
of duplication that drifts: a normalisation rule fixed in one place and not the
other silently changes what a word error rate means relative to what the
corrector actually does.

Stdlib only - imported by the worker process.
"""

import re
import unicodedata

# Final (sofit) letters are positional variants, not distinct letters. A model
# writing מ where ם belongs has not misheard anything.
FINAL_FORMS = {
    "ך": "כ",
    "ם": "מ",
    "ן": "נ",
    "ף": "פ",
    "ץ": "צ",
}

# Hebrew points and cantillation marks (U+0591-U+05C7). Optional diacritics
# that carry no information about which word was recognised.
NIKUD = re.compile(r"[֑-ׇ]")

# Stackable one-letter prefixes: and/in/like/to/from/that/the.
CLITICS = "ובכלמשה"

# Bidi control characters. Layout, not content - core/formatting.py adds some
# of these deliberately when rendering timestamps into RTL text.
BIDI_CONTROLS = re.compile(r"[‎‏⁦-⁩‪-‮]")

# ---------------------------------------------------------------------------
# RTL isolation for Hebrew text logged into an otherwise-LTR line
# ---------------------------------------------------------------------------
# main.py's LOG_FORMAT puts %(message)s last, after fields that are always
# LTR (timestamp, level, logger name, file:line). When the message itself is
# Hebrew, that makes the Hebrew a right-to-left run trailing an LTR
# paragraph with nothing marking where the neutral run stops. A neutral
# character sitting right after the Hebrew - the trailing comma
# faster-whisper leaves on a truncated segment, for example - has no strong
# direction of its own, so the bidi algorithm resolves it from context, and
# it can render *before* the Hebrew instead of after it: "Segment 26: ,נין"
# instead of "Segment 26: ...נין,".
#
# core/formatting/timecode.py documents the mirror-image problem - an LTR
# timestamp range embedded inside RTL transcript text - and fixes it with an
# LRI/PDI pair. This is the same fix run the other way: an RTL run embedded
# inside LTR text.
#
#   RLI ... PDI  (U+2067 / U+2069) - Right-to-Left Isolate. Forces the
#       enclosed run to lay out RTL *and* isolates it, so a neutral
#       character immediately outside the pair resolves against the LTR
#       paragraph it actually sits in, not against the Hebrew inside it.
#
# Defined here instead of importing timecode.py's LRI/PDI: this module is
# already the stdlib-only home for Hebrew-text handling shared across the
# corrector and the eval metrics, and it is imported into the transcription
# worker process regardless. Reaching into core/formatting for two control
# characters would pull that package's __init__ (assets, chrome, document,
# turns) into the worker for no reason connected to what it is doing there -
# building transcript output, not logging a debug line - even on paths that
# never call format_range() at all.
RLI = "⁧"
PDI = "⁩"

# Detects any Hebrew-block character (letters, points, punctuation). Used to
# skip the isolate on text that has none - wrapping "(empty)" or a stray
# ASCII line in invisible control characters would only add noise for
# anyone grepping speech_to_text.log.
_HAS_HEBREW = re.compile(r"[֐-׿]")


def isolate_rtl(text: str) -> str:
    """
    Wrap text in an RTL isolate (RLI...PDI) if it contains Hebrew.

    Meant for interpolating raw Hebrew text into an otherwise-LTR line, such
    as a log message - see the module comment above for why the isolate is
    needed and why it lives here rather than in core/formatting.
    """
    if not text or not _HAS_HEBREW.search(text):
        return text
    return f"{RLI}{text}{PDI}"


def strip_nikud(text: str) -> str:
    return NIKUD.sub("", unicodedata.normalize("NFC", text))


def collapse_finals(text: str) -> str:
    for final, base in FINAL_FORMS.items():
        text = text.replace(final, base)
    return text


def normalize_word(word: str) -> str:
    """Reduce a word to the form used for comparing spellings."""
    return collapse_finals(strip_nikud(word))
