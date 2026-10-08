"""Targeted correction of misrecognised Hebrew words.

The obvious version - look every word up in a Hebrew dictionary and replace
anything unknown with its nearest neighbour - makes transcripts worse, for two
reasons specific to the language:

1. Morphology defeats the "is this a word?" test. Hebrew stacks prefix clitics
   (ו ב כ ל מ ש ה, and combinations) and attaches possessive and plural
   suffixes, so one lemma has dozens of surface forms and any plain word list
   marks a large share of correct words as unknown.

2. Edit-distance neighbours in Hebrew are usually other real words.
   Unvocalised Hebrew is dense: חתם / חתן / חתך are mutually distance 1 and
   all valid, so nearest-neighbour matching has a high chance of replacing a
   correct word with an incorrect one.

Hence something narrower, which is where the wins are anyway:

* Only words the model itself flagged as uncertain, via the per-word
  probabilities word_timestamps=True provides. Confident words are untouched.
* Matched against a curated term list from the user - names, places,
  organisations, jargon - not a dictionary. These are exactly the words a
  general model gets wrong and a dictionary cannot help with. No list means
  this pass does nothing at all.
* Distance is phonetically weighted rather than plain Levenshtein, because the
  substitutions Whisper actually makes in Hebrew are the ones that sound alike.
* A replacement happens only when one candidate clearly beats the runner-up.

Set expectations accordingly: this fixes proper nouns and domain vocabulary,
not general Hebrew misrecognition - only a better model does that.
"""

import logging
import os
import re
from collections import Counter
from collections.abc import Iterator, Sequence

from core import term_store
from core.hebrew_text import CLITICS, normalize_word
from core.segments import Segment, Word

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

# A word the model wrote with at least this confidence, at least this many
# times in the same recording, is taken to be a real word it knows - never a
# misheard term. Measured on real calls (tests/eval/compare_term_correction):
# the term ענבל kept "correcting" אבל ("but"), which the same recording held
# 29 times at confidence 1.0. Two sightings, not one, because a misheard
# name can itself come out confident once (ציל for צליל, at 0.96).
KNOWN_WORD_CONFIDENCE = 0.9
KNOWN_WORD_MIN_COUNT = 2

# The transcript page's click-to-fix menu: at most this many terms, and only
# those within this weighted distance of the best one (see suggestions()).
SUGGESTION_LIMIT = 3
SUGGESTION_SPREAD = 1.0

# Letters routinely confused because they sound identical or near-identical in
# modern pronunciation, so a difference between them is weak evidence that this
# is a different word - hence a cost below 1.0. א/ה/ע are silent or
# near-silent; כ/ק, ט/ת and ס/שׂ are homophones; ב/ו overlap on /v/. Plain
# Levenshtein weights these the same as any other letter swap.
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

# Punctuation faster-whisper attaches to a word ("לכיסריה." "יוסי,"), split
# off before matching and put back after. Without this every name at the end
# of a sentence or before a comma failed _HEBREW_WORD and was never looked
# at. Only the edges are touched, so gershayim inside an acronym (צה"ל) stay
# put. Apostrophe and geresh are left out entirely: they can END a word
# (ג'ורג'), and such a word should stay unmatched rather than lose a letter.
_PUNCTUATION_CLASS = r'[.,!?;:"()\[\]{}«»“”„…–—\-־]'
_EDGE_PUNCTUATION = re.compile(rf"^({_PUNCTUATION_CLASS}*)(.*?)({_PUNCTUATION_CLASS}*)$")


def _split_punctuation(text: str) -> tuple[str, str, str]:
    """(leading punctuation, word, trailing punctuation)."""
    match = _EDGE_PUNCTUATION.match(text)
    if match is None:  # unreachable - every group can be empty - but typed
        return "", text, ""
    lead, core, trail = match.groups()
    return lead, core, trail


_SUBSTITUTION_COST: dict[tuple[str, str], float] = {}
for _group, _cost in _CONFUSION_GROUPS:
    for _a in _group:
        for _b in _group:
            if _a != _b:
                _SUBSTITUTION_COST.setdefault((_a, _b), _cost)


def strip_clitics(word: str) -> tuple[str, str]:
    """Split leading prefix letters off a word, returning (prefix, stem).

    A letter is only stripped if at least four remain: below that the "prefix"
    is far more likely part of the word itself, and stripping the ש from שלום
    would be actively harmful.

    This is a guess, not an analysis - telling a clitic from a stem letter
    needs a morphological lexicon - so _rank tries the unstripped word too and
    keeps whichever matches better.
    """
    index = 0
    while index < len(word) and word[index] in CLITICS and len(word) - index > 4:
        index += 1
    return word[:index], word[index:]


