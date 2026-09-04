"""
Hebrew-aware text normalisation and error rates.

Comparing Hebrew transcripts naively over-reports errors: nikud is optional and
inconsistently produced, final letters are positional variants of the same
letter, and punctuation placement in RTL text is unreliable. None of those are
recognition mistakes, so normalising them away is what makes a word error rate
mean "the model heard the wrong word" rather than "the model typed it
differently".
"""

import re

from speech_to_text.core.hebrew_text import BIDI_CONTROLS, normalize_word

# Geresh/gershayim used in acronyms and loanwords, plus ASCII quotes that
# transcription models place inconsistently.
_PUNCTUATION = re.compile(r"[.,!?;:\"'׳״()\[\]{}\-–—…]")

# "[0:01:23]" as written by core.formatting, with or without its bidi isolates.
_TIMESTAMP = re.compile(r"[⁦⁩]*\[\d{1,2}:\d{2}:\d{2}\][⁦⁩]*")

# "דובר 1:" / "Speaker 1:" at the start of a line.
_SPEAKER_LABEL = re.compile(r"(?m)^\s*(?:דובר|Speaker)\s*\d+\s*:")


def normalize(text: str) -> str:
    """Reduce Hebrew text to what a word error rate should actually compare."""
    # Drop our own rendering furniture first. A reference transcript is often
    # just a corrected copy of a saved run, so it arrives with timestamps and
    # speaker labels attached. Stripping punctuation alone would leave the
    # digits behind as bogus "words" and inflate the error rate.
    text = _TIMESTAMP.sub(" ", text)
    text = _SPEAKER_LABEL.sub(" ", text)
    text = _PUNCTUATION.sub(" ", text)
    # Nikud and final-form handling is shared with the correction pass, so the
    # two cannot drift apart on what counts as the same word.
    text = normalize_word(text)
    text = BIDI_CONTROLS.sub("", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    """Levenshtein distance over sequences, O(len(reference)) memory."""
    if not reference:
        return len(hypothesis)
    previous = list(range(len(reference) + 1))
    for i, hyp in enumerate(hypothesis, start=1):
        current = [i]
        for j, ref in enumerate(reference, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ref != hyp),  # substitution
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = tokens(reference)
    if not ref:
        return float("nan")
    return edit_distance(ref, tokens(hypothesis)) / len(ref)


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref = list(normalize(reference).replace(" ", ""))
    if not ref:
        return float("nan")
    hyp = list(normalize(hypothesis).replace(" ", ""))
    return edit_distance(ref, hyp) / len(ref)
