"""Background QThreads used by MainWindow: bridges from worker processes
(see core/__init__.py for why those are separate) to Qt signals, plus a
duration prober.
"""

import logging
import multiprocessing
import queue
import traceback

from PyQt5.QtCore import QThread, pyqtSignal

import config
from core.calibration import run_calibration_process
from core.progress_scale import STATUS_ONLY_PERCENT
from core.run_options import TranscriptionOptions
from core.worker import run_transcription_process
from gui.audio_utils import get_audio_duration
from gui.i18n import document_strings, t

logger = logging.getLogger(__name__)

# The `phase` signal's stand-in for the worker's None ("begun, duration
# unknown"): pyqtSignal has no optional float. Negative, since real values
# are durations.
PHASE_STARTED_SECONDS = -1.0

# How long to keep listening after the worker exits: it puts its result and
# then exits, so the result can still be in the pipe - and Queue.empty() is
# unreliable exactly then. Calling it "exited" early fails a successful run.
RESULT_GRACE_SECONDS = 2.0

# How long to wait for a terminated process to actually die before giving up
# on reaping it. terminate() is asynchronous; without a join() the child is
# never reaped and its handle leaks for the life of the Process object.
TERMINATE_GRACE_SECONDS = 5.0


def _terminate_and_reap(process: "multiprocessing.Process | None") -> None:
    """Terminate and join a worker process, so nothing is left unreaped;
    kill() if it ignores terminate (a child wedged in native inference would
    keep burning cores).
    """
    if process is None or not process.is_alive():
        return
    process.terminate()
    process.join(timeout=TERMINATE_GRACE_SECONDS)
    if process.is_alive():
        logger.warning("worker process ignored terminate(); killing it")
        process.kill()
        process.join(timeout=TERMINATE_GRACE_SECONDS)


