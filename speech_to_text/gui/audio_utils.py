"""
Audio file utilities for the Speech-to-Text Transcriber GUI.
"""

import os
import logging

from speech_to_text import config

logger = logging.getLogger(__name__)


def get_audio_duration(file_path: str) -> int:
    """
    Get the real audio/video duration in seconds by reading container
    metadata — not an estimate.

    Uses PyAV (the 'av' package), which is already a required dependency of
    faster-whisper, so no extra install is needed. This reads the container
    header directly rather than decoding the file, so it's fast and exact
    for essentially all formats faster-whisper/ffmpeg can handle. Falls back
    to a rough file-size-based guess only if the file can't be opened at all
    (e.g. corrupt/unsupported file) — that fallback is clearly logged as an
    estimate, since it is one.
    """
    try:
        import av
        container = av.open(file_path)
        try:
            if container.duration is not None:
                duration = int(container.duration / av.time_base)
                logger.debug(f"Got exact duration from container metadata: {duration}s")
                return duration
            # Some containers don't set an overall duration; fall back to the
            # longest individual stream's duration (still exact, not a guess).
            for stream in container.streams:
                if stream.duration is not None and stream.time_base is not None:
                    duration = int(stream.duration * stream.time_base)
                    logger.debug(f"Got exact duration from stream metadata: {duration}s")
                    return duration
        finally:
            container.close()
    except Exception as e:
        logger.warning(f"Could not read exact duration via av, falling back to estimate: {e}")

    # Last-resort fallback: a rough estimate from file size. Only reached if
    # the file couldn't be opened/probed at all.
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    estimated_seconds = int(file_size_mb * 60 * config.AUDIO_MINUTES_PER_100MB)
    logger.warning(
        f"Using ESTIMATED duration (file could not be probed): "
        f"{estimated_seconds}s ({estimated_seconds//60}m {estimated_seconds%60}s)"
    )
    return estimated_seconds
