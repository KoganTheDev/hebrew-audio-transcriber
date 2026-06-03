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
            self.progress_callback("Loading model...", 0)
            
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="int8",
                download_root="./whisper_models"
            )
            
            logger.info(f"✓ Model loaded successfully: {self.model_size} ({self.device})")
            self.progress_callback(f"Model loaded: {self.model_size}", 100)
            return True
            
        except Exception as e:
            logger.error(f"Failed to load {self.model_size} model: {e}", exc_info=True)
            self.progress_callback(f"Error loading model: {e}", 0)
            return False
    
    def transcribe(self, audio_file: str) -> Optional[str]:
        """
        Transcribe audio file to text.
        
        Args:
            audio_file: Path to audio/video file
            
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
            self.progress_callback("Starting transcription...", 10)
            
            segments, info = self.model.transcribe(
                audio_file,
                language=self.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            logger.debug(f"Transcription info: {info}")
            segment_list = list(segments)
            logger.info(f"Processing {len(segment_list)} audio segments...")
            
            transcribed_text = ""
            
            for i, segment in enumerate(segment_list):
                # Try to log segment info safely
                try:
                    if hasattr(segment, 'start') and hasattr(segment, 'end'):
                        segment_preview = segment.text[:50] if segment.text else "(empty)"
                        logger.debug(f"Segment {i+1}/{len(segment_list)}: {segment_preview}")
                except Exception:
                    pass  # Skip debug logging if segment attributes are problematic
                
                if segment.text:
                    # Add space before segment if not the first segment and text doesn't start with space
                    if transcribed_text and not transcribed_text.endswith(" "):
                        transcribed_text += " "
                    transcribed_text += segment.text
                
                # Update progress
                progress = 10 + int((i / max(len(segment_list), 1)) * 80)
                self.progress_callback(
                    f"Transcribing: {i+1}/{len(segment_list)} segments",
                    progress
                )
            
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
