"""Small helpers shared by the hand-painted animated widgets.

Each animated widget keeps a clock reading and the time a transition began,
and computes its look from the two at paint time. These are the pieces that
arithmetic needs: how far along a transition is, its easing, and colour
blending. The timings themselves live in theme.Motion.
"""

import math

from PyQt5.QtGui import QColor

from gui.theme import COLORS, Motion

# A start time far enough in the past that any transition measured from it
# has long finished - what "no animation" looks like to paint code.
LONG_AGO = -1e9


def progress(now: float, since: float, duration: float) -> float:
    """Fraction of a `duration`-long transition done at `now`, clamped to 0..1."""
    return min(1.0, max(0.0, (now - since) / duration))


def ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def ease_out_back(x: float) -> float:
    """Overshoots slightly past 1 before settling - the "pop"."""
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def pop_scale(now: float, since: float) -> float:
    """Scale for an icon popping in: 0.5 -> slight overshoot -> 1."""
    f = progress(now, since, Motion.POP_MS)
    return 0.5 + 0.5 * ease_out_back(f) if f < 1 else 1.0


def breath(phase: float) -> float:
    """0..1..0 over one cycle, eased at both ends (a cosine)."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * phase)


def mix(a: QColor, b: QColor, f: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * f,
        a.greenF() + (b.greenF() - a.greenF()) * f,
        a.blueF() + (b.blueF() - a.blueF()) * f,
        a.alphaF() + (b.alphaF() - a.alphaF()) * f,
    )


def with_alpha(color_key: str, alpha: float) -> QColor:
    color = QColor(COLORS[color_key])
    color.setAlphaF(alpha)
    return color
