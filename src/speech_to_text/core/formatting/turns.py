"""Turn merging: grouping raw Whisper segments into readable speaker turns.

Kept apart from timecode.py and the HTML renderer because it is a distinct
job with its own inputs (Segment/Word) and no knowledge of how a turn ends up
formatted - render_html() and format_plain() both consume Turn objects
without either being able to influence how they were grouped.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from speech_to_text.core.segments import Segment, Word

from .timecode import split_sentences

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Turn merging
# ---------------------------------------------------------------------------
# Whisper emits a segment every few seconds - a decoder-sized unit, not a
# human-sized one. One timestamped line per segment produces a transcript
# that's technically correct and unreadable, so consecutive segments are merged
# into a "turn" until the speaker changes, the pause gets long enough to read as
# a break, or the turn simply grows too long to stay scannable.
TURN_GAP_SECONDS = 2.0
# 60s -> 30s: a 60-second block of unbroken Hebrew is exactly the "wall of
# text with a timestamp buried somewhere in the middle" shape that motivated
# this whole rewrite. Halving the cap keeps every block short enough to
# scan even before the sentence-per-<p> layout gets involved.
TURN_MAX_SECONDS = 30.0


@dataclass
class Sentence:
    """One sentence within a Turn, with its own time span.

    Exists because the bubble layout needs a click target and a playback
    range per sentence, not just per turn - split_sentences() already cuts
    a turn's text into sentences for the <p>-per-sentence body, but a
    string has no timing of its own. `words` carries the slice of the
    turn's Word list this sentence consumed, the same per-word confidence
    data Turn.low_confidence() reads, in case a future caller wants
    per-sentence flags instead of per-turn ones.
    """

    text: str
    start: float
    end: float
    words: List[Word] = field(default_factory=list)


class Turn:
    """One speaker's uninterrupted stretch of speech."""

    def __init__(self, segment: Segment):
        self.start = segment.start
        self.end = segment.end
        self.speaker = segment.speaker
        self._parts = [segment.text.strip()]
        # Per-word confidences are carried through rather than dropped: they
        # are what lets the reader see which words the model itself doubted,
        # which is the difference between proofreading the whole transcript
        # and proofreading the parts that need it. Same data hebrew_correct
        # already uses to decide what it is allowed to touch.
        self.words: List[Word] = list(segment.words or [])

    def append(self, segment: Segment) -> None:
        self.end = segment.end
        text = segment.text.strip()
        if text:
            self._parts.append(text)
        if segment.words:
            self.words.extend(segment.words)

    @property
    def text(self) -> str:
        return " ".join(part for part in self._parts if part)

    def low_confidence(self, threshold: float) -> List[list]:
        """Words the model was unsure about, as [text, probability, occurrence].

        The occurrence index counts how many times that exact token has
        already appeared in this turn, so a word that shows up twice with
        different confidences only gets flagged where it was actually
        uncertain. It is computed over the word list rather than over the
        rendered text; the two agree because the text is built from these
        same segments, and a rare disagreement costs at most a neighbouring
        duplicate being highlighted instead.
        """
        seen: dict = {}
        flagged: List[list] = []

        for word in self.words:
            token = (word.text or "").strip()
            if not token:
                continue
            index = seen.get(token, 0)
            seen[token] = index + 1
            if word.probability < threshold:
                flagged.append([token, round(float(word.probability), 3), index])

        return flagged

    def sentences(self) -> List[Sentence]:
        """Split this turn's text into Sentence objects, each with its own span.

        split_sentences() already produces the text of each sentence; this
        walks self.words in order, consuming words until the collapsed
        (whitespace-stripped) text consumed matches the collapsed sentence
        text's length. word.text carries leading spaces from faster-whisper,
        so comparing lengths after collapsing whitespace is what makes this
        robust to that - matching on exact concatenation would require every
        space to line up exactly, which the words list gives no guarantee of.

        REQUIRED FALLBACK, matching split_sentences' own degrade-on-failure
        shape: no words at all (word timestamps absent, or a segment from the
        per-channel stereo path that never carried them) gives every sentence
        the turn's own start/end rather than raising. The same fallback is
        used, per sentence, if the word list runs out before a sentence's
        text is fully matched - a text/word mismatch is a data quirk, not a
        reason to crash a render.
        """
        try:
            texts = split_sentences(self.text)
        except Exception as e:
            logger.warning(f"Could not split turn into sentences: {e}")
            texts = [self.text] if self.text else []

        if not texts:
            return []

        if not self.words:
            return [Sentence(text=t, start=self.start, end=self.end, words=[]) for t in texts]

        try:
            result: List[Sentence] = []
            word_index = 0
            word_count = len(self.words)
            previous_end = self.start

            for text in texts:
                target_len = len("".join(text.split()))
                consumed_len = 0
                sentence_words: List[Word] = []

                while word_index < word_count and consumed_len < target_len:
                    w = self.words[word_index]
                    consumed_len += len("".join((w.text or "").split()))
                    sentence_words.append(w)
                    word_index += 1

                if sentence_words:
                    start = sentence_words[0].start
                    end = sentence_words[-1].end
                else:
                    # Words ran out before this sentence matched anything -
                    # fall back rather than leave it with no span at all.
                    start = previous_end
                    end = self.end

                result.append(Sentence(text=text, start=start, end=end, words=sentence_words))
                previous_end = end

            return result
        except Exception as e:
            logger.warning(f"Could not derive sentence spans from words: {e}")
            return [Sentence(text=t, start=self.start, end=self.end, words=[]) for t in texts]


def merge_turns(
    segments: List[Segment],
    gap_seconds: float = TURN_GAP_SECONDS,
    max_seconds: float = TURN_MAX_SECONDS,
) -> List[Turn]:
    """Group consecutive segments into readable speaker turns."""
    turns: List[Turn] = []

    for segment in segments:
        if not segment.text or not segment.text.strip():
            continue

        current = turns[-1] if turns else None
        if (
            current is not None
            and segment.speaker == current.speaker
            and segment.start - current.end <= gap_seconds
            and segment.end - current.start <= max_seconds
        ):
            current.append(segment)
        else:
            turns.append(Turn(segment))

    return turns


def _speaker_indices(segments: List[Segment]) -> List[int]:
    """Distinct speakers in a document, in first-appearance order."""
    ordered: List[int] = []
    for segment in segments:
        if segment.speaker is not None and segment.speaker not in ordered:
            ordered.append(segment.speaker)
    return ordered