def clitic_splits(word: str) -> list[tuple[str, str]]:
    """Every plausible way to divide a word into prefix + stem, shortest first.

    Splitting greedily at the longest run of prefix letters is not enough,
    because prefix letters also occur as ordinary first letters of words.
    בכיסריה is "ב" + the misheard "כיסריה", but a greedy strip reads it as
    "בכ" + "יסריה" and never finds קיסריה. Trying each split point costs a
    handful of extra comparisons and removes the guesswork.
    """
    _, stem = strip_clitics(word)
    max_strip = len(word) - len(stem)
    return [(word[:i], word[i:]) for i in range(max_strip + 1)]


def weighted_distance(a: str, b: str, cutoff: float | None = None) -> float:
    """Levenshtein distance with Hebrew-aware substitution costs.

    Insertions and deletions cost 1.0; substitutions cost less for commonly
    confused letters. `cutoff` exits early once every cell in a row exceeds it,
    which matters when scanning a long term list.
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
        self.terms = [" ".join(t.split()) for t in terms if t.strip()]
        self._normalized = [(normalize_word(t), t) for t in self.terms]
        # Multi-word terms again, split and grouped by word count, for
        # best_phrase_match(). Whisper emits one word at a time, so a term
        # like "יובל קוגן" compared whole against single words never matched.
        self._phrases: dict[int, list[tuple[list[str], list[str]]]] = {}
        for normalized, original in self._normalized:
            parts = normalized.split(" ")
            if len(parts) > 1:
                self._phrases.setdefault(len(parts), []).append((parts, original.split(" ")))

    @property
    def phrase_lengths(self) -> list[int]:
        """Word counts of the multi-word terms, longest first."""
        return sorted(self._phrases, reverse=True)

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
            # The same parser the terms dialog writes through, so "what counts
            # as a term line" has one definition.
            terms = cls(term_store.read_terms(path))
            logger.info(f"Loaded {len(terms)} Hebrew correction term(s) from {path}")
            return terms
        except Exception as e:
            logger.warning(f"Could not read term list {path}: {e}")
            return cls([])

    def _near_matches(self, prefix: str, candidate: str) -> Iterator[tuple[str, float]]:
        """Yield (replacement, distance) for each term close enough to
        `candidate`, with `prefix` - the clitic run stripped off the front -
        put back on so the replacement keeps the original word's grammar.
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

    def _rank(self, word: str) -> tuple[tuple[str, float] | None, float]:
        """Score every clitic reading of `word`, returning ((replacement,
        distance) or None, runner-up distance).

        Every reading is tried because Hebrew gives no way to tell a clitic
        from a stem letter that happens to be one: קיסריה begins with ק, but
        כיסריה - the very misrecognition we want to fix - begins with כ, which
        is also a prefix. Whichever reading matches a term best wins.

        A second match producing the *same* replacement text is not a
        runner-up: two readings agreeing is confirmation, not ambiguity.
        """
        best: tuple[str, float] | None = None
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

    def suggestions(self, word: str, limit: int = SUGGESTION_LIMIT) -> list[str]:
        """Terms a person might pick for this word, best first.

        Unlike best_match() there is no margin: a tie is exactly what a
        pick-one menu is for. Two filters instead:
        * one entry per TERM, at its best clitic reading - every reading
          yields its own prefix+term, and a mockup over real output listed
          junk like בכקיסריה beside בקיסריה until this rule;
        * only candidates within SUGGESTION_SPREAD of the best, so a choice
          is between near-ties rather than a long tail.
        Single-word terms only: replacing one word with a phrase would break
        the word timings every other feature of the page reads.
        """
        best: dict[str, tuple[float, str]] = {}
        normalized = normalize_word(word)
        for prefix, candidate in clitic_splits(normalized):
            if len(candidate) < 2:
                continue
            for replacement, distance in self._near_matches(prefix, candidate):
                term = replacement[len(prefix) :]
                if " " in term:
                    continue
                if distance < best.get(term, (float("inf"), ""))[0]:
                    best[term] = (distance, replacement)

        ranked = sorted(best.values())
        if not ranked:
            return []
        cutoff = ranked[0][0] + SUGGESTION_SPREAD
        return [
            replacement
            for distance, replacement in ranked
            if distance <= cutoff and normalize_word(replacement) != normalized
        ][:limit]

    def best_match(self, word: str) -> tuple[str, float, float] | None:
        """Find the term this word was most likely meant to be.

        Returns (term, distance, margin) or None when nothing is close enough
        or the choice is ambiguous.
        """
        if not self._normalized:
            return None

        best, runner_up = self._rank(word)
        return _decisive(best, runner_up)

    def best_phrase_match(
        self, words: Sequence[str], uncertain: Sequence[bool]
    ) -> tuple[list[str], float, float] | None:
        """Find the multi-word term these consecutive words were meant to be.

        Words the model was confident about must equal their part of the term
        exactly; only the uncertain ones may differ, each within the same
        distance limit as a single word. Scoring the window as one string
        instead would let a term spend its distance budget on a confident
        word: "דנה לא" is close enough to a term "דנה לוי" as a string, and
        לא is a common word the model has every right to be unsure of.

        The first word may carry clitics (במכללת בראודה), split off and put
        back as best_match() does. Returns (replacement words, distance,
        margin), or None when nothing qualifies or the choice is ambiguous.
        """
        pool = self._phrases.get(len(words))
        if not pool or not any(uncertain):
            return None

        normalized = [normalize_word(word) for word in words]
        best: tuple[str, float] | None = None
        runner_up = float("inf")
        by_text: dict[str, list[str]] = {}

        for prefix, stem in clitic_splits(normalized[0]):
            if len(stem) < 2:
                continue
            reading = [stem] + normalized[1:]
            for term_parts, original_parts in pool:
                distance = _phrase_distance(reading, term_parts, uncertain)
                if distance is None:
                    continue
                replacement = [prefix + original_parts[0]] + original_parts[1:]
                text = " ".join(replacement)
                by_text[text] = replacement
                if best is None or distance < best[1]:
                    if best is not None and best[0] != text:
                        runner_up = best[1]
                    best = (text, distance)
                elif distance < runner_up and best[0] != text:
                    runner_up = distance

        decided = _decisive(best, runner_up)
        if decided is None:
            return None
        text, distance, margin = decided
        return by_text[text], distance, margin


