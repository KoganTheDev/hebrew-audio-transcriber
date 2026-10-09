"""Core Transcription Module
Handles the actual transcription process.
"""

import ctypes
import importlib.util
import logging
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import config
from core.formatting import format_mmss
from core.hebrew_text import isolate_rtl
from core.progress_scale import (
    STATUS_ONLY_PERCENT,
    TRANSCRIBER_LOAD_START_PERCENT,
    TRANSCRIBER_MODEL_LOADED_PERCENT,
    TRANSCRIBER_TRANSCRIBE_END_PERCENT,
    TRANSCRIBER_TRANSCRIBE_SPAN,
    WORK_PHASE_PREPARE,
    WORK_PHASE_STARTED,
)
from core.segments import Segment, Word

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)

_cuda_runtime_preloaded = False


def _preload_cuda_runtime_libraries() -> None:
    """Preload the pip-installed cuBLAS/cuDNN (the `gpu` extra) by absolute
    path, before any CUDA work.

    ctranslate2 first needs them on the first GPU encode, and by then changing
    PATH/LD_LIBRARY_PATH is useless - the search path is fixed at process
    start. A no-op without the extra (find_spec raises ModuleNotFoundError on
    the missing `nvidia` parent, which is caught); load_model then falls back
    to CPU.
    """
    global _cuda_runtime_preloaded
    if _cuda_runtime_preloaded:
        return
    _cuda_runtime_preloaded = True

    is_windows = platform.system() == "Windows"
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(package)
        except (ModuleNotFoundError, ImportError, ValueError):
            continue
        if spec is None or not spec.submodule_search_locations:
            continue
        package_dir = Path(next(iter(spec.submodule_search_locations)))
        lib_dir = package_dir / ("bin" if is_windows else "lib")
        if not lib_dir.is_dir():
            continue
        if is_windows:
            try:
                os.add_dll_directory(str(lib_dir))
            except OSError:
                logger.debug(f"Could not add DLL directory {lib_dir}", exc_info=True)
        else:
            for shared_object in sorted(lib_dir.glob("*.so.*")):
                try:
                    ctypes.CDLL(str(shared_object), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    logger.debug(f"Could not preload {shared_object}", exc_info=True)


# Exceptions meaning "could not reach the model", not "the model is wrong".
# Matched by class name, since importing requests/huggingface_hub here would
# undo the guarded faster_whisper import. LocalEntryNotFoundError is the key
# one: no network AND nothing cached - a first run offline. HfHubHTTPError is
# deliberately absent: a 404 did reach the network.
_NETWORK_FAILURE_NAMES = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
        "LocalEntryNotFoundError",
        "OfflineModeIsEnabled",
        "NewConnectionError",
        "MaxRetryError",
    }
)


def _is_network_failure(error: BaseException) -> bool:
    """Whether this exception means the network, not the model."""
    seen: set[int] = set()
    queue: list[BaseException | None] = [error]
    while queue:
        current = queue.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for klass in type(current).__mro__:
            if klass.__name__ in _NETWORK_FAILURE_NAMES:
                return True
        # A hub failure usually arrives wrapped, with the socket error that
        # actually happened as its cause.
        queue.append(current.__cause__)
        queue.append(current.__context__)
    return False


