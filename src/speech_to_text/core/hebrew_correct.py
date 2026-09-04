"""Targeted correction of misrecognised Hebrew words.

The obvious version of this idea - look up every word in a Hebrew dictionary
and replace anything unknown with its nearest neighbour - makes transcripts
worse, for two reasons specific to the language:

1. Morphology defeats the "is this a word?" test. Hebrew stacks prefix clitics
   (ו ב כ ל מ ש ה, and combinations of them) and attaches possessive and plural
   suffixes, so one lemma has dozens of surface forms. Any plain word list
   marks a large share of perfectly correct words as unknown, and a
   dictionary-driven pass then spends most of its effort "fixing" text that was
   already right.

2. Edit-distance neighbours in Hebrew are usually other real words. Unvocalised
   Hebrew is dense: חתם / חתן / חתך are mutually distance 1 and all valid. So
   nearest-neighbour matching against a general dictionary has a genuinely high
   chance of replacing a correct word with an incorrect one.

This module therefore does something narrower, which is where the actual wins
are anyway:

* It only looks at words the model itself flagged as uncertain, using the
  per-word probabilities that word_timestamps=True provides. Words Whisper was
  confident about are never touched.
* It matches against a curated term list supplied by the user - names, places,
  organisations, jargon - not a dictionary. These are precisely the words a
  general model gets wrong and a dictionary cannot help with. No list means
  this pass does nothing at all.
* Distance is phonetically weighted rather than plain Levenshtein, because the
  substitutions Whisper actually makes in Hebrew are the ones that sound alike.
* A replacement happens only when one candidate is clearly better than the
  runner-up, so ambiguous cases are left alone.

Set expectations accordingly: this fixes proper nouns and domain vocabulary. It
does not fix general Hebrew misrecognition - only a better model does that.
"""

import logging
import os
import re
from collections.abc import Iterator, Sequence
from typing import Optional

from speech_to_text.core.hebrew_text import CLITICS, normalize_word
from speech_to_text.core.segments import Segment, Word

logger = logging.getLogger(__name__)

# Only words the model scored below this are candidates. This gate is what
# makes the pass safe rather than reckless: it is the difference between
# "correct what the model doubted" and "second-guess the whole transcript".
CONFIDENCE_THRESHOLD = 0.55

# Maximum weighted distance, as a fraction of the term's length, for a match to
# count. Deliberately tight - most low-confidence words are not domain terms at
# all and must be left alone.
MAX_RELATIVE_DISTANCE = 0.34

# The best candidate must beat the runner-up by this much (in weighted edit
# cost) to be applied. Without this, two similar terms would make the choice a
# coin flip, and a coin flip on someone's name is worse than leaving the
# model's guess in place.
MIN_MARGIN = 0.5

# Hebrew letters that are routinely confused because they sound identical or
# near-identical in modern pronunciation. Cost below 1.0 means "these two being
# different is weak evidence that this is a different word".
#
# א/ה/ע are silent or near-silent; כ/ק and ט/ת and ס/שׂ are homophones; ב/ו
# overlap on the /v/ sound. These are the substitutions an ASR model actually
# makes, which plain Levenshtein weights the same as any other letter swap.
_CONFUSION_GROUPS: Sequence[tuple[str, float]] = (
    ("אהע", 0.25),
    ("כק", 0.25),
    ("טת", 0.25),
    ("סשצ", 0.35),
    ("בו", 0.35),
    ("יא", 0.4),
    ("גז", 0.5),
)

_HEBREW_WORD = re.compile(r"^[א-ת]+$")

_SUBSTITUTION_COST: dict[tuple[str, str], float] = {}
for _group, _cost in _CONFUSION_GROUPS:
    for _a in _group:
        for _b in _group:
            if _a != _b:
                _SUBSTITUTION_COST.setdefault((_a, _b), _cost)


