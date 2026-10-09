"""Audio file utilities for the Speech-to-Text Transcriber GUI."""

import logging
import os

import config

logger = logging.getLogger(__name__)


def get_audio_duration(file_path: str) -> tuple[int, bool]:
    """The audio/video duration in seconds, read from container metadata.

    PyAV reads the header without decoding, so it is fast and exact. If the
    file cannot be opened at all, falls back to a size-based guess.

    Returns:
        (seconds, probed). probed=False means the guess was used - and the
        file is likely one faster-whisper cannot decode either, which the
        caller can now flag instead of failing minutes later in the worker.

    """
    try:
        import av

        container = av.open(file_path)
        try:
            if container.duration is not None:
                duration = int(container.duration / av.time_base)
                logger.debug(f"Got exact duration from container metadata: {duration}s")
                return duration, True
            # Some containers don't set an overall duration; fall back to the
            # longest individual stream's duration (still exact, not a guess).
            for stream in container.streams:
                if stream.duration is not None and stream.time_base is not None:
                    duration = int(stream.duration * stream.time_base)
                    logger.debug(f"Got exact duration from stream metadata: {duration}s")
                    return duration, True
        finally:
            container.close()
    except Exception as e:
        logger.warning(f"Could not read exact duration via av, falling back to estimate: {e}")

    # Size-based guess, guarded: a file deleted since it was selected must
    # degrade like any unreadable file, not raise into the drop handler.
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except OSError as e:
        logger.warning(f"Could not size {file_path}: {e}")
        return 0, False
    estimated_seconds = int(file_size_mb * 60 * config.AUDIO_MINUTES_PER_100MB)
    logger.warning(
        f"Using ESTIMATED duration (file could not be probed): "
        f"{estimated_seconds}s ({estimated_seconds // 60}m {estimated_seconds % 60}s)"
    )
    return estimated_seconds, False
