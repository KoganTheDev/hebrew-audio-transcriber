"""Standalone transcription worker, run in a separate OS process.

faster-whisper (ctranslate2) and PyQt5 each bundle their own copy of
MSVCP140.dll on Windows. Loading both into the same process causes an
intermittent native access-violation crash (0xc0000005) that Python cannot
catch, observed specifically when the model loads on a background QThread
while the Qt event loop is active. Running the actual transcription in a
separate process (never importing PyQt5) sidesteps the conflict entirely,
regardless of timing.
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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from speech_to_text.core import power
from speech_to_text.core.progress_scale import (
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
    TRANSCRIBER_MODEL_LOADED_PERCENT,
    TRANSCRIBER_TRANSCRIBE_SPAN,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from speech_to_text.core.options import TranscriptionOptions
    from speech_to_text.core.segments import Segment, TranscriptDocument
    from speech_to_text.core.transcriber import Transcriber

logger = logging.getLogger(__name__)

# One progress report: an i18n key and its params, never rendered text (this
# process does not know the UI language - see run_transcription_process).
_Message = tuple[str, dict[str, Any]]
# What every progress-reporting step in this module is handed. Which scale
# the percent is on depends on where the callback came from: batch-wide from
# _progress_emitter, file-local from _batch_scale_emitter.
_Emitter = Callable[[_Message, int], None]


def _log_phase(phase: str, start: float) -> None:
    """Emit one phase's wall-clock cost at DEBUG.

    This module had zero timing instrumentation before this: decode,
    transcribe, diarize, assign_speakers, Hebrew correction and HTML render
    were indistinguishable in the log, which made "what's actually slow"
    guesswork instead of measurement. time.perf_counter() (monotonic,
    sub-millisecond resolution) rather than time.time() (wall clock, can
    jump backward on an NTP correction) - deliberately not the choice
    tests/eval/compare_models.py and core/calibration.py already make for
    their own reasons.
    """
    logger.debug(f"phase timing: {phase} took {time.perf_counter() - start:.3f}s")


# faster-whisper decodes each ~30s audio window internally, retrying at
# progressively higher "temperatures" whenever the result looks repetitive
# (compression_ratio_threshold) or low-confidence (log_prob_threshold) -
# entirely inside one synchronous call, before it ever yields a Segment. That
# retry loop is exactly the stretch users see as a frozen progress bar: no
# Segment means no percentage update, even though real work is happening.
# faster-whisper already logs each of these events (at DEBUG, on its own
# "faster_whisper" logger) - _RETRY_LOG_PATTERNS turns them into live,
# human-readable status messages instead of leaving the UI silent.
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


def _atomic_write_html(path: str, content: str) -> None:
    """Write content to `path` without ever leaving a half-written file behind.

    A plain `open(path, "w")` truncates the target immediately, so a crash
    partway through the write destroys whatever good output was already
    there - exactly the failure this whole checkpointing scheme exists to
    prevent. Instead: write to a fresh temp file in the SAME directory as
    the target (same filesystem, which is what makes the final step atomic
    rather than a copy), flush and fsync so the bytes are actually on disk
    and not just sitting in an OS buffer, then os.replace() the temp file
    onto the target. os.replace() is an atomic rename on both POSIX and
    Windows: any reader (or another crash) sees either the old complete file
    or the new complete file, never something in between.

    If the write itself fails partway, the temp file is removed rather than
    left behind for the batch's output directory to accumulate junk in.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".transcript-", suffix=".tmp", dir=directory)
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
    """Everything the checkpoint render and the final render both need.

    documents/doc_id/vista are the three things that vary between the two
    render sites; none of the eight OTHER render_html arguments do - both
    calls render the same batch under the same options, just at different
    points in the run. Holding that fixed set in one object means a ninth
    render option is one edit, not two kept in sync by hand.
    """

    output_file: str
    options: "TranscriptionOptions"
    doc_id: str
    vista: Optional[str]
    documents: list["TranscriptDocument"] = field(default_factory=list)

    def render(self) -> str:
        from speech_to_text.core import formatting

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
    """Pin this run's render identity, before the first checkpoint write.

    doc_id: render_html() mints a fresh uuid4 on every call, which is right
    for a one-shot render but wrong for a document rewritten repeatedly
    during one run - a changing doc_id would change the browser's
    localStorage autosave key on every checkpoint, orphaning any edits the
    user made against the previous doc_id. It must stay exactly what it was
    on the first write through to the last.

    vista: same reasoning. Without a pin the backdrop photo would change on
    every per-file checkpoint rewrite and flicker to a different image
    mid-batch - a document is one document, not a slide show. _vista_names()
    can be empty (no vistas/ directory, e.g. an installed copy that lost its
    package data); None then, and render_html() already treats vista=None as
    "no backdrop" the same way it treats an empty vistas/ directory.
    """
    from speech_to_text.core import formatting

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
    """Rescale one file's own 0-100 progress into its slice of the batch band.

    The slice is sized by this file's share of total audio duration rather
    than its share of the file count, so a 2-hour recording among ten
    1-minute ones doesn't make the bar sit at "90% of files done" while most
    of the actual work remains.
    """

    def emit_local(message: _Message, local_percent: int) -> None:
        key, params = message
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
) -> "TranscriptDocument":
    """Transcribe one file into a document, turning any failure into a marked one.

    One file failing does not fail the batch: it is logged, marked on that
    file's TranscriptDocument, and the caller carries on. This mirrors the
    decision already made for diarization and Hebrew correction: an optional
    or partial failure costs only itself.
    """
    from speech_to_text.core.segments import TranscriptDocument

    source_name = os.path.basename(audio_file)
    try:
        segments = _transcribe_one(
            audio_file, transcriber, options, file_duration, emit_local, progress_queue
        )
    except Exception as e:
        logger.error(f"Transcription failed for {audio_file}: {e}", exc_info=True)
        segments = None

    if segments is None:
        return TranscriptDocument(source_name=source_name, failed=True)
    return TranscriptDocument(source_name=source_name, segments=segments)