def strip_clitics(word: str) -> tuple[str, str]:
    """Split leading prefix letters off a word.

    Returns (prefix, stem). A letter is only stripped if at least four letters
    remain afterwards: below that the "prefix" is far more likely to be part of
    the word itself, and stripping the ש from שלום would be actively harmful.

    Note this is a guess, not an analysis - Hebrew has no way to tell a clitic
    from a stem letter without a morphological lexicon. best_match therefore
    tries the unstripped word as well and keeps whichever matches better.
    """
    index = 0
    while index < len(word) and word[index] in CLITICS and len(word) - index > 4:
        index += 1
    return word[:index], word[index:]


def clitic_splits(word: str) -> list[tuple[str, str]]:
    """Every plausible way to divide a word into prefix + stem.

    Returns [("", word), (word[:1], word[1:]), ...] up to the maximum strip.

    Splitting greedily at the longest run of prefix letters is not enough,
    because prefix letters also occur as ordinary first letters of words.
    בכיסריה is "ב" + the misheard "כיסריה", but a greedy strip reads it as
    "בכ" + "יסריה" and never finds קיסריה. Trying each split point costs at
    most a handful of extra comparisons and removes the guesswork.
    """
    _, stem = strip_clitics(word)
    max_strip = len(word) - len(stem)
    return [(word[:i], word[i:]) for i in range(max_strip + 1)]


def weighted_distance(a: str, b: str, cutoff: Optional[float] = None) -> float:
    """Levenshtein distance with Hebrew-aware substitution costs.

    Insertions and deletions cost 1.0; substitutions cost less when the two
    letters are commonly confused. `cutoff` allows early exit once every cell
    in a row already exceeds it, which matters when scanning a long term list.
    """
    if a == b:
        return 0.0
    if not a:
        return float(len(b))
    if not b:
        return float(len(a))

    previous = [float(i) for i in range(len(a) + 1)]
    for i, char_b in enumerate(b, start=1):
        current = [float(i)]
        for j, char_a in enumerate(a, start=1):
            substitution = (
                0.0 if char_a == char_b else _SUBSTITUTION_COST.get((char_a, char_b), 1.0)
            )
            current.append(
                min(
                    previous[j] + 1.0,
                    current[j - 1] + 1.0,
                    previous[j - 1] + substitution,
                )
            )
        if cutoff is not None and min(current) > cutoff:
            return cutoff + 1.0
        previous = current
    return previous[-1]


