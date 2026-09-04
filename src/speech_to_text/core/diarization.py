"""Speaker diarization: working out who spoke when, for single-microphone
recordings where both parties share one channel.

Engine choice. The obvious candidate is pyannote.audio, which is the accuracy
leader, but it pulls torch and torchaudio (~2.5 GB) and requires a HuggingFace
account plus accepting gated model terms before it will download weights at
runtime. That is a poor fit for an app whose entire premise is that it runs
locally with no account and no network after setup. sherpa-onnx runs the same
family of models through onnxruntime instead: ~36 MB of weights, no login, no
torch, and it exposes the one knob that matters most here - clustering into a
known number of speakers.

Accuracy note: fixing the speaker count is the single largest lever available.
Threshold-based clustering has to infer how many people are present, and it
gets that wrong often enough to fragment one speaker into several. If the user
knows there are two people, saying so removes the hardest part of the problem.
"""

import logging
import os
import shutil
import tarfile
import urllib.request
from collections.abc import Sequence
from typing import Callable, List, Optional

import numpy as np

from speech_to_text import config
from speech_to_text.core.segments import Segment, Word

logger = logging.getLogger(__name__)

# Cache next to whisper_models/, which Transcriber already uses as its
# download_root. Both are gitignored.
MODELS_DIR = "./diarization_models"

_SEGMENTATION_ARCHIVE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
_SEGMENTATION_MODEL = os.path.join(
    MODELS_DIR, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx"
)

# VoxCeleb-trained rather than one of the Chinese-corpus alternatives. Speaker
# embeddings capture voice timbre more than language-specific phonetics, so
# any of them would function on Hebrew, but VoxCeleb is by far the most
# speaker-diverse training set of the options offered, which is the property
# that actually matters for telling two unfamiliar voices apart.
_EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
)
_EMBEDDING_MODEL = os.path.join(MODELS_DIR, "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx")


class DiarizationUnavailable(Exception):
    """Raised when diarization cannot run. Never fatal to a transcription."""


def models_present() -> bool:
    return os.path.exists(_SEGMENTATION_MODEL) and os.path.exists(_EMBEDDING_MODEL)


