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
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from speech_to_text.core.options import TranscriptionOptions

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
    audio_file: str,
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

    Overall progress bar phase breakdown (all emitted percentages are on
    this single 0-100 scale, so they only ever move forward):
      0-5%    initializing this process
      5-12%   loading the Whisper model (Transcriber.load_model)
      12-15%  decoding audio and checking for one-speaker-per-channel
      15-85%  transcribing, tracked by real audio position (Transcriber.transcribe)
      85-92%  identifying speakers (skipped when not requested, or when the
              channel split already answered the question exactly)
      92-98%  formatting + writing the output file
      100%    done
    """
    try:
        progress_queue.put(("progress", "w_initializing", {}, 2))

        from speech_to_text.core import formatting
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

        channels, two_party = _prepare_audio(audio_file, options, emit_progress)

        # DEBUG is required for faster-whisper to even emit the
        # "Processing segment at ..." line (it's gated by an isEnabledFor
        # check internally); the retry-threshold messages are unconditional
        # but only useful once we're already listening at this level.
        fw_logger = logging.getLogger("faster_whisper")
        fw_logger.setLevel(logging.DEBUG)
        retry_handler = _RetryStatusLogHandler(progress_queue)
        fw_logger.addHandler(retry_handler)
        try:
            if two_party:
                segments = _transcribe_per_channel(transcriber, channels, options)
            else:
                # Hand over the decoded array when we have one so the file is
                # not decoded twice; fall back to the path if decoding failed.
                source = audio_file
                if channels is not None:
                    from speech_to_text.core import audio_source
                    source = audio_source.to_mono(channels)
                segments = transcriber.transcribe(
                    source, total_duration_seconds=options.audio_duration_seconds
                )
        finally:
            fw_logger.removeHandler(retry_handler)

        if segments is None:
            result_queue.put(("error", "err_transcription_failed", {}))
            return

        if not two_party:
            _identify_speakers(segments, channels, options, emit_progress)

        _correct_hebrew(segments, options, emit_progress)

        emit_progress(("w_formatting", {}), 92)
        formatted_text = formatting.render(
            segments,
            speaker_label=options.speaker_label,
            timestamps=options.timestamps,
        )

        emit_progress(("w_saving", {}), 97)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        emit_progress(("w_complete", {}), 100)
        result_queue.put(("finished", output_file))

    except Exception as e:
        logger.error(f"Transcription worker process error: {e}", exc_info=True)
        result_queue.put(("error", "err_generic", {"detail": str(e)}))


def _prepare_audio(audio_file: str, options, emit_progress):
    """
    Decode the file and decide which speaker-separation path applies.

    Returns (channels, two_party). Decoding is skipped entirely when speaker
    identification is off, since then nothing needs the samples and
    faster-whisper can open the file itself as it always did.
    """
    if not options.identify_speakers:
        return None, False

    emit_progress(("w_analyzing_audio", {}), 12)
    from speech_to_text.core import audio_source

    channels, two_party = audio_source.load(audio_file)
    if two_party:
        emit_progress(("w_stereo_detected", {}), 15)
    return channels, two_party


def _transcribe_per_channel(transcriber, channels, options):
    """
    Transcribe each channel separately - the exact path.

    When a recording genuinely has one speaker per channel, attribution needs
    no model and carries no error: whoever is on channel 0 is speaker 0. The
    cost is that transcription runs once per channel, roughly doubling the
    wall-clock time, which the GUI's estimate accounts for.
    """
    per_channel_duration = options.audio_duration_seconds
    collected = []
    for index, channel in enumerate(channels[:2]):
        segments = transcriber.transcribe(
            channel, total_duration_seconds=per_channel_duration
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

        emit_progress(("w_identifying_speakers", {}), 85)

        if not diarization.models_present():
            emit_progress(("w_downloading_diarization", {}), 85)
            diarization.ensure_models()

        mono = audio_source.to_mono(channels)

        def on_progress(processed: int, total: int) -> None:
            if total > 0:
                emit_progress(
                    ("w_identifying_speakers", {}),
                    85 + int(min(processed / total, 1.0) * 7),
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
        emit_progress(("w_speakers_unavailable", {}), 92)


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

        emit_progress(("w_correcting_terms", {}), 92)
        changes = hebrew_correct.correct(segments, terms)
        if changes:
            logger.info(f"Applied {len(changes)} Hebrew term correction(s)")

    except Exception as e:
        logger.warning(f"Hebrew term correction skipped: {e}", exc_info=True)
