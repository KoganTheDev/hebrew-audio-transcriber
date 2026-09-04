"""Logging glue for visual-order console output - see core/hebrew_text.py,
above to_visual_order(), for why this exists at all. Separate from main.py so
main.py stays wiring: which handler gets which formatter, not why.
"""

import logging
import os
import sys

from speech_to_text.core.hebrew_text import to_visual_order


def visual_order_mode() -> str:
    """Resolve STT_LOG_BIDI to "visual" or "logical".

    "auto" (the default) means visual on a Windows console tty and logical
    everywhere else: no Windows console implements the UBA, so a Windows tty
    needs pre-reversed text, while redirected output is headed for a file or
    pager opened by a bidi-capable reader, where pre-reversed text would be
    wrong. The env var is the escape hatch for a terminal that does implement
    the UBA.
    """
    mode = os.environ.get("STT_LOG_BIDI", "auto").strip().lower()
    if mode in ("visual", "logical"):
        return mode
    return "visual" if (os.name == "nt" and sys.stdout.isatty()) else "logical"


class VisualOrderFormatter(logging.Formatter):
    """Reorders each formatted line into visual order for a non-bidi console.

    Per line, not over the whole record as one blob, so a multi-line exception
    traceback is reordered line by line rather than as a single paragraph with
    the wrong boundaries.
    """

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if visual_order_mode() != "visual":
            return formatted
        return "\n".join(to_visual_order(line) for line in formatted.split("\n"))
