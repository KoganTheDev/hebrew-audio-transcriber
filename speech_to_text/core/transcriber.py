"""
Core Transcription Module
Handles the actual transcription process.
"""

import logging
from typing import Callable, List, Optional

from speech_to_text import config
from speech_to_text.core.formatting import format_mmss
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
        progress_callback: Optional[Callable] = None
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.progress_callback = progress_callback or self._default_callback
        self.model = None
        logger.debug(f"Transcriber initialized: model={model_size}, device={device}, lang={language}")

    @property
    def model_repo(self) -> str:
        """
        The identifier faster-whisper actually loads.

        config.MODELS keys are this app's own stable names; "repo" is the
        upstream address (a bare Whisper size, or a HuggingFace repo holding
        CTranslate2 weights). An unknown key falls through to itself so callers
        can still pass a raw Whisper size or repo id directly - useful for the
        evaluation harness, which benchmarks models that have no GUI card.
        """
        entry = config.MODELS.get(self.model_size)
        return entry["repo"] if entry else self.model_size
        
    @staticmethod
    def _default_callback(message, progress: int):
        """Default progress callback."""
        pass
        
    def load_model(self) -> bool:
        """Load the Whisper model."""
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
            self.progress_callback(("w_loading_model", {"model": self.model_size}), 5)

            self.model = WhisperModel(
                self.model_repo,
                device=self.device,
                compute_type=config.COMPUTE_TYPE,
                download_root="./whisper_models"
            )

            logger.info(f"✓ Model loaded successfully: {self.model_size} ({self.device})")
            self.progress_callback(("w_model_loaded", {"model": self.model_size}), 15)
            return True

        except Exception as e:
            logger.error(f"Failed to load {self.model_size} model: {e}", exc_info=True)
            self.progress_callback(("w_error_loading", {"detail": str(e)}), 0)
            return False
    
    def transcribe(
        self, audio_file, total_duration_seconds: float = 0
    ) -> Optional[List[Segment]]:
        """
        Transcribe audio to structured segments.

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
            self.progress_callback(("w_starting", {}), 15)

            segments, info = self.model.transcribe(
                audio_file,
                language=self.language,
                beam_size=config.BEAM_SIZE,
                # Per-word timings and confidences. Needed twice over: word
                # boundaries are what let diarization attribute a speaker
                # change that happens mid-segment, and word probabilities are
                # what let the Hebrew correction pass touch only the words the
                # model was unsure about.
                word_timestamps=True,
                vad_filter=config.VAD_FILTER,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            logger.debug(f"Transcription info: {info}")

            collected: List[Segment] = []
            segment_count = 0

            # 'segments' is a lazy generator — faster-whisper decodes one
            # segment at a time as it's iterated. Iterating it directly
            # (instead of materializing it with list() first) is what makes
            # per-segment progress updates reflect real, ongoing work rather
            # than firing all at once after decoding has already finished.
            for segment in segments:
                segment_count += 1
                try:
                    segment_preview = segment.text[:50] if segment.text else "(empty)"
                    logger.debug(f"Segment {segment_count}: {segment_preview}")
                except Exception:
                    pass  # Skip debug logging if segment attributes are problematic

                if segment.text:
                    collected.append(_to_segment(segment))

                segment_end = getattr(segment, "end", None)
                if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                    # Real progress: how far into the audio this segment ends.
                    fraction = min(segment_end / total_duration_seconds, 1.0)
                    message = ("w_transcribing_time", {
                        "position": format_mmss(segment_end),
                        "total": format_mmss(total_duration_seconds),
                    })
                else:
                    # No reliable duration to measure against (shouldn't
                    # normally happen — the GUI always probes the real
                    # duration first) — fall back to a soft, ever-increasing
                    # estimate that never claims to reach completion.
                    fraction = min(0.03 * segment_count, 0.95)
                    message = ("w_transcribing_seg", {"n": segment_count})

                progress = 15 + int(fraction * 75)
                self.progress_callback(message, progress)

            logger.info(f"✓ Transcription complete: {len(collected)} segments")
            self.progress_callback(("w_transcription_done", {}), 90)
            return collected

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            logger.debug(f"Error details: {type(e).__name__}")
            self.progress_callback(("w_error", {"detail": str(e)}), 0)
            return None
    

def _to_segment(raw) -> Segment:
    """
    Convert one faster-whisper Segment into our own Segment.

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
        words.append(Word(
            start=_as_float(getattr(raw_word, "start", None), 0.0),
            end=_as_float(getattr(raw_word, "end", None), 0.0),
            text=word_text,
            probability=_as_float(getattr(raw_word, "probability", None), 1.0),
        ))

    return Segment(
        start=_as_float(getattr(raw, "start", None), 0.0),
        end=_as_float(getattr(raw, "end", None), 0.0),
        text=raw.text,
        words=words,
    )


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