def _write_checkpoint(batch: _BatchRender, audio_file: str) -> None:
    """Render and atomically rewrite the output after one file.

    Transcription is by far the most expensive step in this pipeline, so the
    combined HTML is re-rendered and rewritten after EVERY file, not only
    once at the very end. A crash, a forced reboot or a kill at file 9 of 10
    must not cost the nine files that already finished. Re-rendering the
    whole document per file is O(n^2) in render cost, but render+write is
    negligible next to decoding and transcribing audio, so this trade is not
    close.

    A checkpoint is a safety net, not the main event: if rendering or writing
    it raises, that must not take down a batch that is otherwise succeeding.
    Log it and keep transcribing - the next checkpoint, or the final write,
    gets another chance.

    Silent to the caller by design: it touches neither progress_queue
    (w_formatting/w_saving stay attached to the one final write only) nor
    result_queue (still exactly one "finished"/"error" at the end) - the
    GUI's completion path does not need to know intermediate writes happened
    at all.
    """
    try:
        render_start = time.perf_counter()
        checkpoint_html = batch.render()
        _log_phase("HTML render (checkpoint)", render_start)
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
            document = _transcribe_to_document(
                audio_file, transcriber, options, file_duration, emit_local, progress_queue
            )
            batch.documents.append(document)
            if not document.failed:
                succeeded += 1

            # Gated on succeeded > 0 rather than firing unconditionally: if
            # every file so far has failed there is nothing worth writing yet
            # (only failure-notice placeholders), and if the whole batch goes
            # on to fail, the caller's "every file failed" path must behave
            # exactly as it always has - error reported, no output file left
            # on disk. Once at least one file has succeeded, every subsequent
            # checkpoint (successful or not) rewrites the full picture so far.
            if succeeded > 0:
                _write_checkpoint(batch, audio_file)

            done_duration += file_duration
    finally:
        fw_logger.removeHandler(retry_handler)

    return succeeded


