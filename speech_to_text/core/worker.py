"""
Standalone transcription worker, run in a separate OS process.

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
import re
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from speech_to_text.core.options import TranscriptionOptions
    from speech_to_text.core.segments import Segment
    from speech_to_text.core.transcriber import Transcriber

logger = logging.getLogger(__name__)

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
    (re.compile(r"^Processing segment at (.+)$"),
     lambda m: ("status_analyzing", {"time": m.group(1)})),
    (re.compile(r"^Compression ratio threshold is not met with temperature ([\d.]+)"),
     lambda m: ("status_retry_compression", {"temp": m.group(1)})),
    (re.compile(r"^Log probability threshold is not met with temperature ([\d.]+)"),
     lambda m: ("status_retry_logprob", {"temp": m.group(1)})),
]


class _RetryStatusLogHandler(logging.Handler):
    """
    Forwards faster-whisper's own internal decode-retry log lines onto
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


def run_transcription_process(
    audio_files: List[str],
    output_file: str,
    options: "TranscriptionOptions",
    progress_queue: "multiprocessing.Queue",
    result_queue: "multiprocessing.Queue",
) -> None:
    """
    Entry point for the child process. Must stay import-light (no PyQt5).

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
    forward):
      0-5%    initializing this process
      5-12%   loading the Whisper model - once for the whole batch, which is
              the entire reason this loop lives here rather than in the GUI
              looping over one-file-at-a-time runs (a 1.6 GB default model
              load is a real cost, not worth paying N times)
      12-98%  transcribing every file in turn - decode, transcribe, identify
              speakers, correct Hebrew terms - each file's share of this
              band is weighted by its share of total audio duration (see
              _global_percent below), so one long recording among several
              short ones doesn't make the bar crawl through the short ones
              and then stall
      98-100% rendering the one combined HTML document and writing it once

    One file failing does not fail the batch: it's logged, marked on that
    file's TranscriptDocument, and the loop continues (see _transcribe_one's
    caller below). Only every file failing is treated as an overall error -
    losing a batch's worth of finished transcripts to one bad file would be
    indefensible given how long transcription takes. This mirrors the
    decision already made for diarization and Hebrew correction: an optional
    or partial failure costs only itself.
    """
    try:
        progress_queue.put(("progress", "w_initializing", {}, 2))

        from speech_to_text.core import formatting
        from speech_to_text.core.segments import TranscriptDocument
        from speech_to_text.core.transcriber import Transcriber

        def emit_progress(message, percent: int) -> None:
            key, params = message
            progress_queue.put(("progress", key, params, percent))

        transcriber = Transcriber(
            model_size=options.model_size,
            device=options.device,
            language=options.language,
            progress_callback=emit_progress,
        )

        if not transcriber.load_model():
            result_queue.put(("error", "err_load_model", {}))
            return

        durations = options.audio_durations or [0.0] * len(audio_files)
        total_duration = options.total_duration

        # DEBUG is required for faster-whisper to even emit the
        # "Processing segment at ..." line (it's gated by an isEnabledFor
        # check internally); the retry-threshold messages are unconditional
        # but only useful once we're already listening at this level.
        fw_logger = logging.getLogger("faster_whisper")
        fw_logger.setLevel(logging.DEBUG)
        retry_handler = _RetryStatusLogHandler(progress_queue)
        fw_logger.addHandler(retry_handler)

        documents = []
        done_duration = 0.0
        succeeded = 0
        try:
            for index, audio_file in enumerate(audio_files):
                file_duration = durations[index] if index < len(durations) else 0.0
                progress_queue.put((
                    "status", "w_file_progress",
                    {"i": index + 1, "n": len(audio_files), "name": os.path.basename(audio_file)},
                ))

                # Weighted rescale: this file's own 0-100 local progress
                # becomes its slice of the batch's 12-98% band, sized by its
                # share of total audio duration rather than its share of the
                # file count, so a 2-hour recording among ten 1-minute ones
                # doesn't make the bar sit at "90% of files done" while most
                # of the actual work remains.
                done_before = done_duration

                def emit_local(
                    message,
                    local_percent: int,
                    _done_before=done_before,
                    _file_duration=file_duration,
                ) -> None:
                    key, params = message
                    if total_duration > 0:
                        done = _done_before + (local_percent / 100.0) * _file_duration
                        global_percent = 12 + int(86 * done / total_duration)
                    else:
                        # Durations unknown (the GUI always probes them, but a
                        # direct caller need not): pin to the start of the band
                        # rather than divide by zero. The bar stalls, which is
                        # honest - there is nothing to measure progress against.
                        global_percent = 12
                    global_percent = max(12, min(98, global_percent))
                    progress_queue.put(("progress", key, params, global_percent))

                try:
                    segments = _transcribe_one(
                        audio_file, transcriber, options, file_duration, emit_local
                    )
                except Exception as e:
                    logger.error(f"Transcription failed for {audio_file}: {e}", exc_info=True)
                    segments = None

                if segments is None:
                    documents.append(TranscriptDocument(
                        source_name=os.path.basename(audio_file), failed=True,
                    ))
                else:
                    documents.append(TranscriptDocument(
                        source_name=os.path.basename(audio_file), segments=segments,
                    ))
                    succeeded += 1

                done_duration += file_duration
        finally:
            fw_logger.removeHandler(retry_handler)

        if succeeded == 0:
            result_queue.put(("error", "err_transcription_failed", {}))
            return

        emit_progress(("w_formatting", {}), 98)
        rendered = formatting.render_html(
            documents,
            speaker_label=options.speaker_label,
            timestamps=options.timestamps,
            failed_label=options.failed_label,
            title=os.path.splitext(os.path.basename(output_file))[0],
            ui_strings=options.ui_strings,
        )

        emit_progress(("w_saving", {}), 99)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(rendered)

        emit_progress(("w_complete", {}), 100)
        result_queue.put(("finished", output_file))

    except Exception as e:
        logger.error(f"Transcription worker process error: {e}", exc_info=True)
        result_queue.put(("error", "err_generic", {"detail": str(e)}))


