"""
Background QThreads used by MainWindow.

Both threads exist purely to bridge a `multiprocessing.Process` (running in
a separate OS process, per the DLL-conflict note below) back into Qt
signals — neither does any heavy lifting itself.
"""

import os
import logging
import multiprocessing
import queue
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from speech_to_text import config
from speech_to_text.core.worker import run_transcription_process
from speech_to_text.core.calibration import run_calibration_process

logger = logging.getLogger(__name__)


class TranscriptionThread(QThread):
    """
    Worker thread for transcription.

    Runs the actual transcription in a separate OS process (see
    speech_to_text.core.worker) rather than in-process, and just relays
    progress/results as Qt signals. See worker.py for why: ctranslate2 and
    PyQt5 each bundle their own MSVCP140.dll on Windows, and loading both in
    one process causes an intermittent native crash.
    """
    # progress/error carry (i18n key, format params) rather than rendered
    # text - the worker process doesn't know the UI language, and rendering
    # at display time lets a mid-run language toggle re-render live status.
    progress = pyqtSignal(str, dict, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str, dict)

    def __init__(self, audio_file: str, model_size: str, device: str, audio_duration_seconds: float = 0):
        super().__init__()
        self.audio_file = audio_file
        self.model_size = model_size
        self.device = device
        self.audio_duration_seconds = audio_duration_seconds
        self._is_running = True
        self._process: Optional[multiprocessing.Process] = None
        logger.debug(f"TranscriptionThread created: {os.path.basename(audio_file)}")

    def run(self):
        """Launch the worker process and relay its progress/result as signals."""
        logger.info(f"TranscriptionThread started")
        try:
            # Kept below run_transcription_process's own first emission (2%)
            # so the bar only ever moves forward — see its phase breakdown.
            self.progress.emit("w_starting_thread", {}, 1)
            output_file = self._get_output_path()

            progress_queue: multiprocessing.Queue = multiprocessing.Queue()
            result_queue: multiprocessing.Queue = multiprocessing.Queue()

            self._process = multiprocessing.Process(
                target=run_transcription_process,
                args=(self.audio_file, self.model_size, self.device, output_file,
                      progress_queue, result_queue, self.audio_duration_seconds),
                daemon=True,
            )
            self._process.start()

            while self._is_running:
                # Drain every progress message currently queued (not just
                # one) before checking for a result. Otherwise, if the
                # worker process finishes quickly, several trailing
                # messages (e.g. "Saving output file...", 97 then
                # "Complete!", 100) can already be sitting in the queue
                # alongside the "finished" result — relaying only the first
                # one and then returning left the bar visibly stuck below
                # 100% even though the run had actually completed.
                got_any = False
                while True:
                    try:
                        kind, *payload = progress_queue.get_nowait()
                    except queue.Empty:
                        break
                    got_any = True
                    self._relay_progress_message(kind, payload)

                if not got_any:
                    try:
                        kind, *payload = progress_queue.get(timeout=0.2)
                        self._relay_progress_message(kind, payload)
                    except queue.Empty:
                        pass

                try:
                    kind, *payload = result_queue.get_nowait()
                    if kind == "finished":
                        logger.info("✓ Transcription complete")
                        self.finished.emit(payload[0])
                    else:
                        key, params = payload
                        logger.error(f"Transcription worker error: {key} {params}")
                        self.error.emit(key, params)
                    return
                except queue.Empty:
                    pass

                if not self._process.is_alive() and result_queue.empty():
                    self.error.emit("err_worker_exited", {})
                    return

            self.error.emit("err_cancelled", {})

        except Exception as e:
            logger.error(f"TranscriptionThread error: {e}", exc_info=True)
            self.error.emit("err_generic", {"detail": str(e)})
        finally:
            if self._process and self._process.is_alive():
                self._process.terminate()

    def _relay_progress_message(self, kind: str, payload: list) -> None:
        """
        Relay one progress_queue message as the progress signal.

        "progress" messages carry a real percentage. "status" messages (see
        core.worker._RetryStatusLogHandler) only describe background
        activity — e.g. faster-whisper retrying a hard-to-decode segment at
        a higher temperature — without a known percentage yet, so they're
        emitted with percent=-1 as a sentinel meaning "update the status
        text, but don't move the bar" (see TranscriptionStep.update_progress).

        This thread only relays (key, params) pairs; it never renders text.
        """
        if kind == "progress":
            key, params, percent = payload
            self.progress.emit(key, params, percent)
        elif kind == "status":
            key, params = payload
            self.progress.emit(key, params, -1)

    def stop(self):
        """Stop the thread and terminate the worker process if running."""
        self._is_running = False
        if self._process and self._process.is_alive():
            self._process.terminate()

    def _get_output_path(self) -> str:
        """Get output file path."""
        input_dir = os.path.dirname(self.audio_file)
        output_file = os.path.join(input_dir, config.OUTPUT_FILENAME)
        return output_file


class CalibrationThread(QThread):
    """
    Runs the one-time hardware calibration benchmark in the background.

    Only actually benchmarks on first run — HardwareDetector already loads
    a cached result synchronously if one exists, in which case MainWindow
    won't even start this thread. Same subprocess-isolation reasoning as
    TranscriptionThread: this loads faster-whisper, so it can't safely share
    a process with PyQt5.
    """
    calibrated = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, cpu_cores: int):
        super().__init__()
        self.cpu_cores = cpu_cores
        self._process: Optional[multiprocessing.Process] = None

    def run(self):
        logger.info("Starting background hardware calibration...")
        try:
            result_queue: multiprocessing.Queue = multiprocessing.Queue()
            self._process = multiprocessing.Process(
                target=run_calibration_process,
                args=(self.cpu_cores, result_queue),
                daemon=True,
            )
            self._process.start()

            while True:
                try:
                    kind, payload = result_queue.get(timeout=0.5)
                    if kind == "ok":
                        logger.info(f"Calibration finished: {payload:.4f}s/audio-s")
                        self.calibrated.emit(payload)
                    else:
                        logger.warning(f"Calibration failed: {payload}")
                        self.failed.emit(payload)
                    return
                except queue.Empty:
                    if not self._process.is_alive():
                        self.failed.emit("Calibration process exited unexpectedly")
                        return
        except Exception as e:
            logger.error(f"CalibrationThread error: {e}", exc_info=True)
            self.failed.emit(str(e))