def _write_final_document(batch: _BatchRender, emit_progress: _Emitter) -> None:
    """Render the combined document once more and write it for the last time.

    Unlike the per-file checkpoints, this write is not allowed to fail
    silently: it's the last chance to persist the batch, so a failure here
    must surface as the "error" result the way it always has (the caller's
    except still catches it). Still routed through the same atomic helper as
    the checkpoints - there is no reason the final write should be less safe
    than the ones before it; a crash during this write must not be able to
    destroy the last good checkpoint on disk.
    """
    emit_progress(("w_formatting", {}), BATCH_FORMATTING_PERCENT)
    render_start = time.perf_counter()
    rendered = batch.render()
    _log_phase("HTML render (final)", render_start)

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

    All human-readable text crosses the process boundary as (i18n key,
    params) pairs, never rendered strings - this process doesn't know the
    UI language, and the GUI renders keys at display time (which also lets
    a mid-run language toggle re-render the live status).

    Puts ("progress", key, params, percent) tuples on progress_queue for
    real percentage updates, and ("status", key, params) tuples for
    text-only updates (see _RetryStatusLogHandler) that describe background
    activity without claiming a percentage that isn't actually known yet.
    Puts a single final ("finished", output_file) or ("error", key, params)
    on result_queue before exiting.

    Overall progress bar phase breakdown, batch-wide (all emitted
    percentages are on this single 0-100 scale, so they only ever move
    forward). The boundaries below are named constants in
    core/progress_scale.py, not numbers retyped here - a bare integer in a
    docstring cannot be checked against the code it describes, and this
    table used to drift from the actual boundaries for exactly that reason.
      0 .. BATCH_INIT_PERCENT
          initializing this process
      BATCH_INIT_PERCENT .. TRANSCRIBER_MODEL_LOADED_PERCENT
          loading the Whisper model - once for the whole batch, which is the
          entire reason this loop lives here rather than in the GUI looping
          over one-file-at-a-time runs (a 1.6 GB default model load is a
          real cost, not worth paying N times)
      BATCH_TRANSCRIBE_START .. BATCH_TRANSCRIBE_END
          transcribing every file in turn - decode, transcribe, identify
          speakers, correct Hebrew terms - each file's share of this band
          weighted by its share of total audio duration (see _transcribe_all)
      BATCH_TRANSCRIBE_END .. BATCH_COMPLETE_PERCENT
          rendering the one combined HTML document and writing it once

    Only every file failing is treated as an overall error - losing a
    batch's worth of finished transcripts to one bad file would be
    indefensible given how long transcription takes.
    """
    # Held for the whole batch, not per file: the gap between two files is
    # still this process working, and letting the machine stand by in that
    # window would reintroduce exactly the problem this prevents. See
    # core/power.py for what was actually going wrong. The `with` also covers
    # every early return below - leaving sleep suppressed after the work is
    # done would be a worse bug than the one this fixes.
    with power.keep_system_awake("transcription batch"):
        try:
            progress_queue.put(("progress", "w_initializing", {}, BATCH_INIT_PERCENT))

            from speech_to_text.core.transcriber import Transcriber

            emit_progress = _progress_emitter(progress_queue)
            transcriber = Transcriber(
                model_size=options.model_size,
                device=options.device,
                language=options.language,
                progress_callback=emit_progress,
            )

            if not transcriber.load_model():
                result_queue.put(("error", "err_load_model", {}))
                return

            batch = _new_batch(options, output_file)
            succeeded = _transcribe_all(audio_files, transcriber, options, batch, progress_queue)

            if succeeded == 0:
                result_queue.put(("error", "err_transcription_failed", {}))
                return

            _write_final_document(batch, emit_progress)
            result_queue.put(("finished", output_file))

        except Exception as e:
            logger.error(f"Transcription worker process error: {e}", exc_info=True)
            result_queue.put(("error", "err_generic", {"detail": str(e)}))


def _file_local_emitter(emit_progress: _Emitter) -> _Emitter:
    """Remap Transcriber's own absolute scale onto this file's local 0-100.

    Transcriber emits TRANSCRIBER_MODEL_LOADED_PERCENT at the start of
    transcribe() and climbs to TRANSCRIBER_TRANSCRIBE_END_PERCENT as segments
    complete; that fixed range was written back when a worker run only ever
    handled one file. Remapping it here onto
    FILE_LOCAL_TRANSCRIBE_START..FILE_LOCAL_TRANSCRIBE_END (leaving
    0..FILE_LOCAL_TRANSCRIBE_START for decoding and
    FILE_LOCAL_TRANSCRIBE_END..FILE_LOCAL_MAX for speakers and correction) is
    what lets a single already-loaded Transcriber be reused, unmodified,
    across every file in a batch instead of paying the model-load cost again
    per file.
    """

    def from_transcriber_scale(message: _Message, percent: int) -> None:
        # A stray 0 (Transcriber's own error sentinel) clamps to 0 rather
        # than going negative - the file is about to be marked failed
        # regardless of the exact number shown at that instant.
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
    channels: Optional[list],
    two_party: bool,
    options: "TranscriptionOptions",
    progress_queue: "multiprocessing.Queue",
    result: dict,
) -> tuple[Optional[Any], Optional["threading.Thread"]]:
    """Downmix to mono and kick diarization off before transcription starts.

    Returns (mono, thread), either of which is None when there is nothing to
    diarize - a two-party file attributes speakers by channel instead, and a
    file that would not decode has no samples to work from.

    Diarization is a full second pass over the SAME audio, and - unlike every
    other step in this pipeline - does not depend on the transcript at all:
    diarize() takes only the raw samples, and only assign_speakers (after
    both are done) needs segments. Run sequentially, it costs a whole extra
    pass; started here, before transcribe(), it costs only whatever of it
    doesn't finish before transcribe() does. Both faster-whisper
    (ctranslate2) and sherpa-onnx (onnxruntime) release the GIL during their
    native compute, so a plain Python thread gets real wall-clock overlap,
    not just interleaving - though with 4 physical cores and beam_size=5
    already asking for several of them, how much overlap actually pays off is
    a measurement question (see tests/eval/compare_models.py and the Stage 2
    report), not something guaranteed by the threading alone.

    Progress during the overlap window is deliberately routed as
    ("status", key, params) - text only, no percentage (see
    _RetryStatusLogHandler for the existing precedent, and gui/threads.py's
    _relay_progress_message for how the GUI treats it) - rather than through
    the file-local percent scale. Diarization's own band
    (FILE_LOCAL_TRANSCRIBE_END..FILE_LOCAL_SPEAKER_ID_END) was carved out on
    the assumption transcription had already reached
    FILE_LOCAL_TRANSCRIBE_END by the time diarization started; once the two
    run concurrently that assumption no longer holds - diarization can
    legitimately finish before transcription does on a long file - so a
    diarization percentage arriving mid-overlap would either lie (claim more
    done than the file-local scale means) or fight transcribe's own climbing
    percentage for the same numbers. Text status has no such ordering
    constraint. The real percentage bump for this phase still happens, in
    _finish_identify_speakers, but only after both threads have actually
    finished - at that point there is only one writer again and the normal
    sequential guarantee holds.
    """
    if channels is None or two_party:
        return None, None

    from speech_to_text.core import audio_source

    mono = audio_source.to_mono(channels)
    return mono, _start_diarization(mono, options, progress_queue, result)


def _decode_transcript(
    transcriber: "Transcriber",
    audio_file: str,
    channels: Optional[list],
    mono: Optional[Any],
    two_party: bool,
    file_duration: float,
    diarization_thread: Optional["threading.Thread"],
) -> Optional[list["Segment"]]:
    """Produce this file's segments, joining the diarization thread either way.

    try/finally, not a bare call followed by a join: transcriber.transcribe()
    can raise (a bad file, a decode failure faster-whisper only discovers
    partway through), and letting that propagate straight out - skipping the
    join - would leave the diarization thread orphaned. daemon=True (see
    _start_diarization) only guarantees it won't block process exit; while
    THIS process is still alive (more files left in the batch, or about to
    render and write the final HTML) an unjoined thread keeps burning CPU
    concurrently with that work for a result nothing will ever read.
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
        _log_phase("transcribe", transcribe_start)
        return segments
    finally:
        if diarization_thread is not None:
            diarization_thread.join()