def _transcribe_one(
    audio_file: str,
    transcriber: "Transcriber",
    options: "TranscriptionOptions",
    file_duration: float,
    emit_progress,
) -> Optional[List["Segment"]]:
    """
    Run one file's decode -> transcribe -> speaker id -> Hebrew correction.

    emit_progress here is already file-local (0-100 covering just this
    file's own work) - the caller in run_transcription_process does the
    duration-weighted rescale into the batch's overall percentage.

    Reassigns transcriber.progress_callback for the duration of this call.
    Transcriber.transcribe() reports its own progress on a fixed absolute
    15-90 sub-range, written back when a worker run only ever handled one
    file (see core/transcriber.py). Remapping that fixed range back onto
    this file's local 0-100 scale is what lets a single already-loaded
    Transcriber be reused, unmodified, across every file in a batch, instead
    of paying the model-load cost again per file.

    Returns None (rather than raising) if this file's transcription itself
    failed, so one bad file can be caught and skipped by the caller without
    losing the rest of the batch.
    """
    def from_transcriber_scale(message, percent: int) -> None:
        # Transcriber emits 15 at the start of transcribe() and climbs to 90
        # as segments complete; map that onto this file's own 5-90 local
        # band (leaving 0-5 for decoding and 90-100 for speakers/correction
        # below). A stray 0 (Transcriber's own error sentinel) clamps to 0
        # rather than going negative - the file is about to be marked
        # failed regardless of the exact number shown at that instant.
        local = max(0, min(100, round(5 + (percent - 15) / 75 * 85)))
        emit_progress(message, local)

    transcriber.progress_callback = from_transcriber_scale

    channels, two_party = _prepare_audio(audio_file, options, file_duration, emit_progress)

    if two_party:
        segments = _transcribe_per_channel(transcriber, channels, file_duration)
    else:
        # Hand over the decoded array when we have one so the file is not
        # decoded twice; fall back to the path if decoding failed.
        source = audio_file
        if channels is not None:
            from speech_to_text.core import audio_source
            source = audio_source.to_mono(channels)
        segments = transcriber.transcribe(source, total_duration_seconds=file_duration)

    if segments is None:
        return None

    if not two_party:
        _identify_speakers(segments, channels, options, emit_progress)

    _correct_hebrew(segments, options, emit_progress)

    emit_progress(("w_transcription_done", {}), 100)
    return segments


