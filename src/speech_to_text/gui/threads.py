"""Background QThreads used by MainWindow.

Both threads exist purely to bridge a `multiprocessing.Process` (running in
a separate OS process, per the DLL-conflict note below) back into Qt
signals - neither does any heavy lifting itself.
"""

import logging
import multiprocessing
import queue
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from speech_to_text import config
from speech_to_text.core.calibration import run_calibration_process
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.core.progress_scale import STATUS_ONLY_PERCENT
from speech_to_text.core.worker import run_transcription_process
from speech_to_text.gui.i18n import document_strings, t

logger = logging.getLogger(__name__)


class TranscriptionThread(QThread):
    """Worker thread for transcription.

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

    def __init__(
        self,
        audio_files: list[str],
        model_size: str,
        device: str,
        durations: Optional[list[float]] = None,
        options: Optional[TranscriptionOptions] = None,
    ):
        super().__init__()
        self.audio_files = audio_files
        # Settings travel to the worker as one picklable object rather than a
        # long positional argument list forwarded through Process(args=...).
        # model_size/device/durations stay as explicit arguments because
        # they are what callers actually vary per run.
        self.options = options or TranscriptionOptions()
        self.options.model_size = model_size
        self.options.device = device
        self.options.audio_durations = durations or [0.0] * len(audio_files)
        # Speaker labels and the failed-file notice must be rendered here, in
        # the GUI process: the worker has no access to i18n and does not
        # know the UI language (see core/worker.py's module docstring).
        if self.options.speaker_label is None and self.options.identify_speakers:
            self.options.speaker_label = t("speaker_label")
        if self.options.failed_label is None:
            self.options.failed_label = t("file_failed_notice")
        # Same reason again, for the transcript page's own buttons and labels.
        if not self.options.ui_strings:
            self.options.ui_strings = document_strings()
        if self.options.terms_file is None:
            self.options.terms_file = config.TERMS_FILENAME
        self._is_running = True
        self._process: Optional[multiprocessing.Process] = None
        logger.debug(f"TranscriptionThread created: {len(audio_files)} file(s)")

    @property
    def model_size(self) -> str:
        return self.options.model_size

    @property
    def device(self) -> str:
        return self.options.device

    def run(self):  # noqa: C901 - scheduled for extraction
        """Launch the worker process and relay its progress/result as signals."""
        logger.info("TranscriptionThread started")
        try:
            # Kept below run_transcription_process's own first emission
            # (BATCH_INIT_PERCENT, see core/progress_scale.py) so the bar
            # only ever moves forward - see that module's phase breakdown.
            # Not expressed as BATCH_INIT_PERCENT - 1: nothing else derives
            # from this number, it only has to be smaller, and a bare 1 says
            # "before the worker process has said anything at all" more
            # plainly than a formula would.
            self.progress.emit("w_starting_thread", {}, 1)
            output_file = self._get_output_path()

            progress_queue: multiprocessing.Queue = multiprocessing.Queue()
            result_queue: multiprocessing.Queue = multiprocessing.Queue()

            self._process = multiprocessing.Process(
                target=run_transcription_process,
                args=(self.audio_files, output_file, self.options, progress_queue, result_queue),
                daemon=True,
            )
            self._process.start()

            while self._is_running:
                # Drain every progress message currently queued (not just
                # one) before checking for a result. Otherwise, if the
                # worker process finishes quickly, several trailing
                # messages (e.g. "Saving output file...", 97 then
                # "Complete!", 100) can already be sitting in the queue
                # alongside the "finished" result - relaying only the first
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
        """Relay one progress_queue message as the progress signal.

        "progress" messages carry a real percentage. "status" messages (see
        core.worker._RetryStatusLogHandler) only describe background
        activity - e.g. faster-whisper retrying a hard-to-decode segment at
        a higher temperature - without a known percentage yet, so they're
        emitted with percent=STATUS_ONLY_PERCENT as a sentinel meaning
        "update the status text, but don't move the bar" (see
        TranscriptionStep.update_progress).

        This thread only relays (key, params) pairs; it never renders text.
        """
        if kind == "progress":
            key, params, percent = payload
            self.progress.emit(key, params, percent)
        elif kind == "status":
            key, params = payload
            self.progress.emit(key, params, STATUS_ONLY_PERCENT)

    def stop(self):
        """Stop the thread and terminate the worker process if running."""
        self._is_running = False
        if self._process and self._process.is_alive():
            self._process.terminate()

    def _get_output_path(self) -> str:
        """Get output file path - named after the single file, or the batch's folder."""
        return config.output_path_for(self.audio_files)


class CalibrationThread(QThread):
    """Runs the one-time hardware calibration benchmark in the background.

    Only actually benchmarks on first run - HardwareDetector already loads
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
        self._is_running = True
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

            while self._is_running:
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
                        # A stop() that has just terminated the process gets
                        # here too, and that exit is expected rather than a
                        # failure - the flag is what tells the two apart.
                        if self._is_running:
                            self.failed.emit("Calibration process exited unexpectedly")
                        return
            logger.info("Calibration stopped before a result arrived")
        except Exception as e:
            logger.error(f"CalibrationThread error: {e}", exc_info=True)
            if self._is_running:
                self.failed.emit(str(e))
        finally:
            if self._process and self._process.is_alive():
                self._process.terminate()

    def stop(self):
        """Stop the thread and terminate the benchmark process if running.

        Same shape as TranscriptionThread.stop() above, and needed for the
        same reason even though the benchmark process is daemonic and so
        would never hold up interpreter exit on its own: what matters is
        the QThread and its two signals, which will happily deliver a
        result into slots whose widgets are already being destroyed (see
        MainWindow._detach_calibration_thread, and gui/focus.py for the
        one time this repo watched that happen).
        """
        self._is_running = False
        if self._process and self._process.is_alive():
            self._process.terminate()