def _decisive(best: tuple[str, float] | None, runner_up: float) -> tuple[str, float, float] | None:
    """(replacement, distance, margin) when the best candidate clearly wins."""
    if best is None:
        return None
    margin = runner_up - best[1]
    if margin < MIN_MARGIN:
        return None
    return best[0], best[1], margin


def _phrase_distance(
    words: Sequence[str], term: Sequence[str], uncertain: Sequence[bool]
) -> float | None:
    """Summed distance of uncertain words to their term word.

    None if any confident word differs or any uncertain one is out of range.
    """
    total = 0.0
    for word, part, doubted in zip(words, term, uncertain):
        if not doubted:
            if word != part:
                return None
            continue
        limit = MAX_RELATIVE_DISTANCE * max(len(word), len(part))
        distance = weighted_distance(word, part, cutoff=limit)
        if distance > limit:
            return None
        total += distance
    return total


def _correction_for(
    word: Word, terms: TermList, confidence_threshold: float, known: frozenset[str]
) -> tuple[str, str] | None:
    """Decide what one word should be replaced with, or None to leave it alone.

    Returns (original, replacement) with the surrounding whitespace stripped -
    the caller puts it back. Logs the accepted replacement here, where the
    distance and margin that justified it are still in scope.
    """
    if word.probability >= confidence_threshold:
        return None

    bare = word.text.strip()
    lead, core, trail = _split_punctuation(bare)
    if not _HEBREW_WORD.match(normalize_word(core)) or normalize_word(core) in known:
        return None

    match = terms.best_match(core)
    if match is None:
        return None

    replacement, distance, margin = match
    if replacement == core:
        return None

    logger.info(
        f"Hebrew correction: {core!r} -> {replacement!r} "
        f"(confidence {word.probability:.2f}, distance {distance:.2f}, "
        f"margin {margin:.2f})"
    )
    return bare, lead + replacement + trail


def _phrase_correction_for(
    window: Sequence[Word], terms: TermList, confidence_threshold: float, known: frozenset[str]
) -> list[str] | None:
    """What a run of words should become as one multi-word term, or None.

    The same gates as _correction_for: at least one word must be one the
    model doubted, and every word must be plain Hebrew. Logs what it accepts.
    """
    uncertain = [word.probability < confidence_threshold for word in window]
    if not any(uncertain):
        return None

    pieces = [_split_punctuation(word.text.strip()) for word in window]
    # Punctuation may open the phrase or close it, not sit inside it: a comma
    # between two words says they are not one name.
    if any(trail for _lead, _core, trail in pieces[:-1]):
        return None
    if any(lead for lead, _core, _trail in pieces[1:]):
        return None
    cores = [core for _lead, core, _trail in pieces]
    if not all(_HEBREW_WORD.match(normalize_word(core)) for core in cores):
        return None
    if any(doubted and normalize_word(core) in known for core, doubted in zip(cores, uncertain)):
        return None

    match = terms.best_phrase_match(cores, uncertain)
    if match is None:
        return None

    replacement, distance, margin = match
    if replacement == cores:
        return None

    logger.info(
        f"Hebrew correction: {' '.join(cores)!r} -> {' '.join(replacement)!r} "
        f"(confidence {min(word.probability for word in window):.2f}, "
        f"distance {distance:.2f}, margin {margin:.2f})"
    )
    replacement = list(replacement)
    replacement[0] = pieces[0][0] + replacement[0]
    replacement[-1] = replacement[-1] + pieces[-1][2]
    return replacement


