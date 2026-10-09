"""Shared machinery for the hand-painted animated widgets.

Each animated widget stores when a transition began and computes its look
from that and the clock at paint time; one looping animation per widget only
decides when to repaint. Timings live in theme.Motion.
"""

import ctypes
import math
import sys
import time

from PyQt5.QtCore import QObject, QVariantAnimation
from PyQt5.QtGui import QColor

from gui.theme import COLORS, Motion

# A start time far enough in the past that any transition from it is over.
LONG_AGO = -1e9

# SystemParametersInfoW action for Settings > Accessibility > Visual effects
# > "Animation effects"; ctypes does not export it.
_SPI_GETCLIENTAREAANIMATION = 0x1042


def animations_enabled() -> bool:
    """Whether to run decorative animations.

    Honors the Windows "Animation effects" switch - where people who get
    motion sick turn UI movement off. Read on each call, so flipping it takes
    effect the next time an animation starts. Unreadable counts as on.
    """
    if sys.platform != "win32":
        return True
    try:
        enabled = ctypes.c_bool(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
        return bool(enabled.value) if ok else True
    except (AttributeError, OSError):
        return True


def now_ms() -> float:
    """The clock every transition is measured against."""
    return time.monotonic() * 1000


def breath_loop(parent: QObject) -> QVariantAnimation:
    """An endless 0 -> 1 animation, one breath long; its value is the phase."""
    loop = QVariantAnimation(parent)
    loop.setStartValue(0.0)
    loop.setEndValue(1.0)
    loop.setDuration(Motion.BREATH_MS)
    loop.setLoopCount(-1)
    return loop


def is_running(animation: QVariantAnimation) -> bool:
    return animation.state() == QVariantAnimation.State.Running


def progress(now: float, since: float, duration: float) -> float:
    """Fraction of a `duration`-long transition done at `now`, clamped to 0..1."""
    return min(1.0, max(0.0, (now - since) / duration))


def ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def ease_out_back(x: float) -> float:
    """Overshoots slightly past 1 before settling - the "pop"."""
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


_POP_START_SCALE = 0.5


def pop_scale(now: float, since: float) -> float:
    """Scale for an icon popping in: half size -> slight overshoot -> 1."""
    f = progress(now, since, Motion.POP_MS)
    if f >= 1:
        return 1.0
    return _POP_START_SCALE + (1 - _POP_START_SCALE) * ease_out_back(f)


def breath(phase: float) -> float:
    """0 -> 1 -> 0 over one cycle, eased at both ends (a cosine)."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * phase)


def pulse_alpha(phase: float) -> float:
    """Fill opacity of a breathing element at `phase`."""
    return Motion.PULSE_MIN_ALPHA + (1 - Motion.PULSE_MIN_ALPHA) * breath(phase)


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
