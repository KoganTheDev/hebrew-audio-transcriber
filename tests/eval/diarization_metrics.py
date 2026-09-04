"""
Diarization Error Rate (DER): an RTTM reader plus the standard NIST/DIHARD
metric.

Diarization quality is currently invisible by construction - tests/eval's own
hebrew_metrics.py strips speaker labels as noise before scoring WER, and
nothing else measures "who spoke when" accuracy at all. Without a number,
"the splitting change in core/diarization.py improved things" is not a
falsifiable claim - it is a guess about a guess.

DER, in one sentence: for every instant of the recording, compare who the
reference says was speaking against who the hypothesis says was speaking, and
add up the disagreement, normalised by how much reference speech there was.

    DER = (missed_speech + false_alarm + speaker_confusion) / total_ref_speech

  - missed_speech: reference has a speaker active and the hypothesis has
    nobody active.
  - false_alarm: the hypothesis has a speaker active and the reference has
    nobody active.
  - speaker_confusion: both have somebody active, but not the same person.

"The same person" requires knowing which hypothesis speaker label
corresponds to which reference speaker label - sherpa-onnx's speaker indices
and the RTTM's speaker names are arbitrary and unrelated, so this is an
assignment problem, solved once per file over the whole-file overlap
(the "confusion matrix"), then applied per instant. This is exactly what
pyannote.metrics and NIST's md-eval.pl compute; the formula and the
per-interval decomposition below (missed = max(0, N_ref - N_hyp) etc.)
follow their definition directly.

Overlap handling: the reference RTTM can legitimately contain overlapping
speech (two people talking at once), which is why N_ref and N_hyp above are
counts of distinct active speakers at an instant, not 0/1 flags - the
formula already generalises to that case without special-casing it.

Hungarian algorithm choice: scipy is not a dependency of this project (see
requirements - it would drag in a large numeric stack for one assignment
problem), so the optimal reference-to-hypothesis mapping is solved with a
brute-force permutation search over the confusion matrix instead of a
from-scratch Munkres/Hungarian implementation. This is the right trade for
this codebase specifically: every realistic input here is a handful of
speakers (2 for this app's own two-party recordings, a handful more for a
benchmark meeting corpus like AMI), so an O(n!) search is microseconds, and
it is trivially, obviously correct - no risk of a subtly-wrong hand-rolled
Hungarian solver silently mis-scoring every DER number this harness reports.
_MAX_BRUTE_FORCE_SPEAKERS caps this at 8 speakers (8! = 40320, still
effectively instant); beyond that a documented non-optimal greedy fallback
is used instead of hanging - see _greedy_mapping.
"""

import itertools
from dataclasses import dataclass

# One reference or hypothesis utterance: (start, end, speaker_label).
Turn = tuple[float, float, str]

# Hard cap on the brute-force permutation search - see the module docstring
# for why brute force was chosen at all. 8! = 40320 permutations is instant;
# above this the search would still finish but the cap exists so a caller
# handing in a badly-parsed RTTM (e.g. one row per word, each with a unique
# fake speaker label) fails fast with a clear number instead of silently
# grinding through a huge factorial.
_MAX_BRUTE_FORCE_SPEAKERS = 8


def read_rttm(path: str) -> list[Turn]:
    """
    Parse an RTTM file into a list of (start, end, speaker) turns.

    RTTM (Rich Transcription Time Marked) is the standard format diarization
    ground truth ships in - one "SPEAKER" line per utterance:

        SPEAKER <file-id> <channel> <start> <duration> <NA> <NA> <speaker> <NA> <NA>

    e.g. "SPEAKER ES2004a 1 0.000 3.220 <NA> <NA> speaker1 <NA> <NA>". Only
    the fields DER needs are read; everything else is positional filler in
    the format and is ignored. Blank lines and non-SPEAKER row types (RTTM
    also defines SEGMENT, NOISE etc., unused by the diarization tools this
    project's fixtures come from) are skipped rather than rejected, since a
    ground-truth file downloaded from a mirror is not this project's to
    reject on formatting it doesn't control.
    """
    turns: list[Turn] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 8 or fields[0] != "SPEAKER":
                continue
            start = float(fields[3])
            duration = float(fields[4])
            speaker = fields[7]
            if duration > 0:
                turns.append((start, start + duration, speaker))
    turns.sort(key=lambda t: t[0])
    return turns


@dataclass
class DERResult:
    """
    The DER components, kept apart rather than collapsed to one float,
    because "DER went up" and "DER went up because of false alarms" call for
    different fixes - one points at min_duration_on/off, the other at the
    speaker count passed to diarize().
    """

    total_ref_speech: float
    missed_speech: float
    false_alarm: float
    confusion: float

    @property
    def der(self) -> float:
        if self.total_ref_speech <= 0:
            return float("nan")
        return (self.missed_speech + self.false_alarm + self.confusion) / self.total_ref_speech

    def __str__(self) -> str:
        return (
            f"DER={self.der:.4f}  "
            f"(missed={self.missed_speech:.2f}s, false_alarm={self.false_alarm:.2f}s, "
            f"confusion={self.confusion:.2f}s, total_ref={self.total_ref_speech:.2f}s)"
        )


