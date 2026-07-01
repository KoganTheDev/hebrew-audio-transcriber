"""
Audio file utilities for the Speech-to-Text Transcriber GUI.
"""

import os
import logging

from speech_to_text import config

logger = logging.getLogger(__name__)


def get_audio_duration(file_path: str) -> int:
    """
    Get audio file duration in seconds.
    Try multiple methods and fall back to file size estimate.
    """
    try:
        # Try moviepy first
        from moviepy.editor import AudioFileClip
        try:
            clip = AudioFileClip(file_path)
            duration = int(clip.duration)
            clip.close()
            logger.debug(f"Got duration from moviepy: {duration}s")
            return duration
        except Exception as e:
            logger.debug(f"moviepy failed: {e}")
    except ImportError:
        logger.debug("moviepy not available")

    try:
        # Try librosa
        import librosa
        y, sr = librosa.load(file_path, sr=None)
        duration = int(librosa.get_duration(y=y, sr=sr))
        logger.debug(f"Got duration from librosa: {duration}s")
        return duration
    except ImportError:
        logger.debug("librosa not available")
    except Exception as e:
        logger.debug(f"librosa failed: {e}")

    # Fallback: estimate from file size
    # Typical: 128kbps MP3 ≈ 16 KB/sec, 192kbps ≈ 24 KB/sec
    # We use config.AUDIO_MINUTES_PER_100MB to keep the fallback estimate centralized.
    # This value represents average audio duration for a 100MB file in minutes.
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    estimated_seconds = int(file_size_mb * 60 * config.AUDIO_MINUTES_PER_100MB)
    logger.debug(f"Estimated duration from file size: {estimated_seconds}s ({estimated_seconds//60}m {estimated_seconds%60}s)")
    return estimated_seconds
