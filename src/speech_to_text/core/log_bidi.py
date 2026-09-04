"""Logging glue for visual-order console output - see the module comment in
core/hebrew_text.py above to_visual_order() for why this exists at all.
Kept separate from main.py so main.py stays wiring: which handler gets
which formatter, not why.
"""

import logging
import os
import sys

from speech_to_text.core.hebrew_text import to_visual_order


def visual_order_mode() -> str:
    """Resolve STT_LOG_BIDI to "visual" or "logical".

    "auto" (the default) resolves to visual on a Windows console tty and to
    logical everywhere else: no Windows console implements the Unicode
    Bidirectional Algorithm, so a Windows tty always needs the pre-reversed
    text to read correctly, while redirected output is headed for a file or
    a pager that a bidi-capable reader will open, where pre-reversed text
    would be wrong. The env var is the escape hatch for anyone on a
    terminal that does implement the UBA.
    """
    mode = os.environ.get("STT_LOG_BIDI", "auto").strip().lower()
    if mode in ("visual", "logical"):
        return mode
    return "visual" if (os.name == "nt" and sys.stdout.isatty()) else "logical"


class VisualOrderFormatter(logging.Formatter):
    """A logging.Formatter that reorders each formatted line into visual order
    before it reaches a non-bidi console. Applied per line, not to the
    whole formatted record as one blob, so a multi-line exception traceback
    is reordered line by line rather than as a single paragraph with the
    wrong boundaries.
    """

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if visual_order_mode() != "visual":
            return formatted
        return "\n".join(to_visual_order(line) for line in formatted.split("\n"))