class TermList:
    """The user's domain vocabulary, indexed for matching."""

    def __init__(self, terms: Sequence[str]):
        # Keep the original spelling for output, key on the normalized form for
        # comparison.
        self.terms = [t.strip() for t in terms if t.strip()]
        self._normalized = [(normalize_word(t), t) for t in self.terms]

    def __len__(self) -> int:
        return len(self.terms)

    @classmethod
    def load(cls, path: str) -> "TermList":
        """Read a term list, one entry per line. Missing file means an empty list,
        which makes the whole correction pass a no-op - the intended default.
        """
        if not os.path.exists(path):
            logger.debug(f"No Hebrew term list at {path}; correction disabled")
            return cls([])
        try:
            with open(path, encoding="utf-8") as handle:
                lines = [
                    line for line in handle if line.strip() and not line.lstrip().startswith("#")
                ]
            terms = cls(lines)
            logger.info(f"Loaded {len(terms)} Hebrew correction term(s) from {path}")
            return terms
        except Exception as e:
            logger.warning(f"Could not read term list {path}: {e}")
            return cls([])

    def _near_matches(self, prefix: str, candidate: str) -> Iterator[tuple[str, float]]:
        """Yield (replacement, distance) for each term close enough to `candidate`.

        `prefix` is the clitic run that was stripped off the front; it is put
        back on the term so a replacement keeps the original word's grammar.
        """
        for normalized_term, original_term in self._normalized:
            # Length gate first: far cheaper than the distance itself, and
            # it discards most of the list.
            if abs(len(normalized_term) - len(candidate)) > 2:
                continue
            limit = MAX_RELATIVE_DISTANCE * max(len(normalized_term), len(candidate))
            distance = weighted_distance(candidate, normalized_term, cutoff=limit)
            if distance > limit:
                continue
            yield prefix + original_term, distance

    def _rank(self, word: str) -> tuple[Optional[tuple[str, float]], float]:
        """Score every reading of `word` and return (best, runner-up distance).

        best is (replacement, distance), or None when nothing was close enough.
        A further match producing the *same* replacement text does not count as
        a runner-up: two readings agreeing on an answer is confirmation, not
        ambiguity.
        """
        # Every prefix reading is tried, because Hebrew gives no way to tell a
        # clitic from a stem letter that happens to be one: קיסריה begins with
        # ק, but כיסריה - the very misrecognition we want to fix - begins with
        # כ, which is also a prefix. Whichever reading matches a term best wins.
        best: Optional[tuple[str, float]] = None
        runner_up = float("inf")

        for candidate_prefix, candidate in clitic_splits(normalize_word(word)):
            if len(candidate) < 2:
                continue
            for replacement, distance in self._near_matches(candidate_prefix, candidate):
                if best is None or distance < best[1]:
                    if best is not None and best[0] != replacement:
                        runner_up = best[1]
                    best = (replacement, distance)
                elif distance < runner_up and best[0] != replacement:
                    runner_up = distance

        return best, runner_up

    def best_match(self, word: str) -> Optional[tuple[str, float, float]]:
        """Find the term this word was most likely meant to be.

        Returns (term, distance, margin) or None when nothing is close enough
        or the choice is ambiguous.
        """
        if not self._normalized:
            return None

        best, runner_up = self._rank(word)
        if best is None:
            return None

        margin = runner_up - best[1]
        if margin < MIN_MARGIN:
            return None

        return best[0], best[1], margin


def _correction_for(
    word: Word, terms: TermList, confidence_threshold: float
) -> Optional[tuple[str, str]]:
    """Decide what one word should be replaced with, or None to leave it alone.

    Returns (original, replacement) with the surrounding whitespace stripped -
    the caller puts it back. Logs the accepted replacement here, where the
    distance and margin that justified it are still in scope.
    """
    if word.probability >= confidence_threshold:
        return None

    bare = word.text.strip()
    if not _HEBREW_WORD.match(normalize_word(bare)):
        return None

    match = terms.best_match(bare)
    if match is None:
        return None

    replacement, distance, margin = match
    if replacement == bare:
        return None

    logger.info(
        f"Hebrew correction: {bare!r} -> {replacement!r} "
        f"(confidence {word.probability:.2f}, distance {distance:.2f}, "
        f"margin {margin:.2f})"
    )
    return bare, replacement


def correct(
    segments: Sequence[Segment],
    terms: TermList,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Correct low-confidence words against the term list, in place.

    Returns the list of (original, replacement, confidence) substitutions made,
    which the caller logs. Every change being auditable is not optional here:
    without a record of what it did, a pass like this is unfalsifiable and its
    thresholds cannot be tuned against real audio.
    """
    if not len(terms):
        return []

    changes: list[tuple[str, str, float]] = []

    for segment in segments:
        if not segment.words:
            continue

        replacements: dict[int, str] = {}
        for index, word in enumerate(segment.words):
            correction = _correction_for(word, terms, confidence_threshold)
            if correction is None:
                continue
            bare, replacement = correction

            # Whitespace is attached to words by faster-whisper; keep it so the
            # rebuilt segment text spaces correctly.
            leading = word.text[: len(word.text) - len(word.text.lstrip())]
            trailing = word.text[len(word.text.rstrip()) :]

            replacements[index] = leading + replacement + trailing
            changes.append((bare, replacement, word.probability))

        if not replacements:
            continue

        for index, new_text in replacements.items():
            segment.words[index].text = new_text
        segment.text = "".join(word.text for word in segment.words)

    return changes
