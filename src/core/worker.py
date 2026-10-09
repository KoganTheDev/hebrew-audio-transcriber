"""The transcription worker, run in its own OS process.

A separate process because faster-whisper and PyQt5 bundle conflicting copies
of MSVCP140.dll: loaded together, a model load on a QThread crashed with an
uncatchable access violation (0xc0000005).
"""

import logging
import multiprocessing
import os
import random
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from core import keep_awake
from core.progress_scale import (
    BATCH_COMPLETE_PERCENT,
    BATCH_FORMATTING_PERCENT,
    BATCH_INIT_PERCENT,
    BATCH_SAVING_PERCENT,
    BATCH_TRANSCRIBE_END,
    BATCH_TRANSCRIBE_SPAN,
    BATCH_TRANSCRIBE_START,
    FILE_LOCAL_ANALYZING_PERCENT,
    FILE_LOCAL_CORRECTING_PERCENT,
    FILE_LOCAL_MAX,
    FILE_LOCAL_SPEAKER_ID_END,
    FILE_LOCAL_TRANSCRIBE_SPAN,
    FILE_LOCAL_TRANSCRIBE_START,
    STATUS_ONLY_PERCENT,
    TRANSCRIBER_MODEL_LOADED_PERCENT,
    TRANSCRIBER_TRANSCRIBE_SPAN,
    WORK_PHASE_ASSIGN,
    WORK_PHASE_CORRECT,
    WORK_PHASE_DECODE,
    WORK_PHASE_DIARIZE,
    WORK_PHASE_DIARIZE_WAIT,
    WORK_PHASE_RENDER,
    WORK_PHASE_STARTED,
    WORK_PHASE_TRANSCRIBE,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from core.run_options import TranscriptionOptions
    from core.segments import Segment, TranscriptDocument
    from core.transcriber import Transcriber

logger = logging.getLogger(__name__)

# One progress report: an i18n key and its params, never rendered text (this
# process does not know the UI language - see run_transcription_process).
_Message = tuple[str, dict[str, Any]]
# What every progress-reporting step in this module is handed. Which scale
# the percent is on depends on where the callback came from: batch-wide from
# _progress_emitter, file-local from _batch_scale_emitter.
_Emitter = Callable[[_Message, int], None]


def _log_phase(progress_queue: "multiprocessing.Queue", phase: str, start: float) -> None:
    """Report one phase's wall-clock cost to the log and to the GUI's time
    estimate (one measurement, not two that can disagree). perf_counter, which
    cannot jump backwards on an NTP correction.
    """
    elapsed = time.perf_counter() - start
    logger.debug(f"phase timing: {phase} took {elapsed:.3f}s")
    _report_phase(progress_queue, phase, elapsed)


def _report_phase(
    progress_queue: "multiprocessing.Queue", phase: str, seconds: float | None
) -> None:
    """Put one phase fact on the queue. seconds=WORK_PHASE_STARTED means "begun".

    Split from _log_phase because a phase STARTING has nothing to log - there
    is no duration yet - but is the whole point for a phase that reports no
    progress of its own while it runs.
    """
    progress_queue.put(("phase", phase, seconds, time.monotonic()))


def _work_emitter(
    progress_queue: "multiprocessing.Queue", done_before: float, total_duration: float
) -> Callable[[float, float], None]:
    """Lift one file's audio position onto the batch's: offset by the audio
    already finished - audio-seconds add up, no rescaling needed.
    """

    def emit_work(audio_done: float, audio_total: float) -> None:
        del audio_total  # the file's own total; the batch's is what the GUI needs
        progress_queue.put(("work", done_before + audio_done, total_duration, time.monotonic()))

    return emit_work


# faster-whisper retries a 30 s window at higher temperatures inside one call,
# yielding no Segment meanwhile - a frozen bar. It logs each retry at DEBUG;
# these patterns turn those log lines into live status messages.
_RETRY_LOG_PATTERNS = [
    (
        re.compile(r"^Processing segment at (.+)$"),
        lambda m: ("status_analyzing", {"time": m.group(1)}),
    ),
    (
        re.compile(r"^Compression ratio threshold is not met with temperature ([\d.]+)"),
        lambda m: ("status_retry_compression", {"temp": m.group(1)}),
    ),
    (
        re.compile(r"^Log probability threshold is not met with temperature ([\d.]+)"),
        lambda m: ("status_retry_logprob", {"temp": m.group(1)}),
    ),
]


class _RetryStatusLogHandler(logging.Handler):
    """Forwards faster-whisper's own internal decode-retry log lines onto
    progress_queue as status-only updates (kind="status" - text changes,
    percentage does not), so the user sees what's actually happening during
    a stalled window instead of a silent, seemingly-frozen bar.
    """

    def __init__(self, progress_queue: "multiprocessing.Queue"):
        super().__init__(level=logging.DEBUG)
        self._progress_queue = progress_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            raw = record.getMessage()
        except Exception:
            return
        for pattern, to_key_params in _RETRY_LOG_PATTERNS:
            match = pattern.match(raw)
            if match:
                self._progress_queue.put(("status",) + to_key_params(match))
                return


# Prefix of the temp file _atomic_write_html writes through. Named because
# the sweeper below has to recognise its own litter and nothing else.
_TEMP_PREFIX = ".transcript-"
_TEMP_SUFFIX = ".tmp"

# How old an abandoned temp file must be before it is swept. A real write
# takes well under a second, so anything this old is certainly not in
# progress - and the gap is what makes the sweep safe when two runs write to
# the same folder at once, which is a thing a user with two windows open can
# do. Deleting a live sibling's temp file would corrupt ITS output, which is
# far worse than leaving litter.
_TEMP_STALE_SECONDS = 3600.0


def _sweep_stale_temp_files(output_file: str, now: float | None = None) -> int:
    """Delete abandoned .transcript-*.tmp files beside the output; returns how
    many.

    Cancelling terminates the process (TerminateProcess - no finally runs), so
    a run cancelled mid-write leaves its temp file; the next run sweeps it.
    Never fatal: failures are logged and stepped over.
    """
    directory = os.path.dirname(output_file) or "."
    cutoff = (now if now is not None else time.time()) - _TEMP_STALE_SECONDS
    swept = 0
    try:
        names = os.listdir(directory)
    except OSError as e:
        logger.debug(f"Could not list {directory} to sweep temp files: {e}")
        return 0

    for name in names:
        if not (name.startswith(_TEMP_PREFIX) and name.endswith(_TEMP_SUFFIX)):
            continue
        candidate = os.path.join(directory, name)
        try:
            if os.path.getmtime(candidate) > cutoff:
                continue
            os.remove(candidate)
            swept += 1
        except OSError as e:
            logger.debug(f"Could not sweep {candidate}: {e}")

    if swept:
        logger.info(f"Removed {swept} abandoned checkpoint temp file(s) from {directory}")
    return swept


def _atomic_write_html(path: str, content: str) -> None:
    """Write `path` atomically: temp file in the same directory, fsync, then
    os.replace - a crash leaves the old file or the new one, never half of
    either. A failed write removes its temp file.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX, dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


@dataclass
class _BatchRender:
    """The render_html arguments shared by checkpoint and final renders, held
    once so a new render option is one edit, not two.
    """

    output_file: str
    options: "TranscriptionOptions"
    doc_id: str
    vista: str | None
    documents: list["TranscriptDocument"] = field(default_factory=list)

    def render(self) -> str:
        from core import formatting

        return formatting.render_html(
            self.documents,
            speaker_label=self.options.speaker_label,
            timestamps=self.options.timestamps,
            failed_label=self.options.failed_label,
            title=os.path.splitext(os.path.basename(self.output_file))[0],
            ui_strings=self.options.ui_strings,
            doc_id=self.doc_id,
            vista=self.vista,
        )


def _new_batch(options: "TranscriptionOptions", output_file: str) -> _BatchRender:
    """Pin this run's render identity before the first checkpoint write.

    doc_id keys the page's localStorage autosave, so a new one per checkpoint
    would orphan the user's edits; vista keeps the backdrop from changing
    between rewrites (None when no photos exist).
    """
    from core import formatting

    vista_names = formatting._vista_names()
    return _BatchRender(
        output_file=output_file,
        options=options,
        doc_id=uuid.uuid4().hex,
        vista=random.choice(vista_names) if vista_names else None,
    )


def _progress_emitter(progress_queue: "multiprocessing.Queue") -> _Emitter:
    """Adapt the (message, percent) callback shape onto progress_queue."""

    def emit_progress(message: _Message, percent: int) -> None:
        key, params = message
        progress_queue.put(("progress", key, params, percent))

    return emit_progress


def _batch_scale_emitter(
    progress_queue: "multiprocessing.Queue",
    done_before: float,
    file_duration: float,
    total_duration: float,
) -> _Emitter:
    """Rescale one file's 0-100 into its slice of the batch band, sized by its
    share of audio duration, not of the file count.
    """

    def emit_local(message: _Message, local_percent: int) -> None:
        key, params = message
        if local_percent == STATUS_ONLY_PERCENT:
            progress_queue.put(("progress", key, params, STATUS_ONLY_PERCENT))
            return
        if total_duration > 0:
            done = done_before + (local_percent / 100.0) * file_duration
            global_percent = BATCH_TRANSCRIBE_START + int(
                BATCH_TRANSCRIBE_SPAN * done / total_duration
            )
        else:
            # Durations unknown (the GUI always probes them, but a direct
            # caller need not): pin to the start of the band rather than
            # divide by zero. The bar stalls, which is honest - there is
            # nothing to measure progress against.
            global_percent = BATCH_TRANSCRIBE_START
        global_percent = max(BATCH_TRANSCRIBE_START, min(BATCH_TRANSCRIBE_END, global_percent))
        progress_queue.put(("progress", key, params, global_percent))

    return emit_local


def _transcribe_to_document(
    audio_file: str,
    transcriber: "Transcriber",
    options: "TranscriptionOptions",
    file_duration: float,
    emit_local: _Emitter,
    progress_queue: "multiprocessing.Queue",
    work_callback: Callable[[float, float], None],
) -> "TranscriptDocument":
    """Transcribe one file into a document. A failure is logged and marked on
    that document, and the batch carries on.
    """
    from core.segments import TranscriptDocument

    source_name = os.path.basename(audio_file)
    try:
        segments = _transcribe_one(
            audio_file,
            transcriber,
            options,
            file_duration,
            emit_local,
            progress_queue,
            work_callback,
        )
    except Exception as e:
        logger.error(f"Transcription failed for {audio_file}: {e}", exc_info=True)
        return TranscriptDocument(source_name=source_name, failed=True, error_detail=str(e))

    if segments is None:
        return TranscriptDocument(
            source_name=source_name, failed=True, error_detail=transcriber.last_transcribe_error
        )
    return TranscriptDocument(source_name=source_name, segments=segments)


def _write_checkpoint(
    batch: _BatchRender, audio_file: str, progress_queue: "multiprocessing.Queue"
) -> None:
    """Render and atomically rewrite the output after one file, so a crash at
    file 9 of 10 keeps the first nine. O(n^2) rendering, negligible next to
    transcription.

    A safety net: a failure here is logged and the batch continues. Silent -
    no progress or result messages; the GUI only hears about the final write.
    """
    try:
        render_start = time.perf_counter()
        checkpoint_html = batch.render()
        _log_phase(progress_queue, WORK_PHASE_RENDER, render_start)
        _atomic_write_html(batch.output_file, checkpoint_html)
    except Exception as e:
        logger.warning(f"Checkpoint write failed after {audio_file}: {e}", exc_info=True)


def _transcribe_all(
    audio_files: list[str],
    transcriber: "Transcriber",
    options: "TranscriptionOptions",
    batch: _BatchRender,
    progress_queue: "multiprocessing.Queue",
) -> int:
    """Transcribe every file in turn, checkpointing as it goes.

    Appends one TranscriptDocument per input file to `batch` and returns how
    many of them succeeded. Occupies BATCH_TRANSCRIBE_START ..
    BATCH_TRANSCRIBE_END of the overall bar, each file weighted by its share
    of the total audio duration (see _batch_scale_emitter).
    """
    durations = options.audio_durations or [0.0] * len(audio_files)
    total_duration = options.total_duration

    # DEBUG is required for faster-whisper to even emit the "Processing
    # segment at ..." line (it's gated by an isEnabledFor check internally);
    # the retry-threshold messages are unconditional but only useful once
    # we're already listening at this level.
    fw_logger = logging.getLogger("faster_whisper")
    fw_logger.setLevel(logging.DEBUG)
    retry_handler = _RetryStatusLogHandler(progress_queue)
    fw_logger.addHandler(retry_handler)

    done_duration = 0.0
    succeeded = 0
    try:
        for index, audio_file in enumerate(audio_files):
            file_duration = durations[index] if index < len(durations) else 0.0
            progress_queue.put(
                (
                    "status",
                    "w_file_progress",
                    {
                        "i": index + 1,
                        "n": len(audio_files),
                        "name": os.path.basename(audio_file),
                    },
                )
            )

            emit_local = _batch_scale_emitter(
                progress_queue, done_duration, file_duration, total_duration
            )
            emit_work = _work_emitter(progress_queue, done_duration, total_duration)
            document = _transcribe_to_document(
                audio_file,
                transcriber,
                options,
                file_duration,
                emit_local,
                progress_queue,
                emit_work,
            )
            batch.documents.append(document)
            if document.failed:
                # The one thing the GUI could not previously learn. A failed
                # file is recorded in the output document and the batch walks
                # past it, which is the right behaviour - but it meant the
                # progress strip painted the file the same green as one that
                # worked, and the only way to find out was to open the HTML
                # afterwards. 1-based to match w_file_progress's "i".
                progress_queue.put(("file_failed", index + 1))
            else:
                succeeded += 1

            # Nothing to write until a file succeeds: an all-failed batch must
            # end with an error and no output file.
            if succeeded > 0:
                _write_checkpoint(batch, audio_file, progress_queue)

            done_duration += file_duration
    finally:
        fw_logger.removeHandler(retry_handler)

    return succeeded


def _write_final_document(
    batch: _BatchRender, emit_progress: _Emitter, progress_queue: "multiprocessing.Queue"
) -> None:
    """The final render and write. Unlike checkpoints, a failure here
    propagates as the run's error. Atomic too, so it cannot destroy the last
    good checkpoint.
    """
    emit_progress(("w_formatting", {}), BATCH_FORMATTING_PERCENT)
    render_start = time.perf_counter()
    rendered = batch.render()
    _log_phase(progress_queue, WORK_PHASE_RENDER, render_start)

    emit_progress(("w_saving", {}), BATCH_SAVING_PERCENT)
    _atomic_write_html(batch.output_file, rendered)

    emit_progress(("w_complete", {}), BATCH_COMPLETE_PERCENT)


def run_transcription_process(
    audio_files: list[str],
    output_file: str,
    options: "TranscriptionOptions",
    progress_queue: "multiprocessing.Queue",
    result_queue: "multiprocessing.Queue",
) -> None:
    """Entry point for the child process. Must stay import-light (no PyQt5).

    Text crosses the process boundary as (i18n key, params), never rendered
    strings: this process does not know the UI language. progress_queue gets
    ("progress", key, params, percent) and text-only ("status", key, params);
    result_queue gets one ("finished", path) or ("error", key, params).

    The bar, batch-wide (constants in core/progress_scale.py):
      0 .. BATCH_INIT_PERCENT                  starting up
      .. TRANSCRIBER_MODEL_LOADED_PERCENT      loading the model, once per
                                               batch - why the loop lives here
      BATCH_TRANSCRIBE_START .. _END           every file, weighted by duration
      .. BATCH_COMPLETE_PERCENT                rendering and writing

    Only every file failing is an error: one bad file must not cost the rest.
    """
    # Held for the whole batch, not per file: the gap between two files is
    # still this process working, and letting the machine stand by in that
    # window would reintroduce exactly the problem this prevents. See
    # core/keep_awake.py for what was actually going wrong. The `with` also covers
    # every early return below - leaving sleep suppressed after the work is
    # done would be a worse bug than the one this fixes.
    with keep_awake.keep_system_awake("transcription batch"):
        try:
            progress_queue.put(("progress", "w_initializing", {}, BATCH_INIT_PERCENT))

            from core.transcriber import Transcriber

            emit_progress = _progress_emitter(progress_queue)
            transcriber = Transcriber(
                model_size=options.model_size,
                device=options.device,
                language=options.language,
                progress_callback=emit_progress,
            )

            if not transcriber.load_model():
                # Two very different problems used to arrive as one message.
                # A first run with no internet and a genuinely broken model
                # both read "Failed to load transcription model", which tells
                # a user nothing about whether to check their connection or
                # pick a different model.
                result_queue.put(
                    (
                        "error",
                        "err_load_model_offline"
                        if transcriber.load_failed_on_network
                        else "err_load_model",
                        {},
                    )
                )
                return

            # Before the first checkpoint can add one of its own.
            _sweep_stale_temp_files(output_file)

            batch = _new_batch(options, output_file)
            succeeded = _transcribe_all(audio_files, transcriber, options, batch, progress_queue)

            if succeeded == 0:
                # Every document in the batch failed - report the most recent
                # one's real error instead of a bare "transcription failed"
                # that tells the user nothing about why (see TranscriptDocument
                # .error_detail).
                last_error_detail = next(
                    (doc.error_detail for doc in reversed(batch.documents) if doc.error_detail),
                    None,
                )
                result_queue.put(
                    ("error", "err_transcription_failed", {"detail": last_error_detail or "?"})
                )
                return

            _write_final_document(batch, emit_progress, progress_queue)
            result_queue.put(("finished", output_file))

        except Exception as e:
            logger.error(f"Transcription worker process error: {e}", exc_info=True)
            result_queue.put(("error", "err_generic", {"detail": str(e)}))


def _file_local_emitter(emit_progress: _Emitter) -> _Emitter:
    """Remap Transcriber's scale (MODEL_LOADED..TRANSCRIBE_END) onto this
    file's FILE_LOCAL_TRANSCRIBE band, so one loaded Transcriber serves the
    whole batch.
    """

    def from_transcriber_scale(message: _Message, percent: int) -> None:
        if percent == STATUS_ONLY_PERCENT:
            emit_progress(message, percent)
            return
        local = max(
            0,
            min(
                FILE_LOCAL_MAX,
                round(
                    FILE_LOCAL_TRANSCRIBE_START
                    + (percent - TRANSCRIBER_MODEL_LOADED_PERCENT)
                    / TRANSCRIBER_TRANSCRIBE_SPAN
                    * FILE_LOCAL_TRANSCRIBE_SPAN
                ),
            ),
        )
        emit_progress(message, local)

    return from_transcriber_scale


def _start_overlapped_diarization(
    channels: list | None,
    two_party: bool,
    options: "TranscriptionOptions",
    progress_queue: "multiprocessing.Queue",
    result: dict,
) -> tuple[Any | None, Optional["threading.Thread"]]:
    """Downmix to mono and kick diarization off before transcription starts.

    Returns (mono, thread), either of which is None when there is nothing to
    diarize - a two-party file attributes speakers by channel instead, and a
    file that would not decode has no samples to work from.

    Diarization needs only the samples, not the transcript, so it runs on a
    thread beside transcribe() instead of as a second pass afterwards; both
    native libraries release the GIL, so the overlap is real (measured in
    docs/DIARIZATION_TUNING.md).

    During the overlap, diarization reports text-only ("status", ...)
    messages, never a percentage: its band assumes transcription has already
    finished, so a percentage mid-overlap would fight transcribe's own. The
    percentage bump comes in _finish_identify_speakers, once both are done.
    """
    if channels is None or two_party:
        return None, None

    from core import audio_source

    mono = audio_source.to_mono(channels)
    return mono, _start_diarization(mono, options, progress_queue, result)


def _decode_transcript(
    transcriber: "Transcriber",
    audio_file: str,
    channels: list | None,
    mono: Any | None,
    two_party: bool,
    file_duration: float,
    diarization_thread: Optional["threading.Thread"],
    progress_queue: "multiprocessing.Queue",
) -> list["Segment"] | None:
    """Transcribe the file, joining the diarization thread even if
    transcription raises - an unjoined thread would keep burning CPU through
    the rest of the batch for a result nobody reads.
    """
    try:
        if two_party:
            return _transcribe_per_channel(transcriber, channels, file_duration)

        # Hand over the decoded array when we have one so the file is not
        # decoded twice (also what makes reusing it for diarization free);
        # fall back to the path if decoding failed.
        source = mono if mono is not None else audio_file
        transcribe_start = time.perf_counter()
        segments = transcriber.transcribe(source, total_duration_seconds=file_duration)
        _log_phase(progress_queue, WORK_PHASE_TRANSCRIBE, transcribe_start)
        return segments
    finally:
        if diarization_thread is not None:
            # Usually instant (diarization 26.6 s vs transcription 130.3 s on
            # 180 s of audio), but a fast GPU or small model leaves a wait with
            # nothing moving, so the wait is announced and timed.
            join_start = time.perf_counter()
            _report_phase(progress_queue, WORK_PHASE_DIARIZE_WAIT, WORK_PHASE_STARTED)
            diarization_thread.join()
            _log_phase(progress_queue, WORK_PHASE_DIARIZE_WAIT, join_start)


def _transcribe_one(
    audio_file: str,
    transcriber: "Transcriber",
    options: "TranscriptionOptions",
    file_duration: float,
    emit_progress: _Emitter,
    progress_queue: "multiprocessing.Queue",
    work_callback: Callable[[float, float], None],
) -> list["Segment"] | None:
    """One file's decode -> transcribe -> speaker id -> Hebrew correction.

    emit_progress is file-local; progress_queue is passed too, for the
    diarization thread's status messages. Returns None if transcription
    failed, so the caller can skip the file.
    """
    transcriber.progress_callback = _file_local_emitter(emit_progress)
    # Same reassign-per-file arrangement as progress_callback above, for the
    # same reason: one loaded Transcriber serves the whole batch, so what
    # changes per file is only where its reports are routed. The two-party
    # path transcribes each channel over the same file_duration, so its work
    # would otherwise be counted twice - _work_emitter is told the true
    # denominator instead (see _transcribe_per_channel).
    transcriber.work_callback = work_callback
    transcriber.phase_callback = lambda name, seconds: _report_phase(progress_queue, name, seconds)

    channels, two_party = _prepare_audio(
        audio_file, options, file_duration, emit_progress, progress_queue
    )

    diarization_result: dict = {}
    mono, diarization_thread = _start_overlapped_diarization(
        channels, two_party, options, progress_queue, diarization_result
    )

    # Once mixed down the channels are never read again; holding them kept a
    # stereo file in memory three times over for the whole transcription.
    if mono is not None:
        channels = None

    segments = _decode_transcript(
        transcriber,
        audio_file,
        channels,
        mono,
        two_party,
        file_duration,
        diarization_thread,
        progress_queue,
    )

    if segments is None:
        return None

    if not two_party:
        _finish_identify_speakers(segments, diarization_result, emit_progress, progress_queue)

    _correct_hebrew(segments, options, emit_progress, progress_queue)

    emit_progress(("w_transcription_done", {}), FILE_LOCAL_MAX)
    return segments


def _prepare_audio(
    audio_file: str,
    options: "TranscriptionOptions",
    file_duration: float,
    emit_progress: _Emitter,
    progress_queue: "multiprocessing.Queue",
) -> tuple[list | None, bool]:
    """Decode the file and decide which speaker-separation path applies.

    Returns (channels, two_party). Decoding is skipped entirely when speaker
    identification is off, since then nothing needs the samples and
    faster-whisper can open the file itself as it always did.
    """
    if not options.identify_speakers:
        return None, False

    emit_progress(("w_analyzing_audio", {}), FILE_LOCAL_ANALYZING_PERCENT)
    from core import audio_source

    decode_start = time.perf_counter()
    channels, two_party = audio_source.load(audio_file)
    _log_phase(progress_queue, WORK_PHASE_DECODE, decode_start)
    if two_party:
        emit_progress(("w_stereo_detected", {}), FILE_LOCAL_TRANSCRIBE_START)
    return channels, two_party


def _transcribe_per_channel(
    transcriber: "Transcriber", channels: Any, file_duration: float
) -> list["Segment"]:
    """Transcribe each channel separately: with one speaker per channel,
    attribution is exact. Costs roughly double the time.
    """
    collected: list[Segment] = []
    # Each pass counts as half the file, so audio_done never runs backwards
    # between channels; the file's total stays its real duration.
    per_channel = list(channels[:2])
    channel_count = max(len(per_channel), 1)
    file_work_callback = transcriber.work_callback
    # The bar has the same problem on the transcriber's own 15-90 scale: each
    # pass climbs the whole band, so channel 2 would restart at 15%. Each
    # channel gets its own slice of that band instead.
    file_progress_callback = transcriber.progress_callback

    for index, channel in enumerate(per_channel):
        offset = index * file_duration / channel_count

        def channel_work(done: float, total: float, _offset: float = offset) -> None:
            file_work_callback(_offset + done / channel_count, total)

        def channel_progress(message: _Message, percent: int, _index: int = index) -> None:
            if percent != STATUS_ONLY_PERCENT:
                fraction = (
                    percent - TRANSCRIBER_MODEL_LOADED_PERCENT
                ) / TRANSCRIBER_TRANSCRIBE_SPAN
                percent = TRANSCRIBER_MODEL_LOADED_PERCENT + round(
                    (_index + max(0.0, fraction)) / channel_count * TRANSCRIBER_TRANSCRIBE_SPAN
                )
            file_progress_callback(message, percent)

        transcriber.work_callback = channel_work
        transcriber.progress_callback = channel_progress
        try:
            segments = transcriber.transcribe(channel, total_duration_seconds=file_duration)
        finally:
            transcriber.work_callback = file_work_callback
            transcriber.progress_callback = file_progress_callback
        if not segments:
            continue
        for segment in segments:
            segment.speaker = index
        collected.extend(segments)

    # Interleave the two channels back into conversational order.
    collected.sort(key=lambda s: s.start)
    return collected


def _start_diarization(
    mono: Any,
    options: "TranscriptionOptions",
    progress_queue: "multiprocessing.Queue",
    result: dict,
) -> Optional["threading.Thread"]:
    """Start diarization (model download, then diarize()) on a thread, leaving
    spans or the caught exception in `result`.

    Progress is text-only status - see _start_overlapped_diarization. Returns
    None when there is nothing to diarize. Every exception is caught: an
    exception in a thread would vanish, and diarization must stay non-fatal.
    """
    if not options.identify_speakers or mono is None:
        return None

    def run() -> None:
        try:
            from core import audio_source, diarization

            progress_queue.put(("status", "w_identifying_speakers", {}))

            if not diarization.models_present():
                progress_queue.put(("status", "w_downloading_diarization", {}))
                diarization.ensure_models()

            diarize_start = time.perf_counter()
            spans = diarization.diarize(
                mono,
                sample_rate=audio_source.SAMPLE_RATE,
                num_speakers=options.num_speakers,
                # No per-chunk percentage callback: a percentage with nowhere
                # honest to go on the file-local scale while transcription is
                # still running concurrently is worse than none at all. The
                # "w_identifying_speakers" status message above already told
                # the user this phase is under way.
                progress=None,
            )
            _log_phase(progress_queue, WORK_PHASE_DIARIZE, diarize_start)
            result["spans"] = spans
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=run, name="diarization", daemon=True)
    thread.start()
    return thread


def _finish_identify_speakers(
    segments: list["Segment"],
    result: dict,
    emit_progress: _Emitter,
    progress_queue: "multiprocessing.Queue",
) -> None:
    """Attach speakers once transcription and diarization are both done.
    Non-fatal: any failure costs the speaker labels and nothing else.
    """
    if "error" in result:
        logger.warning(
            f"Speaker identification skipped: {result['error']}", exc_info=result["error"]
        )
        emit_progress(("w_speakers_unavailable", {}), FILE_LOCAL_SPEAKER_ID_END)
        return

    if not segments:
        return

    # Empty spans (no distinguishable speakers) is not "never ran": it still
    # goes through assign_speakers, a no-op for it, and its progress report.
    spans = result.get("spans", [])

    try:
        from core import diarization

        # assign_speakers returns a NEW list - a segment whose words cross a
        # speaker boundary is split into consecutive sub-segments rather than
        # labelled by majority vote (see core/diarization.py). Assigning into
        # the caller's list in place (segments[:] = ..., not rebinding the
        # local name) is what lets _transcribe_one keep and return the same
        # list object with those splits in it.
        assign_start = time.perf_counter()
        segments[:] = diarization.assign_speakers(segments, spans)
        _log_phase(progress_queue, WORK_PHASE_ASSIGN, assign_start)

        # The percentage withheld during the overlap; one writer again now.
        emit_progress(("w_identifying_speakers", {}), FILE_LOCAL_SPEAKER_ID_END)

    except Exception as e:
        logger.warning(f"Speaker identification skipped: {e}", exc_info=True)
        emit_progress(("w_speakers_unavailable", {}), FILE_LOCAL_SPEAKER_ID_END)


def _correct_hebrew(
    segments: list["Segment"] | None,
    options: "TranscriptionOptions",
    emit_progress: _Emitter,
    progress_queue: "multiprocessing.Queue",
) -> None:
    """Fix misrecognised domain terms in place; a no-op without a term list.
    Any failure costs the correction and nothing else.
    """
    terms_file = options.terms_file
    if not terms_file or not segments:
        return

    try:
        from core import hebrew_corrections

        terms = hebrew_corrections.TermList.load(terms_file)
        if not len(terms):
            return

        emit_progress(("w_correcting_terms", {}), FILE_LOCAL_CORRECTING_PERCENT)
        correct_start = time.perf_counter()
        changes = hebrew_corrections.correct(segments, terms)
        # After correct(), so a word it replaced is offered alternatives to
        # what the model heard rather than to the replacement.
        suggested = hebrew_corrections.annotate_suggestions(segments, terms)
        _log_phase(progress_queue, WORK_PHASE_CORRECT, correct_start)
        if changes:
            logger.info(f"Applied {len(changes)} Hebrew term correction(s)")
        if suggested:
            logger.info(f"Offered term suggestions on {suggested} doubted word(s)")

    except Exception as e:
        logger.warning(f"Hebrew term correction skipped: {e}", exc_info=True)