def _prepare_audio(
    audio_file: str, options, file_duration: float, emit_progress
) -> Tuple[Optional[list], bool]:
    """
    Decode the file and decide which speaker-separation path applies.

    Returns (channels, two_party). Decoding is skipped entirely when speaker
    identification is off, since then nothing needs the samples and
    faster-whisper can open the file itself as it always did.
    """
    if not options.identify_speakers:
        return None, False

    emit_progress(("w_analyzing_audio", {}), 2)
    from speech_to_text.core import audio_source

    channels, two_party = audio_source.load(audio_file)
    if two_party:
        emit_progress(("w_stereo_detected", {}), 5)
    return channels, two_party


def _transcribe_per_channel(transcriber, channels, file_duration: float):
    """
    Transcribe each channel separately - the exact path.

    When a recording genuinely has one speaker per channel, attribution needs
    no model and carries no error: whoever is on channel 0 is speaker 0. The
    cost is that transcription runs once per channel, roughly doubling the
    wall-clock time, which the GUI's estimate accounts for.
    """
    collected = []
    for index, channel in enumerate(channels[:2]):
        segments = transcriber.transcribe(
            channel, total_duration_seconds=file_duration
        )
        if not segments:
            continue
        for segment in segments:
            segment.speaker = index
        collected.extend(segments)

    # Interleave the two channels back into conversational order.
    collected.sort(key=lambda s: s.start)
    return collected


def _identify_speakers(segments, channels, options, emit_progress):
    """
    Run diarization and attach speakers, in place.

    Deliberately non-fatal in every failure mode. Diarization is an
    enhancement; a missing model, an absent dependency or a machine that is
    offline on first run must cost speaker labels and nothing else. Losing a
    completed transcript because the nice-to-have failed would be indefensible
    given how long transcription takes.
    """
    if not options.identify_speakers or channels is None or not segments:
        return

    try:
        from speech_to_text.core import audio_source, diarization

        emit_progress(("w_identifying_speakers", {}), 90)

        if not diarization.models_present():
            emit_progress(("w_downloading_diarization", {}), 90)
            diarization.ensure_models()

        mono = audio_source.to_mono(channels)

        def on_progress(processed: int, total: int) -> None:
            if total > 0:
                emit_progress(
                    ("w_identifying_speakers", {}),
                    90 + int(min(processed / total, 1.0) * 7),
                )

        spans = diarization.diarize(
            mono,
            sample_rate=audio_source.SAMPLE_RATE,
            num_speakers=options.num_speakers,
            progress=on_progress,
        )
        diarization.assign_speakers(segments, spans)

    except Exception as e:
        logger.warning(f"Speaker identification skipped: {e}", exc_info=True)
        emit_progress(("w_speakers_unavailable", {}), 97)


def _correct_hebrew(segments, options, emit_progress):
    """
    Fix misrecognised domain terms, in place.

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

        emit_progress(("w_correcting_terms", {}), 98)
        changes = hebrew_correct.correct(segments, terms)
        if changes:
            logger.info(f"Applied {len(changes)} Hebrew term correction(s)")

    except Exception as e:
        logger.warning(f"Hebrew term correction skipped: {e}", exc_info=True)