def _transcribe_one(
    audio_file: str,
    transcriber: "Transcriber",
    options: "TranscriptionOptions",
    file_duration: float,
    emit_progress: _Emitter,
    progress_queue: "multiprocessing.Queue",
) -> Optional[list["Segment"]]:
    """Run one file's decode -> transcribe -> speaker id -> Hebrew correction.

    emit_progress here is already file-local (0-100 covering just this file's
    own work) - the caller does the duration-weighted rescale into the
    batch's overall percentage. progress_queue is the raw queue underneath
    it, needed separately because the overlapped diarization thread reports
    its own progress as text-only "status" messages rather than through
    emit_progress's percent scale (see _start_overlapped_diarization).

    Reassigns transcriber.progress_callback for the duration of this call, so
    one already-loaded Transcriber serves the whole batch (see
    _file_local_emitter).

    Returns None (rather than raising) if this file's transcription itself
    failed, so one bad file can be caught and skipped by the caller without
    losing the rest of the batch.
    """
    transcriber.progress_callback = _file_local_emitter(emit_progress)

    channels, two_party = _prepare_audio(audio_file, options, file_duration, emit_progress)

    diarization_result: dict = {}
    mono, diarization_thread = _start_overlapped_diarization(
        channels, two_party, options, progress_queue, diarization_result
    )

    segments = _decode_transcript(
        transcriber,
        audio_file,
        channels,
        mono,
        two_party,
        file_duration,
        diarization_thread,
    )

    if segments is None:
        return None

    if not two_party:
        _finish_identify_speakers(segments, diarization_result, emit_progress)

    _correct_hebrew(segments, options, emit_progress)

    emit_progress(("w_transcription_done", {}), FILE_LOCAL_MAX)
    return segments


