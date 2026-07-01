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

import os
import re
import logging
import multiprocessing

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
     lambda m: f"Analyzing audio near {m.group(1)}..."),
    (re.compile(r"^Compression ratio threshold is not met with temperature ([\d.]+)"),
     lambda m: f"Unclear audio — retrying at a higher decoding temperature ({m.group(1)})..."),
    (re.compile(r"^Log probability threshold is not met with temperature ([\d.]+)"),
     lambda m: f"Low-confidence result — retrying at a higher decoding temperature ({m.group(1)})..."),
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
        for pattern, to_message in _RETRY_LOG_PATTERNS:
            match = pattern.match(raw)
            if match:
                self._progress_queue.put(("status", to_message(match)))
                return


def run_transcription_process(
    audio_file: str,
    model_size: str,
    device: str,
    output_file: str,
    progress_queue: "multiprocessing.Queue",
    result_queue: "multiprocessing.Queue",
    audio_duration_seconds: float = 0,
) -> None:
    """
    Entry point for the child process. Must stay import-light (no PyQt5).

    Puts ("progress", message, percent) tuples on progress_queue for real
    percentage updates, and ("status", message) tuples for text-only
    updates (see _RetryStatusLogHandler) that describe background activity
    without claiming a percentage that isn't actually known yet. Puts a
    single final ("finished", output_file) or ("error", message) on
    result_queue before exiting.

    Overall progress bar phase breakdown (all emitted percentages are on
    this single 0-100 scale, so they only ever move forward):
      0-5%    initializing this process
      5-15%   loading the Whisper model (Transcriber.load_model)
      15-90%  transcribing, tracked by real audio position (Transcriber.transcribe)
      90-98%  formatting + writing the output file
      100%    done
    """
    try:
        progress_queue.put(("progress", "Initializing...", 2))

        from speech_to_text.core.transcriber import Transcriber

        def emit_progress(message: str, percent: int) -> None:
            progress_queue.put(("progress", message, percent))

        transcriber = Transcriber(
            model_size=model_size,
            device=device,
            progress_callback=emit_progress,
        )

        if not transcriber.load_model():
            result_queue.put(("error", "Failed to load transcription model"))
            return

        # DEBUG is required for faster-whisper to even emit the
        # "Processing segment at ..." line (it's gated by an isEnabledFor
        # check internally); the retry-threshold messages are unconditional
        # but only useful once we're already listening at this level.
        fw_logger = logging.getLogger("faster_whisper")
        fw_logger.setLevel(logging.DEBUG)
        retry_handler = _RetryStatusLogHandler(progress_queue)
        fw_logger.addHandler(retry_handler)
        try:
            text = transcriber.transcribe(audio_file, total_duration_seconds=audio_duration_seconds)
        finally:
            fw_logger.removeHandler(retry_handler)

        if text is None:
            result_queue.put(("error", "Transcription failed"))
            return

        emit_progress("Formatting output...", 92)
        formatted_text = transcriber.format_output(text)

        emit_progress("Saving output file...", 97)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        emit_progress("Complete!", 100)
        result_queue.put(("finished", output_file))

    except Exception as e:
        logger.error(f"Transcription worker process error: {e}", exc_info=True)
        result_queue.put(("error", str(e)))
