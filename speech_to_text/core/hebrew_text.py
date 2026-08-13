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


def strip_nikud(text: str) -> str:
    return NIKUD.sub("", unicodedata.normalize("NFC", text))


def collapse_finals(text: str) -> str:
    for final, base in FINAL_FORMS.items():
        text = text.replace(final, base)
    return text


def normalize_word(word: str) -> str:
    """Reduce a word to the form used for comparing spellings."""
    return collapse_finals(strip_nikud(word))