def _prepare_audio(
    audio_file: str,
    options: "TranscriptionOptions",
    file_duration: float,
    emit_progress: _Emitter,
) -> tuple[Optional[list], bool]:
    """Decode the file and decide which speaker-separation path applies.

    Returns (channels, two_party). Decoding is skipped entirely when speaker
    identification is off, since then nothing needs the samples and
    faster-whisper can open the file itself as it always did.
    """
    if not options.identify_speakers:
        return None, False

    emit_progress(("w_analyzing_audio", {}), FILE_LOCAL_ANALYZING_PERCENT)
    from speech_to_text.core import audio_source

    decode_start = time.perf_counter()
    channels, two_party = audio_source.load(audio_file)
    _log_phase("audio decode", decode_start)
    if two_party:
        emit_progress(("w_stereo_detected", {}), FILE_LOCAL_TRANSCRIBE_START)
    return channels, two_party


def _transcribe_per_channel(
    transcriber: "Transcriber", channels: Any, file_duration: float
) -> list["Segment"]:
    """Transcribe each channel separately - the exact path.

    When a recording genuinely has one speaker per channel, attribution needs
    no model and carries no error: whoever is on channel 0 is speaker 0. The
    cost is that transcription runs once per channel, roughly doubling the
    wall-clock time, which the GUI's estimate accounts for.
    """
    collected: list[Segment] = []
    for index, channel in enumerate(channels[:2]):
        segments = transcriber.transcribe(channel, total_duration_seconds=file_duration)
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
    """Kick off diarization on a background thread, overlapping it with
    transcription (see the comment above this function's call site in
    _transcribe_one). Runs everything that does NOT need the transcript -
    downloading models on first use, then diarize() itself - and leaves the
    outcome (spans, or a caught exception) in `result` for the main thread to
    read after transcribe() returns and both are actually done (see
    _finish_identify_speakers).

    Progress here goes straight to progress_queue as ("status", key, params)
    - text only, no percentage - not through the file-local emit_progress
    used everywhere else in this module. See the call site's comment for why:
    in short, this phase's percentage band was carved out on the assumption
    transcription had already finished by the time it started, which the
    whole point of overlapping breaks.

    Returns None without starting a thread when diarization isn't wanted or
    there's no audio to diarize - callers only need to check the return value
    for whether there's something to join later, not for whether it "worked":
    that's the non-fatal contract _finish_identify_speakers still owns,
    exactly as the old sequential _identify_speakers did.

    Catches every exception here rather than letting one escape into a
    background thread where nothing would ever see it - diarization staying
    a non-fatal enhancement has to hold in a thread too, not just on the main
    one.
    """
    if not options.identify_speakers or mono is None:
        return None

    def run() -> None:
        try:
            from speech_to_text.core import audio_source, diarization

            progress_queue.put(("status", "w_identifying_speakers", {}))

            if not diarization.models_present():
                progress_queue.put(("status", "w_downloading_diarization", {}))
                diarization.ensure_models()

            diarize_start = time.perf_counter()
            spans = diarization.diarize(
                mono,
                sample_rate=audio_source.SAMPLE_RATE,
                num_speakers=options.num_speakers,
                # No per-chunk percentage callback here (the old sequential
                # code had one) - a percentage with nowhere honest to go on
                # the file-local scale while transcription is still running
                # concurrently is worse than no percentage at all. The
                # "w_identifying_speakers" status message above already told
                # the user this phase is under way.
                progress=None,
            )
            _log_phase("diarize", diarize_start)
            result["spans"] = spans
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=run, name="diarization", daemon=True)
    thread.start()
    return thread