def ensure_models(progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Download the ONNX models on first use.

    sherpa-onnx ships no weights of its own, so this has to happen once. Both
    files are small enough (~36 MB total) that a progress callback is a
    courtesy rather than a necessity, but a silent multi-second stall in a
    desktop app reads as a freeze.
    """
    if models_present():
        return

    os.makedirs(MODELS_DIR, exist_ok=True)

    if not os.path.exists(_EMBEDDING_MODEL):
        _download(_EMBEDDING_URL, _EMBEDDING_MODEL, progress)

    if not os.path.exists(_SEGMENTATION_MODEL):
        archive = os.path.join(MODELS_DIR, "segmentation.tar.bz2")
        _download(_SEGMENTATION_ARCHIVE, archive, progress)
        try:
            with tarfile.open(archive, "r:bz2") as tar:
                # Guard against path traversal in archive members. These come
                # from a trusted release, but extracting archives without
                # checking member paths is the kind of thing that stays wrong
                # forever once copied elsewhere.
                _safe_extract(tar, MODELS_DIR)
        finally:
            if os.path.exists(archive):
                os.remove(archive)

    if not models_present():
        raise DiarizationUnavailable("Diarization models missing after download")


def _safe_extract(tar: tarfile.TarFile, target_dir: str) -> None:
    target_root = os.path.abspath(target_dir)
    for member in tar.getmembers():
        destination = os.path.abspath(os.path.join(target_dir, member.name))
        if not destination.startswith(target_root + os.sep) and destination != target_root:
            raise DiarizationUnavailable(f"Unsafe path in archive: {member.name}")
    tar.extractall(target_dir)


def _download(url: str, destination: str, progress: Optional[Callable[[int, int], None]]) -> None:
    logger.info(f"Downloading {os.path.basename(destination)} ...")
    partial = destination + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(partial, "wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        # Move into place only once complete, so an interrupted download can't
        # leave a truncated file that looks cached on the next run.
        shutil.move(partial, destination)
    except Exception as e:
        if os.path.exists(partial):
            os.remove(partial)
        raise DiarizationUnavailable(f"Could not download {url}: {e}") from e


def diarize(
    samples: np.ndarray,
    sample_rate: int = 16000,
    num_speakers: int = 2,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List["SpeakerSpan"]:
    """Label who is speaking across a mono recording.

    Args:
        samples: float32 mono audio.
        num_speakers: Exact speaker count if known, or -1 to infer it.
        progress: Called with (processed_chunks, total_chunks).

    Returns speaker-labelled time spans, sorted by start time. Spans of
    different speakers may overlap - that is simultaneous speech, not an
    error, and both callers (assign_speakers and the DER metric) handle it.

    Raises DiarizationUnavailable if the engine or models are missing.

    Which pipeline runs is config.DIARIZATION_ENGINE; see that constant for
    the measurements behind having two. This function keeps the same contract
    either way, so nothing downstream needs to know which one ran.

    """
    if config.DIARIZATION_ENGINE == "powerset":
        # Imported lazily so the sherpa path does not pay for onnxruntime
        # session setup, and so a broken powerset module cannot stop the
        # default engine from working.
        from speech_to_text.core.diarization_powerset import diarize_powerset

        return diarize_powerset(
            samples,
            sample_rate=sample_rate,
            num_speakers=num_speakers,
            progress=progress,
        )

    try:
        import sherpa_onnx
    except ImportError as e:
        raise DiarizationUnavailable("sherpa-onnx is not installed") from e

    ensure_models(progress=None)

    # Named diar_config, not config: this module imports the application's
    # own settings module as `config` at the top, and a local of that name
    # shadows it for the whole function body - including the right-hand side
    # of this very assignment, where the min_duration_* values below are read.
    # That shadowing turned every diarization run into an UnboundLocalError,
    # which worker.py's deliberately non-fatal except swallowed into
    # "Speaker identification skipped", so the feature failed silently rather
    # than loudly. diarize() has no unit test - it needs real models and real
    # audio - so nothing caught it but an end-to-end run.
    diar_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=_SEGMENTATION_MODEL
            ),
            # num_threads/provider were never passed here either, so both
            # models ran on onnxruntime's defaults. See the constants in
            # config.py for why the thread count is a small capped number
            # rather than os.cpu_count() - more threads measured SLOWER for
            # this model's one-window-at-a-time inference.
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_EMBEDDING_MODEL,
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            # num_clusters wins when set; threshold is only consulted when the
            # count is unknown (-1).
            num_clusters=num_speakers if num_speakers and num_speakers > 0 else -1,
            threshold=0.5,
        ),
        # Named constants in config.py, kept equal to sherpa-onnx's own
        # defaults - see the comment there for why they are stated explicitly
        # rather than left to the library.
        min_duration_on=config.DIARIZATION_MIN_DURATION_ON,
        min_duration_off=config.DIARIZATION_MIN_DURATION_OFF,
    )
    if not diar_config.validate():
        raise DiarizationUnavailable("Invalid diarization configuration")

    engine = sherpa_onnx.OfflineSpeakerDiarization(diar_config)

    if sample_rate != engine.sample_rate:
        raise DiarizationUnavailable(
            f"Diarization needs {engine.sample_rate} Hz audio, got {sample_rate}"
        )

    def callback(processed: int, total: int) -> int:
        if progress:
            progress(processed, total)
        return 0  # non-zero would ask sherpa-onnx to stop

    result = engine.process(samples, callback=callback)
    spans = [
        SpeakerSpan(start=s.start, end=s.end, speaker=s.speaker)
        for s in result.sort_by_start_time()
    ]
    logger.info(f"Diarization found {result.num_speakers} speaker(s) across {len(spans)} spans")
    return spans


class SpeakerSpan:
    """A stretch of audio attributed to one speaker."""

    __slots__ = ("start", "end", "speaker")

    def __init__(self, start: float, end: float, speaker: int):
        self.start = start
        self.end = end
        self.speaker = speaker

    def overlap(self, start: float, end: float) -> float:
        return max(0.0, min(self.end, end) - max(self.start, start))

    def __repr__(self) -> str:
        return f"SpeakerSpan({self.start:.2f}-{self.end:.2f}, speaker={self.speaker})"


# Re-exported from config so the tuning value lives with the other
# diarization knobs, while this module-level name (which callers and tests
# already use) keeps working. The two must not drift - tests assert they are
# the same object.
MIN_SPEAKER_RUN_WORDS = config.DIARIZATION_MIN_SPEAKER_RUN_WORDS


def assign_speakers(
    segments: Sequence[Segment],
    spans: Sequence[SpeakerSpan],
    min_run_words: int = MIN_SPEAKER_RUN_WORDS,
) -> List[Segment]:
    """Attach a speaker to each transcript segment, splitting where the speaker
    changes mid-segment.

    Works at word level, not segment level. Whisper's segment boundaries are
    decided by its decoder and have no relationship to who is talking, so a
    speaker change lands mid-segment routinely. Attributing whole segments by
    their overall time span would smear every such change across an entire
    turn, and even majority-voting the whole segment to one label throws the
    minority words' speaker away. Instead each word is matched to the span it
    overlaps most, and consecutive words that agree become one sub-segment -
    so a straddling segment is cut into two (or more) at the word boundary
    where the speaker actually changed, rather than losing that boundary.

    Segment(start, end, text, speaker, words) is fully reconstructible (see
    core/segments.py), so a split rebuilds new Segment objects rather than
    mutating the input. A segment that does not need splitting is returned
    unchanged - same object, not a copy - so callers that compare identity
    (or just want the common case to be cheap) see that.

    Segments with no word timings (or no overlapping span at all) fall back to
    matching on the segment's own span, and stay None if even that fails.
    Leaving a segment unattributed is better than guessing: the renderer
    simply omits the label.

    The returned list is new: `segments` itself is never reordered, extended
    or shortened, and a split segment's pieces are new Segment objects. But a
    segment that is not split IS mutated - its `.speaker` is set in place
    (in the no-split and fallback branches above) and that same object,
    not a copy, is what comes back in the result. So `segments is not
    assign_speakers(segments, spans)` always holds, but
    `segments[i] is result[j]` can still be true for an unsplit segment.
    """
    if not spans:
        return list(segments)

    result: List[Segment] = []
    for segment in segments:
        result.extend(_split_segment(segment, spans, min_run_words))
    return result


def _split_segment(
    segment: Segment,
    spans: Sequence[SpeakerSpan],
    min_run_words: int = MIN_SPEAKER_RUN_WORDS,
) -> List[Segment]:
    """Attribute one segment, splitting it if a real speaker change is found."""
    if not segment.words:
        # No word timings at all - the per-channel stereo path never carries
        # them, and neither does a segment faster-whisper emitted without
        # word_timestamps. Only the segment's own span is available.
        segment.speaker = _best_speaker(spans, segment.start, segment.end)
        return [segment]

    labels = [_best_speaker(spans, word.start, word.end) for word in segment.words]

    if all(label is None for label in labels):
        # Every word missed every span - e.g. the whole segment falls in a
        # gap min_duration_on/off dropped. Leave it unattributed rather than
        # inventing a label from nothing.
        segment.speaker = None
        return [segment]

    # A word with no overlap of its own (a rounding gap at a span boundary,
    # or a span dropped by min_duration_on) does not get to start a run or a
    # None-labelled sub-segment - it is filled in from its neighbours, the
    # same way it would have simply not voted under the old majority scheme.
    filled = _fill_unmatched(labels, segment.words)
    runs = _coalesce_adjacent(_merge_short_runs(_runs(filled), min_run_words, segment.words, spans))

    if len(runs) == 1:
        segment.speaker = runs[0][2]
        return [segment]

    pieces: List[Segment] = []
    last_index = len(runs) - 1
    for i, (start_idx, end_idx, label) in enumerate(runs):
        run_words = segment.words[start_idx:end_idx]
        # Rejoining word texts and stripping mirrors exactly how the original
        # segment text itself was produced: faster-whisper decodes the whole
        # token run and strips it once, and each word's own decoded text
        # already carries whatever leading space separates it from its
        # neighbour (verified against the installed faster-whisper: word
        # text comes from tokenizer.decode() on that word's token slice, so
        # concatenating word texts reproduces the segment text exactly).
        # Stripping only the ends - not collapsing internal whitespace -
        # keeps inter-word spacing exactly as the model produced it.
        text = "".join(word.text for word in run_words).strip()
        # Endpoints: the first piece keeps the segment's own start (which can
        # lead the first word, e.g. VAD padding) and the last piece keeps its
        # own end, for the same reason. Interior boundaries use the word
        # timings themselves, since that word boundary is the split point.
        start = segment.start if i == 0 else run_words[0].start
        end = segment.end if i == last_index else run_words[-1].end
        pieces.append(
            Segment(start=start, end=end, text=text, words=list(run_words), speaker=label)
        )
    return pieces


def _label_coverage(
    spans: Sequence[SpeakerSpan], label: Optional[int], start: float, end: float
) -> float:
    """How much of [start, end) the given speaker's spans cover, in seconds."""
    if label is None:
        return 0.0
    return sum(span.overlap(start, end) for span in spans if span.speaker == label)


def _fill_unmatched(labels: Sequence[Optional[int]], words: Sequence[Word]) -> List[Optional[int]]:
    """Carry a real label over words that overlap no span, from whichever
    labelled neighbour is nearer IN TIME - and only across a short gap.

    This used to forward-fill: a gap word simply took the label of whoever
    spoke last, and a leading run of gap words took the first real label
    found. Both are the same bias, and it is the one that makes a transcript
    read as though one speaker is doing all the talking. A word sitting in
    silence 40ms after speaker A stopped and 900ms before speaker B starts
    belongs with A; the same word 900ms after A and 40ms before B belongs
    with B, and forward-fill got that case backwards every time.

    Neighbours are read from the ORIGINAL labels, never from labels this
    function has already filled in, so one borrowed label cannot chain across
    a whole run of gap words - each is decided on its own distance to real
    evidence.

    Beyond config.DIARIZATION_MAX_FILL_GAP_SECONDS the word keeps no label at
    all. Inventing an attribution across a two-second silence is guessing, and
    an unattributed word renders without a speaker rather than under the wrong
    one - see assign_speakers' docstring on why that is the honest failure.
    """
    filled: List[Optional[int]] = list(labels)

    # Nearest real label to each side, indices into the ORIGINAL labels.
    n = len(labels)
    left_of: List[Optional[int]] = [None] * n
    right_of: List[Optional[int]] = [None] * n
    seen: Optional[int] = None
    for i in range(n):
        left_of[i] = seen
        if labels[i] is not None:
            seen = i
    seen = None
    for i in range(n - 1, -1, -1):
        right_of[i] = seen
        if labels[i] is not None:
            seen = i

    for i, label in enumerate(labels):
        if label is not None:
            continue
        li, ri = left_of[i], right_of[i]
        # A word can sit before every labelled word or after all of them, in
        # which case only one side is a candidate. float("inf") lets the same
        # comparison handle that without a special case - and if the only
        # candidate is too far away, the ceiling below still rejects it.
        gap_left = words[i].start - words[li].end if li is not None else float("inf")
        gap_right = words[ri].start - words[i].end if ri is not None else float("inf")
        # Negative gaps mean the word timings themselves overlap; clamp so
        # "touching" and "overlapping" both read as zero distance.
        gap_left = max(0.0, gap_left)
        gap_right = max(0.0, gap_right)

        if min(gap_left, gap_right) > config.DIARIZATION_MAX_FILL_GAP_SECONDS:
            continue
        # <= so an exact tie prefers the left, which is what this function
        # did unconditionally before - the change is which cases reach the
        # tie, not how a genuine tie breaks.
        filled[i] = labels[li] if gap_left <= gap_right else labels[ri]

    return filled


def _runs(labels: Sequence[Optional[int]]) -> List[List]:
    """Consecutive equal-label stretches, as mutable [start, end, label]."""
    runs: List[List] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append([start, i, labels[start]])
            start = i
    return runs


def _is_real_interjection(
    run: Sequence, words: Sequence[Word], spans: Sequence[SpeakerSpan]
) -> bool:
    """Whether a too-short run is a genuine short turn rather than a boundary slip.

    The run-length floor exists because one stray word usually means the
    diarizer clipped a span boundary by a few tens of milliseconds. But a real
    conversation is full of one-word turns - "כן", "לא", "נכון" - and folding
    every one of them into the previous speaker is the single most visible way
    this app got attribution wrong: the interjecting speaker simply disappears.

    A run earns its own place when the diarizer is positively asserting a
    different speaker across essentially the whole word, not merely clipping
    its edge: the word is long enough to carry a real utterance, and that
    speaker's spans cover nearly all of it.
    """
    start_idx, end_idx, label = run[0], run[1], run[2]
    if label is None:
        return False
    run_words = words[start_idx:end_idx]
    if not run_words:
        return False
    start, end = run_words[0].start, run_words[-1].end
    duration = end - start
    if duration < config.DIARIZATION_INTERJECTION_MIN_SECONDS:
        return False
    covered = _label_coverage(spans, label, start, end)
    return covered >= config.DIARIZATION_INTERJECTION_MIN_COVERAGE * duration


def _merge_short_runs(
    runs: List[List],
    min_words: int,
    words: Sequence[Word] = (),
    spans: Sequence[SpeakerSpan] = (),
) -> List[List]:
    """Fold any run shorter than min_words into a neighbour so it cannot, on its
    own, split the segment (see MIN_SPEAKER_RUN_WORDS) - unless it is a real
    interjection, which keeps its own run.

    Two things here used to bias every decision toward the earlier speaker:

    - A short run was always folded LEFT (`merged[i-1][1] = end`), regardless
      of which neighbour the audio actually supported. Now the run's own words
      are re-scored against each neighbour's label by real span overlap, and
      the better-supported side wins. A tie goes to the longer neighbour,
      then to the left.
    - The scan restarted from the left after every merge, so which run got
      absorbed depended on position in the segment. Now the SHORTEST eligible
      run is resolved first, so the order is driven by how weak the evidence
      is rather than by where it happens to sit.

    None-labelled runs are left alone in both directions: they are words
    _fill_unmatched deliberately declined to attribute (see its docstring),
    and quietly merging them into a labelled neighbour would reinstate exactly
    the guess it refused to make.

    words/spans default to empty so a caller with neither (and older tests
    that call this with two arguments) still gets the length-based behaviour;
    without them no run can qualify as an interjection and overlap scoring
    falls back to the neighbour-length tie-break.
    """
    if len(runs) <= 1:
        return runs

    merged = [list(run) for run in runs]

    def score(run, label) -> float:
        """How much the run's own words support this label, in seconds."""
        if label is None or not words:
            return 0.0
        run_words = words[run[0] : run[1]]
        if not run_words:
            return 0.0
        return _label_coverage(spans, label, run_words[0].start, run_words[-1].end)

    while len(merged) > 1:
        candidates = [
            i
            for i, run in enumerate(merged)
            if run[1] - run[0] < min_words
            and run[2] is not None
            and not _is_real_interjection(run, words, spans)
        ]
        if not candidates:
            break
        # Shortest first; ties by position so the pass stays deterministic.
        i = min(candidates, key=lambda k: (merged[k][1] - merged[k][0], k))

        left = merged[i - 1] if i > 0 else None
        right = merged[i + 1] if i + 1 < len(merged) else None
        if left is not None and left[2] is None:
            left = None
        if right is not None and right[2] is None:
            right = None
        if left is None and right is None:
            # Nothing legitimate to fold into - leave it rather than forcing
            # it onto a None run.
            break

        if left is None:
            take_left = False
        elif right is None:
            take_left = True
        else:
            left_score, right_score = score(merged[i], left[2]), score(merged[i], right[2])
            if left_score != right_score:
                take_left = left_score > right_score
            else:
                left_len, right_len = left[1] - left[0], right[1] - right[0]
                take_left = left_len >= right_len

        if take_left:
            merged[i - 1][1] = merged[i][1]
        else:
            merged[i + 1][0] = merged[i][0]
        del merged[i]

    return merged


def _coalesce_adjacent(runs: List[List]) -> List[List]:
    """Merge neighbouring runs that ended up with the same label after merging short ones."""
    if not runs:
        return runs
    out = [list(runs[0])]
    for start, end, label in runs[1:]:
        if label == out[-1][2]:
            out[-1][1] = end
        else:
            out.append([start, end, label])
    return out


def _best_speaker(spans: Sequence[SpeakerSpan], start: float, end: float) -> Optional[int]:
    """The speaker whose spans overlap [start, end] the most, if any."""
    totals = {}
    for span in spans:
        overlap = span.overlap(start, end)
        if overlap > 0:
            totals[span.speaker] = totals.get(span.speaker, 0.0) + overlap
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]