def _keep_spacing(original: str, replacement: str) -> str:
    """The replacement with the original word's surrounding whitespace.

    Whitespace is attached to words by faster-whisper; keeping it is what
    makes the rebuilt segment text space correctly.
    """
    leading = original[: len(original) - len(original.lstrip())]
    trailing = original[len(original.rstrip()) :]
    return leading + replacement + trailing


def correct(
    segments: Sequence[Segment],
    terms: TermList,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Correct low-confidence words against the term list, in place.

    Returns the (original, replacement, confidence) substitutions made, which
    the caller logs. Auditability is not optional here: without a record of
    what it did, a pass like this is unfalsifiable and its thresholds cannot be
    tuned against real audio.
    """
    if not len(terms):
        return []

    changes: list[tuple[str, str, float]] = []
    known = _known_words(segments)

    for segment in segments:
        if not segment.words:
            continue

        # Multi-word terms first, so a word a phrase claimed is not then
        # "corrected" again on its own.
        replacements: dict[int, str] = {}
        _correct_phrases(segment.words, terms, confidence_threshold, known, replacements, changes)
        _correct_words(segment.words, terms, confidence_threshold, known, replacements, changes)
        if not replacements:
            continue

        for index, new_text in replacements.items():
            word = segment.words[index]
            # Kept for the transcript page's "restore original" - the one
            # undo a reader has for a correction they did not ask for.
            word.original = word.text.strip()
            word.text = new_text
        segment.text = "".join(word.text for word in segment.words)

    return changes


_Change = tuple[str, str, float]


def annotate_suggestions(
    segments: Sequence[Segment],
    terms: TermList,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> int:
    """Attach click-to-fix suggestions to every doubted word, in place.

    Run after correct(). For a word correct() already replaced, alternatives
    are ranked from what the model actually heard (word.original), minus the
    one applied - "restore original" covers going back. The known-word guard
    applies as it does to correct(): on real recordings a list holding ענבל
    would otherwise prompt "ענבל?" on every doubted אבל ("but").

    Returns how many words received at least one suggestion.
    """
    if not len(terms):
        return 0
    known = _known_words(segments)
    annotated = 0
    for segment in segments:
        for word in segment.words:
            if word.probability >= confidence_threshold:
                continue
            lead, core, trail = _split_punctuation(word.text.strip())
            heard = _split_punctuation(word.original)[1] if word.original else core
            if not _HEBREW_WORD.match(normalize_word(heard)) or normalize_word(heard) in known:
                continue
            options = [s for s in terms.suggestions(heard) if s != core]
            word.suggestions = [lead + option + trail for option in options]
            if word.suggestions:
                annotated += 1
    return annotated


def _known_words(segments: Sequence[Segment]) -> frozenset[str]:
    """Words this recording itself shows the model knows - see KNOWN_WORD_*."""
    counts: Counter[str] = Counter()
    for segment in segments:
        for word in segment.words:
            if word.probability >= KNOWN_WORD_CONFIDENCE:
                counts[normalize_word(_split_punctuation(word.text.strip())[1])] += 1
    return frozenset(word for word, n in counts.items() if n >= KNOWN_WORD_MIN_COUNT)


def _correct_phrases(
    words: Sequence[Word],
    terms: TermList,
    confidence_threshold: float,
    known: frozenset[str],
    replacements: dict[int, str],
    changes: list[_Change],
) -> None:
    """Record multi-word term fixes, longest terms first, in `replacements`."""
    for size in terms.phrase_lengths:
        for start in range(len(words) - size + 1):
            span = range(start, start + size)
            if any(index in replacements for index in span):
                continue
            window = [words[index] for index in span]
            phrase = _phrase_correction_for(window, terms, confidence_threshold, known)
            if phrase is None:
                continue
            for index, word, new_bare in zip(span, window, phrase):
                replacements[index] = _keep_spacing(word.text, new_bare)
            original = " ".join(word.text.strip() for word in window)
            confidence = min(word.probability for word in window)
            changes.append((original, " ".join(phrase), confidence))


def _correct_words(
    words: Sequence[Word],
    terms: TermList,
    confidence_threshold: float,
    known: frozenset[str],
    replacements: dict[int, str],
    changes: list[_Change],
) -> None:
    """Record single-word fixes for every word no phrase already claimed."""
    for index, word in enumerate(words):
        if index in replacements:
            continue
        correction = _correction_for(word, terms, confidence_threshold, known)
        if correction is None:
            continue
        bare, replacement = correction
        replacements[index] = _keep_spacing(word.text, replacement)
        changes.append((bare, replacement, word.probability))