def _finish_identify_speakers(
    segments: list["Segment"], result: dict, emit_progress: _Emitter
) -> None:
    """Attach speakers once both transcription and the overlapped diarization
    thread (see _start_diarization) have finished. assign_speakers is the one
    piece of speaker identification that genuinely needs the transcript, so
    it can never start any earlier than this, overlap or not.

    Same non-fatal contract as the old sequential _identify_speakers: a
    missing model, an absent dependency, or any other failure costs speaker
    labels and nothing else - the transcript this function receives is
    already complete.
    """
    if "error" in result:
        logger.warning(
            f"Speaker identification skipped: {result['error']}", exc_info=result["error"]
        )
        emit_progress(("w_speakers_unavailable", {}), FILE_LOCAL_SPEAKER_ID_END)
        return

    if not segments:
        return

    # spans can legitimately be an empty list - diarize() finding no
    # distinguishable speakers is not an error - and that must NOT take the
    # same early-return path as "spans" being absent because the thread
    # never ran (options.identify_speakers off, or no mono audio at all,
    # see _start_diarization). assign_speakers already treats an empty
    # spans list as a safe no-op (returns segments unchanged - see its own
    # `if not spans` guard in core/diarization.py), so it's called
    # unconditionally below rather than special-cased here, matching what
    # the old sequential _identify_speakers did (it never checked spans
    # before calling assign_speakers either) - including still reporting
    # real progress in that case, which a bare `if not spans: return` would
    # have silently skipped.
    spans = result.get("spans", [])

    try:
        from speech_to_text.core import diarization

        # assign_speakers now returns a new list - a segment whose words
        # cross a speaker boundary is split into consecutive sub-segments
        # instead of being labelled by majority vote (see its docstring in
        # core/diarization.py). Assigning into the caller's list in place
        # (segments[:] = ..., not rebinding the local `segments` name) keeps
        # this change contained to this function: the caller in
        # _transcribe_one still holds and returns the same list object, now
        # with any splits reflected in its contents.
        assign_start = time.perf_counter()
        segments[:] = diarization.assign_speakers(segments, spans)
        _log_phase("assign_speakers", assign_start)

        # A real percentage, not just the status message _start_diarization
        # sent during the overlap window (see its comment for why that one
        # had to be status-only). By the time we're here both threads have
        # already joined, so there is only one writer again and nothing
        # stops a normal percent bump - without this the file-local
        # percentage would silently sit at wherever transcribe() left it
        # through all of diarization and assign_speakers, then jump straight
        # to completion, which is not a monotonicity bug but is a real loss
        # of feedback for a phase that can take a third of the audio's
        # length (see hardware_detection.py's DIARIZATION_REALTIME_FACTOR).
        emit_progress(("w_identifying_speakers", {}), FILE_LOCAL_SPEAKER_ID_END)

    except Exception as e:
        logger.warning(f"Speaker identification skipped: {e}", exc_info=True)
        emit_progress(("w_speakers_unavailable", {}), FILE_LOCAL_SPEAKER_ID_END)


def _correct_hebrew(
    segments: Optional[list["Segment"]],
    options: "TranscriptionOptions",
    emit_progress: _Emitter,
) -> None:
    """Fix misrecognised domain terms, in place.

    A no-op unless the user has written a term list. Like diarization, any
    failure here costs the correction and nothing else - the transcript is
    already complete by this point and must not be put at risk by an optional
    tidying step.
    """
    terms_file = options.terms_file
    if not terms_file or not segments:
        return

    try:
        from speech_to_text.core import hebrew_correct

        terms = hebrew_correct.TermList.load(terms_file)
        if not len(terms):
            return

        emit_progress(("w_correcting_terms", {}), FILE_LOCAL_CORRECTING_PERCENT)
        correct_start = time.perf_counter()
        changes = hebrew_correct.correct(segments, terms)
        _log_phase("Hebrew correction", correct_start)
        if changes:
            logger.info(f"Applied {len(changes)} Hebrew term correction(s)")

    except Exception as e:
        logger.warning(f"Hebrew term correction skipped: {e}", exc_info=True)
