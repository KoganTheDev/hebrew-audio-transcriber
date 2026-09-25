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


def read_uem(path: str) -> list[tuple[float, float]]:
    """Scored regions, in NIST's UEM format: `<file-id> <channel> <start> <end>`.

    See compute_der's `scored` parameter for what this is for. Blank lines and
    `#` comments are skipped, the same way read_rttm tolerates them.
    """
    regions: list[tuple[float, float]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            regions.append((float(parts[2]), float(parts[3])))
    return sorted(regions)


def _clip(turns: list[Turn], scored: list[tuple[float, float]]) -> list[Turn]:
    """Every turn, cut down to the parts that fall inside a scored region."""
    out: list[Turn] = []
    for start, end, speaker in turns:
        for r0, r1 in scored:
            lo, hi = max(start, r0), min(end, r1)
            if hi > lo:
                out.append((lo, hi, speaker))
    return out


def compute_der(
    reference: list[Turn],
    hypothesis: list[Turn],
    max_brute_force_speakers: int = _MAX_BRUTE_FORCE_SPEAKERS,
    scored: list[tuple[float, float]] | None = None,
) -> DERResult:
    """
    Standard DER: missed + false alarm + confusion, over total reference
    speech, with the optimal reference-to-hypothesis speaker mapping.

    `scored` restricts both sides to a set of regions before anything is
    measured, the job NIST's UEM file does. It exists because a reference can
    have HOLES - stretches where speech certainly happened but the reference
    does not say who was speaking. tests/eval/docx_to_rttm.py produces exactly
    that: it aligns a human transcript onto machine word timings, and a line
    it cannot confidently match is dropped rather than guessed at, leaving a
    gap the reference cannot distinguish from silence.

    Scoring those gaps punishes the diarizer for being right. Measured on the
    alon_naor fixture: 218s of its span sits inside a block the human
    transcript marks as speech while carrying no reference turn, and that
    fixture's false alarm was the highest of the three by a wide margin. Speech
    detected there is correct and was being counted as invented.

    Without `scored` the whole timeline counts, which is right for a
    hand-drawn reference like AMI's where a gap really does mean silence.

    Raises ValueError if reference is empty - a DER against no reference
    speech at all is undefined (division by zero), not zero or one.
    """
    if scored:
        reference = _clip(reference, scored)
        hypothesis = _clip(hypothesis, scored)
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
    candidates: list[str | None] = list(hyp_speakers)
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


def _overlap_with_label(
    turn_start: float, turn_end: float, hyp_label: str, hypothesis: list[Turn]
) -> float:
    """Total duration of ONE hypothesis speaker's turns that overlaps
    [turn_start, turn_end), merging that speaker's own overlapping turns so
    double-covered time is not counted twice."""
    intervals = sorted(
        (max(turn_start, s), min(turn_end, e))
        for s, e, spk in hypothesis
        if spk == hyp_label and e > turn_start and s < turn_end
    )
    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


# Below this fraction of a reference speaker's total speech time being
# covered by their mapped hypothesis speaker, that speaker counts as "not
# found" rather than "found but under-covered" - a sliver of accidental
# overlap from a neighbouring speaker's boundary rounding should not count
# as detection.
_SPEAKER_FOUND_THRESHOLD = 0.05


@dataclass
class SpeakerRecallResult:
    """
    Per-reference-speaker coverage under the SAME optimal one-to-one
    reference-to-hypothesis mapping compute_der uses (see
    _confusion_matrix/_optimal_mapping): for each real speaker, what fraction
    of their speech is covered by the hypothesis speaker THEY were mapped to.

    Raw "covered by any hypothesis turn at all" was tried first and rejected:
    it cannot tell "found" from "merged into someone else's cluster", because
    a merged cluster's spans still physically sit on top of the swallowed
    speaker's speech in time - only the speaker LABEL is wrong, and a
    label-blind overlap check does not notice. Routing through the same
    one-to-one mapping DER already computes does notice: when the hypothesis
    has fewer distinct speakers than the reference (exactly AMI ES2004a's
    sherpa failure - asking for 3, sherpa returns 2 clusters), the mapping
    can assign each hypothesis speaker to at most one reference speaker, so
    whichever reference speaker loses that competition is correctly left
    unmapped and scores zero here - which is what "found 2 of 3 speakers"
    actually means.

    DER is time-weighted, so a hypothesis that never finds a reference
    speaker at all still posts a merely-bad DER rather than an alarming one:
    the lost speaker's speech becomes ordinary missed_speech (or confusion,
    if merged), indistinguishable from "the boundary was 200ms off" by
    looking at DER alone. speaker_recall makes "found N of M speakers" -
    previously a fact a human read off a printout - a number, and keeps the
    per-speaker detail rather than collapsing straight to a count, because
    knowing WHICH speaker was lost (not just how many) is what makes the
    finding actionable.
    """

    per_speaker: dict[str, float]  # reference speaker -> fraction covered by its mapped speaker
    found_count: int  # reference speakers with coverage above _SPEAKER_FOUND_THRESHOLD
    total_count: int  # total distinct reference speakers

    def __str__(self) -> str:
        detail = ", ".join(f"{spk}={frac:.2f}" for spk, frac in sorted(self.per_speaker.items()))
        return f"speaker_recall={self.found_count}/{self.total_count} ({detail})"


def speaker_recall(
    reference: list[Turn],
    hypothesis: list[Turn],
    max_brute_force_speakers: int = _MAX_BRUTE_FORCE_SPEAKERS,
) -> SpeakerRecallResult:
    """For each reference speaker, the fraction of their total speech time
    covered by the hypothesis speaker the optimal mapping assigns them to -
    zero if the mapping leaves them unassigned. See SpeakerRecallResult for
    why this, not raw time-overlap, is the number that catches "the second
    speaker isn't recognised at all" (whether missed outright or merged into
    another speaker's label) before it reaches a user.
    """
    speakers = sorted({speaker for _, _, speaker in reference})
    ref_speakers, hyp_speakers, matrix = _confusion_matrix(reference, hypothesis)
    mapping = _optimal_mapping(ref_speakers, hyp_speakers, matrix, max_brute_force_speakers)

    per_speaker: dict[str, float] = {}
    for speaker in speakers:
        turns = [(s, e) for s, e, spk in reference if spk == speaker]
        total = sum(e - s for s, e in turns)
        if total <= 0:
            per_speaker[speaker] = 0.0
            continue
        hyp_label = mapping.get(speaker)
        if hyp_label is None:
            per_speaker[speaker] = 0.0
            continue
        covered = sum(_overlap_with_label(s, e, hyp_label, hypothesis) for s, e in turns)
        # Clamp: a reference speaker's own turns can themselves overlap (see
        # the module docstring's note on simultaneous speech), which could
        # otherwise push a naive sum above 1.0.
        per_speaker[speaker] = min(1.0, covered / total)

    found_count = sum(1 for frac in per_speaker.values() if frac > _SPEAKER_FOUND_THRESHOLD)
    return SpeakerRecallResult(
        per_speaker=per_speaker, found_count=found_count, total_count=len(speakers)
    )


@dataclass
class SpeakerCountResult:
    """
    Signed difference between distinct hypothesis and reference speaker
    counts. Positive means the hypothesis invented extra speakers
    (over-clustering/fragmentation); negative means it collapsed real people
    together (under-clustering/merging). DER's confusion component cannot
    tell these apart - both look like "wrong speaker at this instant" - but
    they call for opposite fixes: a higher cluster threshold for the former,
    a lower one (or a correct num_clusters) for the latter.
    """

    hyp_speakers: int
    ref_speakers: int

    @property
    def error(self) -> int:
        return self.hyp_speakers - self.ref_speakers

    def __str__(self) -> str:
        sign = "+" if self.error > 0 else ""
        return f"speaker_count_error={sign}{self.error} (hyp={self.hyp_speakers}, ref={self.ref_speakers})"


def speaker_count_error(reference: list[Turn], hypothesis: list[Turn]) -> SpeakerCountResult:
    """Distinct hypothesis labels minus distinct reference speakers, signed."""
    ref_speakers = len({speaker for _, _, speaker in reference})
    hyp_speakers = len({speaker for _, _, speaker in hypothesis})
    return SpeakerCountResult(hyp_speakers=hyp_speakers, ref_speakers=ref_speakers)


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
