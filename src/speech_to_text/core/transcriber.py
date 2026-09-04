"""Core Transcription Module
Handles the actual transcription process.
"""

import logging
from typing import Any, Callable, Optional, cast

from speech_to_text import config
from speech_to_text.core.formatting import format_mmss
from speech_to_text.core.hebrew_text import isolate_rtl
from speech_to_text.core.progress_scale import (
    TRANSCRIBER_LOAD_START_PERCENT,
    TRANSCRIBER_MODEL_LOADED_PERCENT,
    TRANSCRIBER_TRANSCRIBE_END_PERCENT,
    TRANSCRIBER_TRANSCRIBE_SPAN,
)
from speech_to_text.core.segments import Segment, Word

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)


class Transcriber:
    """Handles speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = config.DEFAULT_MODEL,
        device: str = "cpu",
        language: str = config.LANGUAGE,
        progress_callback: Optional[Callable] = None,
        compute_type: Optional[str] = None,
        beam_size: Optional[int] = None,
        cpu_threads: Optional[int] = None,
        num_workers: Optional[int] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.progress_callback = progress_callback or self._default_callback
        # Any, not Optional[WhisperModel]: WhisperModel is itself None when
        # faster-whisper is not installed (see the import guard above), so
        # there is no static type here to be Optional of.
        self.model: Any = None
        # All four default to None so production behaviour (worker.py's call
        # site, which never passes them) is unchanged from before these
        # existed: compute_type resolves from config.compute_type_for_device
        # at load time (device-conditional - see that function's docstring),
        # beam_size from config.BEAM_SIZE, and cpu_threads/num_workers stay
        # unset (ctranslate2 picks its own thread count). Explicit values
        # exist so tests/eval/compare_models.py can sweep them without a
        # parallel construction path.
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        logger.debug(
            f"Transcriber initialized: model={model_size}, device={device}, lang={language}"
        )

    @property
    def model_repo(self) -> str:
        """The identifier faster-whisper actually loads.

        config.MODELS keys are this app's own stable names; "repo" is the
        upstream address (a bare Whisper size, or a HuggingFace repo holding
        CTranslate2 weights). An unknown key falls through to itself so callers
        can still pass a raw Whisper size or repo id directly - useful for the
        evaluation harness, which benchmarks models that have no GUI card.
        """
        entry = config.MODELS.get(self.model_size)
        # cast, not str(): config.MODELS holds heterogeneous per-model values,
        # so "repo" types as object even though every entry's is a str.
        return cast(str, entry["repo"]) if entry else self.model_size

    @staticmethod
    def _default_callback(message: tuple[str, dict[str, Any]], progress: int) -> None:
        """Default progress callback."""
        pass

    def load_model(self) -> bool:
        """Load the Whisper model.

        device="cuda" is reachable once gui/main_window.py wires up
        get_device_recommendation() (see hardware_detection.py) - but a CUDA
        recommendation is a guess from nvidia-smi output, not proof the
        ctranslate2/CUDA runtime actually initialises: a driver/CUDA-version
        mismatch, a half-installed driver, or too little free VRAM all
        surface only here, as an exception from WhisperModel() itself. NONE
        of that path has been exercised on real hardware - this development
        machine has no NVIDIA GPU at all (Intel Iris Xe only), so the retry
        below is reasoned about, not measured. If cuda load throws, retry
        once on cpu with a cpu-appropriate compute_type rather than
        surfacing a failure the user can do nothing useful with; a machine
        that would work fine on CPU should not fail just because its GPU
        path had a problem.
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

            logger.error(f"Failed to load {self.model_size} model: {e}", exc_info=True)
            self.progress_callback(("w_error_loading", {"detail": str(e)}), 0)
            return False

    def _load_on(self, device: str) -> None:
        """Construct WhisperModel for the given device, resolving every knob
        that is None to its production default. Split out of load_model() so
        the CUDA-fails-fall-back-to-CPU retry (see load_model's docstring)
        can call it a second time with device swapped, without duplicating
        the argument-resolution logic.

        cpu_threads/num_workers are left unset unless explicitly given -
        ctranslate2 picks its own thread count in that case. Phase B's
        measurement (see tests/eval/compare_models.py and the Stage 2
        report) found no repeatable win from pinning either on this 4-core
        machine, so production leaves them alone; the knobs exist so the
        eval harness can still sweep them.
        """
        compute_type = self.compute_type or config.compute_type_for_device(device)
        kwargs: dict[str, Any] = dict(
            device=device,
            compute_type=compute_type,
            # Absolute, resolved once at import time - see
            # config.MODEL_DOWNLOAD_ROOT's own comment for why this used to
            # be the relative literal "./whisper_models" and what that broke
            # once the console script could be launched from anywhere.
            download_root=config.MODEL_DOWNLOAD_ROOT,
        )
        if self.cpu_threads is not None:
            kwargs["cpu_threads"] = self.cpu_threads
        if self.num_workers is not None:
            kwargs["num_workers"] = self.num_workers

        self.model = WhisperModel(self.model_repo, **kwargs)

    def transcribe(
        self, audio_file: Any, total_duration_seconds: float = 0
    ) -> Optional[list[Segment]]:
        """Transcribe audio to structured segments.

        Args:
            audio_file: Path to an audio/video file, or a float32 mono 16 kHz
                numpy array. faster-whisper accepts either; the array form is
                what lets the stereo channel-split path transcribe one
                speaker's channel at a time without writing temp files
                (see core.audio_source).
            total_duration_seconds: Real audio length (from probing the file
                before transcription starts, see gui.audio_utils), used to
                turn each segment's timestamp into an accurate percentage of
                real work done. Without it, progress falls back to a rough
                per-segment estimate.

        Returns:
            List of Segment (with per-word timings and confidences), or None
            if error. Callers that just want text use
            core.segments.plain_text.

        """
        if not self.model:
            logger.error("Model not loaded - call load_model() first")
            self.progress_callback(("w_model_not_loaded", {}), 0)
            return None

        logger.info(f"Starting transcription: {audio_file}")
        logger.debug(f"Language: {self.language}, Device: {self.device}")

        try:
            # Transcribing phase occupies 15-90% of the overall progress bar.
            self.progress_callback(("w_starting", {}), TRANSCRIBER_MODEL_LOADED_PERCENT)

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
                    # the line - LOG_FORMAT (main.py) puts %(message)s after
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

            logger.info(f"✓ Transcription complete: {len(collected)} segments")
            self.progress_callback(("w_transcription_done", {}), TRANSCRIBER_TRANSCRIBE_END_PERCENT)
            return collected

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            logger.debug(f"Error details: {type(e).__name__}")
            self.progress_callback(("w_error", {"detail": str(e)}), 0)
            return None


def _to_segment(raw: Any) -> Segment:
    """Convert one faster-whisper Segment into our own Segment.

    Every attribute is read defensively. faster-whisper's segment type has
    changed shape across releases, `words` is None whenever word_timestamps
    is off, and the test suite feeds in MagicMocks whose attributes are mocks
    rather than numbers - none of which should be able to abort a
    transcription that has otherwise succeeded. Missing timings degrade to
    0.0, missing confidence degrades to 1.0 (i.e. "assume the model was sure",
    so the correction pass leaves the word alone rather than mangling it on
    the strength of absent data).
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