class Transcriber:
    """Handles speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = config.DEFAULT_MODEL,
        device: str = "cpu",
        language: str = config.LANGUAGE,
        progress_callback: Callable | None = None,
        compute_type: str | None = None,
        beam_size: int | None = None,
        cpu_threads: int | None = None,
        num_workers: int | None = None,
        work_callback: Callable | None = None,
        phase_callback: Callable | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.progress_callback = progress_callback or self._default_callback
        # The time estimate's inputs - measurements, not a bar position (see
        # core/progress_scale.py). File-local; core/worker.py makes them
        # batch-wide. No-ops by default.
        self.work_callback = work_callback or self._default_work_callback
        self.phase_callback = phase_callback or self._default_phase_callback
        # Any, not Optional[WhisperModel]: WhisperModel is itself None when
        # faster-whisper is not installed (see the import guard above), so
        # there is no static type here to be Optional of.
        self.model: Any = None
        # Set when a load fails, so the caller can tell offline from broken.
        self.load_failed_on_network = False
        # Why the last transcribe() returned None.
        self.last_transcribe_error: str | None = None
        # None means the production default (config.compute_type_for_device,
        # config.BEAM_SIZE, ctranslate2's own thread count); explicit values
        # let tests/eval/compare_models.py sweep them.
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        logger.debug(
            f"Transcriber initialized: model={model_size}, device={device}, lang={language}"
        )

    @property
    def model_repo(self) -> str:
        """What faster-whisper loads: config.MODELS' "repo", or the name itself
        for a raw Whisper size or repo id (the eval harness uses those).
        """
        entry = config.MODELS.get(self.model_size)
        # cast, not str(): config.MODELS holds heterogeneous per-model values,
        # so "repo" types as object even though every entry's is a str.
        return cast(str, entry["repo"]) if entry else self.model_size

    @staticmethod
    def _default_callback(message: tuple[str, dict[str, Any]], progress: int) -> None:
        """Default progress callback."""
        pass

    @staticmethod
    def _default_work_callback(audio_done: float, audio_total: float) -> None:
        """Default work callback - see __init__ for why this exists."""
        pass

    @staticmethod
    def _default_phase_callback(name: str, seconds: float | None) -> None:
        """Default phase callback - see __init__ for why this exists."""
        pass

    def load_model(self) -> bool:
        """Load the Whisper model, retrying once on CPU if CUDA fails.

        A CUDA recommendation is a guess from nvidia-smi; driver mismatches or
        too little VRAM only surface here, and a machine that works on CPU
        should not fail on its GPU path. Unmeasured: no NVIDIA GPU on the
        development machine.
        """
        try:
            if not WhisperModel:
                logger.error("faster-whisper package not installed")
                return False

            logger.info(f"Loading {self.model_size} model on {self.device}...")
            # Loading-model phase occupies 5-15% of the overall progress bar
            # (see run_transcription_process in core/worker.py for the full
            # phase breakdown).
            # Progress messages are (i18n key, params) tuples, not text -
            # this module runs in the worker process, which knows nothing
            # about the UI language; the GUI renders keys at display time.
            self.progress_callback(
                ("w_loading_model", {"model": self.model_size}), TRANSCRIBER_LOAD_START_PERCENT
            )

            self._load_on(self.device)

            logger.info(f"✓ Model loaded successfully: {self.model_size} ({self.device})")
            self.progress_callback(
                ("w_model_loaded", {"model": self.model_size}), TRANSCRIBER_MODEL_LOADED_PERCENT
            )
            return True

        except Exception as e:
            if self.device == "cuda":
                logger.warning(
                    f"CUDA model load failed ({e}); falling back to CPU. "
                    "This fallback is untested on real GPU hardware - see "
                    "load_model()'s docstring.",
                    exc_info=True,
                )
                try:
                    self.device = "cpu"
                    self._load_on(self.device)
                    logger.info(
                        f"✓ Model loaded successfully: {self.model_size} (cpu, after CUDA fallback)"
                    )
                    self.progress_callback(
                        ("w_model_loaded", {"model": self.model_size}),
                        TRANSCRIBER_MODEL_LOADED_PERCENT,
                    )
                    return True
                except Exception as fallback_error:
                    e = fallback_error

            self.load_failed_on_network = _is_network_failure(e)
            logger.error(
                f"Failed to load {self.model_size} model: {e}"
                f"{' (network unreachable)' if self.load_failed_on_network else ''}",
                exc_info=True,
            )
            self.progress_callback(("w_error_loading", {"detail": str(e)}), STATUS_ONLY_PERCENT)
            return False

    def _fetch_weights(self) -> str | None:
        """Download the model with progress and return its local path, or None
        to let WhisperModel download silently as usual.

        WhisperModel gives no progress for a 1.6-3.1 GB first download, so the
        app looked hung for up to an hour. The progress is a FILE count with
        the total size, because bytes are not observable: snapshot_download's
        tqdm_class only sees the outer per-file bar (huggingface_hub 0.36), and
        the xet backend stages blobs outside the cache until the end. Any
        failure falls back to the plain path.
        """
        try:
            from huggingface_hub import snapshot_download
            from tqdm.auto import tqdm as _tqdm
        except Exception as e:  # pragma: no cover - only if the hub/tqdm move
            logger.debug(f"Progress-reporting download unavailable ({e}); using the plain path")
            return None

        entry = config.MODELS.get(self.model_size) or {}
        size_text = cast(str, entry.get("download_size") or "")
        emit = self.progress_callback

        class _ReportingTqdm(_tqdm):  # type: ignore[misc]  # tqdm ships no types
            def update(self, n: int | None = 1) -> bool | None:
                out: bool | None = super().update(n)
                try:
                    total = int(self.total or 0)
                    if total > 0:
                        emit(
                            (
                                "w_downloading_model",
                                {
                                    "done": int(self.n or 0),
                                    "total": total,
                                    "size": size_text,
                                },
                            ),
                            TRANSCRIBER_LOAD_START_PERCENT,
                        )
                except Exception:  # pragma: no cover - never break a download
                    pass
                return out

        try:
            return snapshot_download(
                repo_id=config.hf_repo_id(self.model_repo),
                cache_dir=config.MODEL_DOWNLOAD_ROOT,
                tqdm_class=_ReportingTqdm,
            )
        except Exception as e:
            # Not fatal on its own: WhisperModel gets its turn next and may
            # succeed from a partial cache, and huggingface_hub keeps its
            # partial files so a retry resumes rather than starting over.
            logger.warning(
                f"Progress-reporting download did not finish ({e}); using the plain path"
            )
            return None

    def _load_on(self, device: str) -> None:
        """WhisperModel for `device`, with unset knobs at production defaults
        (shared by load_model's CPU retry). Thread counts stay ctranslate2's
        own: pinning them measured no repeatable win on a 4-core machine.
        """
        if device == "cuda":
            _preload_cuda_runtime_libraries()

        compute_type = self.compute_type or config.compute_type_for_device(device)
        kwargs: dict[str, Any] = dict(
            device=device,
            compute_type=compute_type,
            # Absolute, resolved once at import time: a relative path would
            # resolve against the working directory, and the app can be
            # launched from anywhere. See config.MODEL_DOWNLOAD_ROOT.
            download_root=config.MODEL_DOWNLOAD_ROOT,
        )
        if self.cpu_threads is not None:
            kwargs["cpu_threads"] = self.cpu_threads
        if self.num_workers is not None:
            kwargs["num_workers"] = self.num_workers

        # A local path when the progress-reporting download ran, otherwise the
        # repo id, leaving WhisperModel to fetch it exactly as it always has.
        target = self._fetch_weights() or self.model_repo
        self.model = WhisperModel(target, **kwargs)

    def transcribe(
        self, audio_file: Any, total_duration_seconds: float = 0
    ) -> list[Segment] | None:
        """Transcribe audio to structured segments.

        Args:
            audio_file: A path, or a float32 mono 16 kHz array (lets the
                stereo path transcribe one channel without temp files).
            total_duration_seconds: The probed audio length, which makes the
                percentage accurate; without it progress is a rough estimate.

        Returns:
            List of Segment (with per-word timings and confidences), or None
            if error. Callers that just want text use
            core.segments.plain_text.

        """
        if not self.model:
            logger.error("Model not loaded - call load_model() first")
            self.progress_callback(("w_model_not_loaded", {}), STATUS_ONLY_PERCENT)
            return None

        try:
            return self._transcribe_once(audio_file, total_duration_seconds)
        except Exception as e:
            if self.device == "cuda":
                # A missing CUDA library only fails on the first encode, after
                # load_model succeeded - fall back to CPU, as load_model does.
                logger.warning(
                    f"CUDA transcription failed ({e}); reloading model on "
                    "CPU and retrying this file once.",
                    exc_info=True,
                )
                try:
                    self.device = "cpu"
                    self._load_on(self.device)
                    return self._transcribe_once(audio_file, total_duration_seconds)
                except Exception as fallback_error:
                    e = fallback_error

            logger.error(f"Transcription failed: {e}", exc_info=True)
            self.last_transcribe_error = str(e)
            # Status-only, not 0: inside a batch the worker rescales this,
            # and a 0 would drag the bar back to the start of the failed file.
            self.progress_callback(("w_error", {"detail": str(e)}), STATUS_ONLY_PERCENT)
            return None

    def _transcribe_once(self, audio_file: Any, total_duration_seconds: float = 0) -> list[Segment]:
        """Do the actual transcription work, letting any failure propagate.

        Split out of transcribe() so a CUDA runtime failure can be retried
        once on CPU without duplicating this whole body - see transcribe().
        Any failure propagates to the caller (transcribe()) uncaught.
        """
        logger.info(f"Starting transcription: {audio_file}")
        logger.debug(f"Language: {self.language}, Device: {self.device}")

        # Transcribing phase occupies 15-90% of the overall progress bar.
        self.progress_callback(("w_starting", {}), TRANSCRIBER_MODEL_LOADED_PERCENT)

        # The stretch between here and the first Segment is the longest
        # stretch of the whole run with nothing to report: model.transcribe()
        # runs Silero VAD over the entire file and decodes the first ~30s
        # window before it yields anything at all. Measured on this machine:
        # 67s on a 15-minute file, all of it at a fixed percentage. Timing it
        # as its own phase is what lets the GUI say "this is a known step
        # that costs this much" instead of showing a bar that has stopped.
        prepare_start = time.perf_counter()
        self.phase_callback(WORK_PHASE_PREPARE, WORK_PHASE_STARTED)

        segments, info = self.model.transcribe(
            audio_file,
            language=self.language,
            beam_size=self.beam_size if self.beam_size is not None else config.BEAM_SIZE,
            # Per-word timings and confidences. Needed twice over: word
            # boundaries are what let diarization attribute a speaker
            # change that happens mid-segment, and word probabilities are
            # what let the Hebrew correction pass touch only the words the
            # model was unsure about. Load-bearing - do not turn off to
            # save time (see core/worker.py's module docstring).
            word_timestamps=True,
            vad_filter=config.VAD_FILTER,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        logger.debug(f"Transcription info: {info}")

        # duration_after_vad is logged, not used as the work denominator:
        # skipped silence already shows as the position jumping. Read with
        # _as_float, defensively, as in _to_segment.
        speech_seconds = _as_float(
            getattr(info, "duration_after_vad", None), total_duration_seconds
        )
        logger.debug(
            f"Decoding {speech_seconds:.1f}s of speech "
            f"out of {total_duration_seconds:.1f}s of audio"
        )
        self.phase_callback(WORK_PHASE_PREPARE, time.perf_counter() - prepare_start)

        collected: list[Segment] = []
        segment_count = 0

        # 'segments' is a lazy generator - faster-whisper decodes one
        # segment at a time as it's iterated. Iterating it directly
        # (instead of materializing it with list() first) is what makes
        # per-segment progress updates reflect real, ongoing work rather
        # than firing all at once after decoding has already finished.
        for segment in segments:
            segment_count += 1
            try:
                segment_preview = segment.text[:50] if segment.text else "(empty)"
                # The preview is often Hebrew, and it's the last thing on
                # the line - LOG_FORMAT (app.py) puts %(message)s after
                # only LTR fields. Isolated so a trailing neutral
                # character (faster-whisper leaves a comma on truncated
                # segments) resolves against this LTR line instead of
                # reordering into the Hebrew. See hebrew_text.isolate_rtl.
                logger.debug(f"Segment {segment_count}: {isolate_rtl(segment_preview)}")
            except Exception:
                pass  # Skip debug logging if segment attributes are problematic

            if segment.text:
                collected.append(_to_segment(segment))

            segment_end = getattr(segment, "end", None)
            message: tuple[str, dict[str, Any]]
            if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                # Real progress: how far into the audio this segment ends.
                fraction = min(segment_end / total_duration_seconds, 1.0)
                message = (
                    "w_transcribing_time",
                    {
                        "position": format_mmss(segment_end),
                        "total": format_mmss(total_duration_seconds),
                    },
                )
            else:
                # No reliable duration to measure against (shouldn't
                # normally happen - the GUI always probes the real
                # duration first) - fall back to a soft, ever-increasing
                # estimate that never claims to reach completion.
                fraction = min(0.03 * segment_count, 0.95)
                message = ("w_transcribing_seg", {"n": segment_count})

            progress = TRANSCRIBER_MODEL_LOADED_PERCENT + int(
                fraction * TRANSCRIBER_TRANSCRIBE_SPAN
            )
            self.progress_callback(message, progress)

            # The same fact in audio-seconds, for the clock - only with a real
            # duration, since a made-up one gives a confidently wrong ETA.
            if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                self.work_callback(
                    min(float(segment_end), total_duration_seconds),
                    total_duration_seconds,
                )

        logger.info(f"✓ Transcription complete: {len(collected)} segments")
        # This file's audio is now fully accounted for, which the last
        # segment's end does NOT say on its own: VAD trims trailing silence,
        # so a recording that ends quietly stops yielding segments well
        # short of its own length. Without this the batch's audio_done would
        # never reach audio_total and the ETA would keep a phantom tail.
        if total_duration_seconds > 0:
            self.work_callback(total_duration_seconds, total_duration_seconds)
        self.progress_callback(("w_transcription_done", {}), TRANSCRIBER_TRANSCRIBE_END_PERCENT)
        return collected


def _to_segment(raw: Any) -> Segment:
    """Convert a faster-whisper Segment into ours, reading every attribute
    defensively: the type changes across releases and `words` can be None.
    Missing timings become 0.0, missing confidence 1.0 - so the correction
    pass leaves the word alone rather than acting on absent data.
    """
    words = []
    for raw_word in getattr(raw, "words", None) or []:
        word_text = getattr(raw_word, "word", None)
        if not isinstance(word_text, str):
            continue
        words.append(
            Word(
                start=_as_float(getattr(raw_word, "start", None), 0.0),
                end=_as_float(getattr(raw_word, "end", None), 0.0),
                text=word_text,
                probability=_as_float(getattr(raw_word, "probability", None), 1.0),
            )
        )

    return Segment(
        start=_as_float(getattr(raw, "start", None), 0.0),
        end=_as_float(getattr(raw, "end", None), 0.0),
        text=raw.text,
        words=words,
    )


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