def compute_der(
    reference: list[Turn],
    hypothesis: list[Turn],
    max_brute_force_speakers: int = _MAX_BRUTE_FORCE_SPEAKERS,
) -> DERResult:
    """
    Standard DER: missed + false alarm + confusion, over total reference
    speech, with the optimal reference-to-hypothesis speaker mapping.

    Raises ValueError if reference is empty - a DER against no reference
    speech at all is undefined (division by zero), not zero or one.
    """
    if not reference:
        raise ValueError("Cannot compute DER against an empty reference")

    ref_speakers, hyp_speakers, matrix = _confusion_matrix(reference, hypothesis)
    mapping = _optimal_mapping(ref_speakers, hyp_speakers, matrix, max_brute_force_speakers)

    boundaries = sorted(
        {
            *(t[0] for t in reference),
            *(t[1] for t in reference),
            *(t[0] for t in hypothesis),
            *(t[1] for t in hypothesis),
        }
    )

    total_ref = 0.0
    missed = 0.0
    false_alarm = 0.0
    confusion = 0.0

    for t0, t1 in zip(boundaries, boundaries[1:]):
        duration = t1 - t0
        if duration <= 0:
            continue
        # Sample at the midpoint of each constant-membership interval rather
        # than at t0: a turn's own start/end is one of the boundary points,
        # and half-open [start, end) membership at exactly t0 is ambiguous
        # for whichever turns end there. The midpoint always falls strictly
        # inside or strictly outside every turn that touches this interval.
        mid = (t0 + t1) / 2
        ref_active = {speaker for (s, e, speaker) in reference if s <= mid < e}
        hyp_active = {speaker for (s, e, speaker) in hypothesis if s <= mid < e}

        n_ref = len(ref_active)
        n_hyp = len(hyp_active)
        n_correct = sum(1 for r in ref_active if mapping.get(r) in hyp_active)

        total_ref += n_ref * duration
        missed += max(0, n_ref - n_hyp) * duration
        false_alarm += max(0, n_hyp - n_ref) * duration
        confusion += (min(n_ref, n_hyp) - n_correct) * duration

    return DERResult(
        total_ref_speech=total_ref,
        missed_speech=missed,
        false_alarm=false_alarm,
        confusion=confusion,
    )


def _confusion_matrix(
    reference: list[Turn], hypothesis: list[Turn]
) -> tuple[list[str], list[str], dict[tuple[str, str], float]]:
    """
    Total co-occurrence duration between every (ref speaker, hyp speaker)
    pair, summed pairwise over every overlapping turn. This is the whole-file
    evidence the optimal mapping is chosen from - a mapping decided from a
    single moment could be misled by one bad interval; this is not.
    """
    ref_speakers = sorted({speaker for _, _, speaker in reference})
    hyp_speakers = sorted({speaker for _, _, speaker in hypothesis})
    matrix: dict[tuple[str, str], float] = {}

    for ref_start, ref_end, ref_speaker in reference:
        for hyp_start, hyp_end, hyp_speaker in hypothesis:
            overlap = min(ref_end, hyp_end) - max(ref_start, hyp_start)
            if overlap > 0:
                key = (ref_speaker, hyp_speaker)
                matrix[key] = matrix.get(key, 0.0) + overlap

    return ref_speakers, hyp_speakers, matrix


def _optimal_mapping(
    ref_speakers: list[str],
    hyp_speakers: list[str],
    matrix: dict[tuple[str, str], float],
    max_brute_force_speakers: int,
) -> dict[str, str]:
    """One-to-one ref-speaker -> hyp-speaker mapping maximising total overlap."""
    if not ref_speakers or not hyp_speakers:
        return {}
    if max(len(ref_speakers), len(hyp_speakers)) <= max_brute_force_speakers:
        return _brute_force_mapping(ref_speakers, hyp_speakers, matrix)
    return _greedy_mapping(ref_speakers, hyp_speakers, matrix)


def _brute_force_mapping(
    ref_speakers: list[str], hyp_speakers: list[str], matrix: dict[tuple[str, str], float]
) -> dict[str, str]:
    """
    Exhaustively try every way to assign hypothesis speakers to reference
    speakers and keep the one with the largest total matched overlap. See
    the module docstring for why this replaces a real Hungarian solver here.
    """
    candidates = list(hyp_speakers)
    # A hypothesis speaker can be left unmatched (padding with None), but a
    # reference speaker with no hypothesis speaker at all can't be matched to
    # one - pad the candidate pool up to the reference count so
    # itertools.permutations has enough slots to leave some reference
    # speakers unmapped when there simply aren't enough hypothesis speakers.
    while len(candidates) < len(ref_speakers):
        candidates.append(None)

    best_score = -1.0
    best_mapping: dict[str, str] = {}
    for assignment in itertools.permutations(candidates, len(ref_speakers)):
        score = sum(
            matrix.get((r, h), 0.0) for r, h in zip(ref_speakers, assignment) if h is not None
        )
        if score > best_score:
            best_score = score
            best_mapping = {r: h for r, h in zip(ref_speakers, assignment) if h is not None}
    return best_mapping


def _greedy_mapping(
    ref_speakers: list[str], hyp_speakers: list[str], matrix: dict[tuple[str, str], float]
) -> dict[str, str]:
    """
    Non-optimal fallback for pathologically large speaker counts (see
    _MAX_BRUTE_FORCE_SPEAKERS). Repeatedly takes the single largest remaining
    overlap in the matrix and commits both sides to it, which can miss the
    true optimum when an early greedy pick blocks a better later pairing -
    acceptable only because this path should never be exercised by any real
    fixture this project uses.
    """
    remaining_ref = set(ref_speakers)
    remaining_hyp = set(hyp_speakers)
    pairs = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
    mapping: dict[str, str] = {}
    for (ref_speaker, hyp_speaker), _overlap in pairs:
        if ref_speaker in remaining_ref and hyp_speaker in remaining_hyp:
            mapping[ref_speaker] = hyp_speaker
            remaining_ref.discard(ref_speaker)
            remaining_hyp.discard(hyp_speaker)
    return mapping
