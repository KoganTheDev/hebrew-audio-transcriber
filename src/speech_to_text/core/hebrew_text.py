"""Shared Hebrew text handling.

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

# Bidi control characters. Layout, not content - core/formatting adds some
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
    """Wrap text in an RTL isolate (RLI...PDI) if it contains Hebrew.

    Meant for interpolating raw Hebrew text into an otherwise-LTR line, such
    as a log message - see the module comment above for why the isolate is
    needed and why it lives here rather than in core/formatting.
    """
    if not text or not _HAS_HEBREW.search(text):
        return text
    return f"{RLI}{text}{PDI}"


# ---------------------------------------------------------------------------
# Visual-order reordering for console output
# ---------------------------------------------------------------------------
# isolate_rtl() fixes speech_to_text.log because every real bidi-aware
# reader (VS Code, Notepad, a browser) implements the Unicode Bidirectional
# Algorithm and does the reordering itself off the RLI/PDI markers. No
# Windows console host does - not conhost.exe, not Windows Terminal
# (microsoft/terminal#538, open since 2019) - so those same markers draw as
# nothing and the console prints logical order, which for Hebrew is
# backwards. There is no markup fix for a renderer that does no reordering
# at all; the reordering has to happen on our side before the bytes reach
# it. to_visual_order() is that reordering, scoped to what LOG_FORMAT
# actually needs: a single line with an LTR paragraph base (timestamp,
# level, logger name and file:line always precede %(message)s) and short,
# single-direction previews rather than arbitrary bidi documents.
# Deliberately a subset of the full UBA - if a log line ever needs more of
# it, get_display() from python-bidi is a drop-in replacement for the body
# below.
MIRROR_PAIRS = {
    "(": ")",
    ")": "(",
    "[": "]",
    "]": "[",
    "{": "}",
    "}": "{",
    "<": ">",
    ">": "<",
    "«": "»",
    "»": "«",
    "‹": "›",
    "›": "‹",
}

_ISOLATE_SPAN = re.compile(f"{RLI}(.*?){PDI}", re.DOTALL)


def _bidi_class(ch: str) -> str:
    """Collapse unicodedata's bidi categories to the three that drive run
    detection: strong RTL, strong LTR, everything else neutral. This
    deliberately puts digits (EN/AN) in the neutral bucket - they only
    start counting as "keep reading left to right" once already inside an
    RTL run, which _reverse_run handles separately.
    """
    category = unicodedata.bidirectional(ch)
    if category in ("R", "AL"):
        return "R"
    if category == "L":
        return "L"
    return "N"


def _is_ltr_or_digit(ch: str) -> bool:
    return unicodedata.bidirectional(ch) in ("L", "EN", "AN")


def _find_rtl_runs(text):
    """Locate maximal RTL runs in `text` under an LTR paragraph - UBA rules
    N1/N2: a neutral run flanked by strong RTL on both sides resolves to
    RTL, but a neutral run touching LTR text or a line boundary resolves to
    the paragraph direction (LTR here) instead and is left where it is.
    Returns a list of (start, end) half-open index spans into `text`.
    """
    classes = [_bidi_class(ch) for ch in text]
    n = len(classes)
    included = [c == "R" for c in classes]

    i = 0
    while i < n:
        if classes[i] != "N":
            i += 1
            continue
        j = i
        while j < n and classes[j] == "N":
            j += 1
        if i > 0 and classes[i - 1] == "R" and j < n and classes[j] == "R":
            for k in range(i, j):
                included[k] = True
        i = j

    runs = []
    i = 0
    while i < n:
        if not included[i]:
            i += 1
            continue
        j = i
        while j < n and included[j]:
            j += 1
        runs.append((i, j))
        i = j
    return runs


def _reverse_run(run_text: str) -> str:
    """Reverse one RTL run into visual order. Embedded Latin words and numbers
    (strong-LTR or digit characters, contiguous) are re-reversed after the
    whole-run reversal so they still read left-to-right at their mirrored
    position, and paired punctuation is swapped via MIRROR_PAIRS - Python's
    unicodedata exposes bidirectional *category* and a mirrored() yes/no
    flag, but no mirror *mapping*, hence the explicit table.
    """
    chars = list(run_text)
    keep_order = [_is_ltr_or_digit(ch) for ch in chars]
    chars.reverse()
    keep_order.reverse()

    n = len(chars)
    i = 0
    while i < n:
        if keep_order[i]:
            j = i
            while j < n and keep_order[j]:
                j += 1
            chars[i:j] = reversed(chars[i:j])
            i = j
        else:
            i += 1

    for idx, ch in enumerate(chars):
        if unicodedata.mirrored(ch) and ch in MIRROR_PAIRS:
            chars[idx] = MIRROR_PAIRS[ch]
    return "".join(chars)


def _reorder_plain(chunk: str) -> str:
    """Run-detect and reverse text that sits outside any RLI...PDI span."""
    if not chunk:
        return chunk
    pieces = []
    last = 0
    for start, end in _find_rtl_runs(chunk):
        pieces.append(chunk[last:start])
        pieces.append(_reverse_run(chunk[start:end]))
        last = end
    pieces.append(chunk[last:])
    return "".join(pieces)


def to_visual_order(text: str) -> str:
    """Reorder one logical-order log line into the visual order a plain,
    non-bidi console needs - see the module comment above for why this is
    necessary at all. Honours isolate_rtl()'s RLI...PDI spans as whole RTL
    runs first: that is the point of isolating rather than stripping - the
    isolate already records that a trailing neutral (the comma
    faster-whisper leaves on a truncated segment, say) belongs inside the
    Hebrew run. Any further RTL runs in the rest of the line are found the
    same way isolate_rtl's output would have been found by a real UBA
    implementation. Bidi control characters are stripped at the end -
    invisible-or-garbage on a non-bidi console and meaningless once the
    text is already in visual order.

    Text with no strong-RTL character and no isolate span comes back
    unchanged (the same object) - the common case, and it must not pay for
    a reorder it doesn't need.
    """
    if not text:
        return text
    if not _ISOLATE_SPAN.search(text) and all(_bidi_class(ch) != "R" for ch in text):
        return text

    out = []
    pos = 0
    for match in _ISOLATE_SPAN.finditer(text):
        out.append(_reorder_plain(text[pos : match.start()]))
        out.append(_reverse_run(match.group(1)))
        pos = match.end()
    out.append(_reorder_plain(text[pos:]))

    return BIDI_CONTROLS.sub("", "".join(out))


def strip_nikud(text: str) -> str:
    return NIKUD.sub("", unicodedata.normalize("NFC", text))


def collapse_finals(text: str) -> str:
    for final, base in FINAL_FORMS.items():
        text = text.replace(final, base)
    return text


def normalize_word(word: str) -> str:
    """Reduce a word to the form used for comparing spellings."""
    return collapse_finals(strip_nikud(word))
