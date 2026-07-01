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
import logging
import multiprocessing

logger = logging.getLogger(__name__)


def run_transcription_process(
    audio_file: str,
    model_size: str,
    device: str,
    output_file: str,
    progress_queue: "multiprocessing.Queue",
    result_queue: "multiprocessing.Queue",
) -> None:
    """
    Entry point for the child process. Must stay import-light (no PyQt5).

    Puts ("progress", message, percent) tuples on progress_queue, and a
    single final ("finished", output_file) or ("error", message) on
    result_queue before exiting.
    """
    try:
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

        emit_progress("Transcribing audio...", 30)
        text = transcriber.transcribe(audio_file)

        if text is None:
            result_queue.put(("error", "Transcription failed"))
            return

        emit_progress("Formatting output...", 90)
        formatted_text = transcriber.format_output(text)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_text)

        emit_progress("Complete!", 100)
        result_queue.put(("finished", output_file))

    except Exception as e:
        logger.error(f"Transcription worker process error: {e}", exc_info=True)
        result_queue.put(("error", str(e)))
