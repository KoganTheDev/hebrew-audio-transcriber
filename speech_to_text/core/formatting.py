"""
Rendering structured segments into the output transcript file.

Split out of Transcriber because formatting stopped being a model concern
once segments carried timing and speaker data: the renderer needs to know
about turn merging, bidi control characters and speaker label templates,
none of which have anything to do with running a Whisper model.

Stdlib only, and no PyQt5 - this runs inside the worker process.
"""

import logging
import re
from typing import List

from speech_to_text.core.segments import Segment, plain_text

logger = logging.getLogger(__name__)


def format_plain(text: str) -> str:
    """
    Format a transcript blob with one sentence per line.

    This is the original pre-timestamps output format, kept intact so the
    app can still produce exactly what it produced before.
    """
    if not text:
        return ""

    try:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        return "\n".join(sentences)
    except Exception as e:
        logger.warning(f"Could not format output: {e}")
        return text


def render(segments: List[Segment]) -> str:
    """Render segments to the output transcript."""
    return format_plain(plain_text(segments))
