"""
Core Transcription Module
Handles the actual transcription process.
"""

import os
import logging
import re
from typing import Optional, Callable

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)


def _format_mmss(seconds) -> str:
    """Format a seconds count as m:ss, tolerating non-numeric input."""
    try:
        total = max(int(seconds), 0)
    except (TypeError, ValueError):
        return "0:00"
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


class Transcriber:
    """Handles speech-to-text transcription."""
    
    def __init__(
        self,
        model_size: str = "medium",
        device: str = "cpu",
        language: str = "he",
        progress_callback: Optional[Callable] = None
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.progress_callback = progress_callback or self._default_callback
        self.model = None
        logger.debug(f"Transcriber initialized: model={model_size}, device={device}, lang={language}")
        
    @staticmethod
    def _default_callback(message: str, progress: int):
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
            self.progress_callback(f"Loading {self.model_size} model...", 5)

            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="int8",
                download_root="./whisper_models"
            )

            logger.info(f"✓ Model loaded successfully: {self.model_size} ({self.device})")
            self.progress_callback(f"Model loaded: {self.model_size}", 15)
            return True
            
        except Exception as e:
            logger.error(f"Failed to load {self.model_size} model: {e}", exc_info=True)
            self.progress_callback(f"Error loading model: {e}", 0)
            return False
    
    def transcribe(self, audio_file: str, total_duration_seconds: float = 0) -> Optional[str]:
        """
        Transcribe audio file to text.

        Args:
            audio_file: Path to audio/video file
            total_duration_seconds: Real audio length (from probing the file
                before transcription starts, see gui.audio_utils), used to
                turn each segment's timestamp into an accurate percentage of
                real work done. Without it, progress falls back to a rough
                per-segment estimate.

        Returns:
            Transcribed text or None if error
        """
        if not self.model:
            logger.error("Model not loaded - call load_model() first")
            self.progress_callback("Model not loaded", 0)
            return None

        logger.info(f"Starting transcription: {audio_file}")
        logger.debug(f"Language: {self.language}, Device: {self.device}")

        try:
            # Transcribing phase occupies 15-90% of the overall progress bar.
            self.progress_callback("Starting transcription...", 15)

            segments, info = self.model.transcribe(
                audio_file,
                language=self.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            logger.debug(f"Transcription info: {info}")

            transcribed_text = ""
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
                    # Add space before segment if not the first segment and text doesn't start with space
                    if transcribed_text and not transcribed_text.endswith(" "):
                        transcribed_text += " "
                    transcribed_text += segment.text

                segment_end = getattr(segment, "end", None)
                if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                    # Real progress: how far into the audio this segment ends.
                    fraction = min(segment_end / total_duration_seconds, 1.0)
                    message = (
                        f"Transcribing audio... {_format_mmss(segment_end)} "
                        f"/ {_format_mmss(total_duration_seconds)}"
                    )
                else:
                    # No reliable duration to measure against (shouldn't
                    # normally happen — the GUI always probes the real
                    # duration first) — fall back to a soft, ever-increasing
                    # estimate that never claims to reach completion.
                    fraction = min(0.03 * segment_count, 0.95)
                    message = f"Transcribing audio... segment {segment_count}"

                progress = 15 + int(fraction * 75)
                self.progress_callback(message, progress)

            logger.info(f"✓ Transcription complete: {len(transcribed_text)} characters")
            self.progress_callback("Transcription complete", 90)
            return transcribed_text

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            logger.debug(f"Error details: {type(e).__name__}")
            self.progress_callback(f"Error: {e}", 0)
            return None
    
    def format_output(self, text: str) -> str:
        """Format output with sentence breaks."""
        if not text:
            return ""
        
        try:
            sentences = re.split(r'(?<=[.!?])\s+', text)
            sentences = [s.strip() for s in sentences if s.strip()]
            return "\n".join(sentences)
        except Exception as e:
            logger.warning(f"Could not format output: {e}")
            return text