class TranscriptionThread(QThread):
    """Runs the transcription in a worker process (core.worker) and relays
    its progress and result as Qt signals.
    """

    # progress/error carry (i18n key, format params) rather than rendered
    # text - the worker process doesn't know the UI language, and rendering
    # at display time lets a mid-run language toggle re-render live status.
    progress = pyqtSignal(str, dict, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str, dict)
    # The time estimate's inputs (see core/progress_scale.py), separate from
    # `progress`: measurements, not a bar position. `phase` uses
    # PHASE_STARTED_SECONDS for "begun".
    work = pyqtSignal(float, float, float)
    phase = pyqtSignal(str, float, float)
    # 1-based index of a file the batch could not transcribe. Its own signal
    # rather than an error: the batch has NOT failed, it is carrying on, and
    # routing this through `error` would tear the run down over one bad file.
    file_failed = pyqtSignal(int)

    def __init__(
        self,
        audio_files: list[str],
        model_size: str,
        device: str,
        durations: list[float] | None = None,
        options: TranscriptionOptions | None = None,
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
            self.options.terms_file = config.resolve_terms_path()
        self._is_running = True
        self._process: multiprocessing.Process | None = None
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
            # Below the worker's first report (BATCH_INIT_PERCENT), so the bar
            # only moves forward.
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
                # Drain every queued message before checking for a result, or
                # a fast run's last reports (to 100%) are lost behind it.
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
                except queue.Empty:
                    pass
                else:
                    self._emit_result(kind, payload)
                    return

                if not self._process.is_alive():
                    # Not result_queue.empty() - see RESULT_GRACE_SECONDS.
                    if self._drain_final_result(progress_queue, result_queue):
                        return
                    self.error.emit("err_worker_exited", {})
                    return

            self.error.emit("err_cancelled", {})

        except Exception as e:
            logger.error(f"TranscriptionThread error: {e}", exc_info=True)
            self.error.emit("err_generic", {"detail": str(e), "traceback": traceback.format_exc()})
        finally:
            _terminate_and_reap(self._process)

    def _drain_final_result(
        self,
        progress_queue: "multiprocessing.Queue",
        result_queue: "multiprocessing.Queue",
    ) -> bool:
        """After the child exits, relay what is left and emit its result.
        False means it died without one (err_worker_exited).
        """
        while True:
            try:
                kind, *payload = progress_queue.get_nowait()
            except queue.Empty:
                break
            self._relay_progress_message(kind, payload)

        try:
            kind, *payload = result_queue.get(timeout=RESULT_GRACE_SECONDS)
        except queue.Empty:
            return False

        self._emit_result(kind, payload)
        return True

    def _emit_result(self, kind: str, payload: list) -> None:
        """Turn one result_queue message into the matching Qt signal."""
        if kind == "finished":
            logger.info("✓ Transcription complete")
            self.finished.emit(payload[0])
        else:
            key, params = payload
            logger.error(f"Transcription worker error: {key} {params}")
            self.error.emit(key, params)

    def _relay_progress_message(self, kind: str, payload: list) -> None:
        """Relay one progress_queue message as a signal; no text, no arithmetic.

        "progress" carries a percentage; "status" is text only, sent with
        STATUS_ONLY_PERCENT ("update the text, not the bar"). "work" and
        "phase" go to their own signals: the bar and the clock answer
        different questions.
        """
        if kind == "progress":
            key, params, percent = payload
            self.progress.emit(key, params, percent)
        elif kind == "status":
            key, params = payload
            self.progress.emit(key, params, STATUS_ONLY_PERCENT)
        elif kind == "work":
            audio_done, audio_total, sent_at = payload
            self.work.emit(audio_done, audio_total, sent_at)
        elif kind == "phase":
            name, seconds, sent_at = payload
            self.phase.emit(name, PHASE_STARTED_SECONDS if seconds is None else seconds, sent_at)
        elif kind == "file_failed":
            self.file_failed.emit(payload[0])

    def stop(self):
        """Stop the thread and terminate the worker process if running."""
        self._is_running = False
        _terminate_and_reap(self._process)

    def _get_output_path(self) -> str:
        """Get output file path - named after the single file, or the batch's folder."""
        return config.output_path_for(self.audio_files)


class DurationProbeThread(QThread):
    """Reads audio durations off the GUI thread, one file at a time.

    Opening a OneDrive cloud-only file blocks until Windows downloads it, which
    froze the window per dropped file. A plain QThread: PyAV is safe in this
    process.
    """

    # path, duration in seconds, whether that duration was really probed
    probed = pyqtSignal(str, int, bool)

    def __init__(self, paths: list[str]):
        super().__init__()
        self._paths = list(paths)
        self._is_running = True

    def run(self) -> None:
        for path in self._paths:
            if not self._is_running:
                return
            try:
                seconds, exact = get_audio_duration(path)
            except Exception as e:
                # get_audio_duration already absorbs a probe failure and falls
                # back to a size estimate, so reaching here means even that
                # failed - the file has gone since it was dropped. Report it
                # as unprobed rather than letting one bad path end the queue
                # and leave every file behind it stuck on "reading length".
                logger.warning(f"Could not probe {path}: {e}")
                seconds, exact = 0, False
            self.probed.emit(path, seconds, exact)

    def stop(self) -> None:
        """Abandon the rest of the queue. The file list has moved on."""
        self._is_running = False


class CalibrationThread(QThread):
    """Runs the first-run calibration benchmark in a worker process (it loads
    faster-whisper). Not started when a cached result exists.
    """

    calibrated = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, cpu_cores: int, device: str):
        super().__init__()
        self.cpu_cores = cpu_cores
        self.device = device
        self._is_running = True
        self._process: multiprocessing.Process | None = None

    def run(self):
        logger.info(f"Starting background hardware calibration on {self.device}...")
        try:
            result_queue: multiprocessing.Queue = multiprocessing.Queue()
            self._process = multiprocessing.Process(
                target=run_calibration_process,
                args=(self.cpu_cores, self.device, result_queue),
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
            _terminate_and_reap(self._process)

    def stop(self):
        """Stop the thread and terminate the benchmark, so no result reaches
        slots whose widgets are being destroyed.
        """
        self._is_running = False
        _terminate_and_reap(self._process)
