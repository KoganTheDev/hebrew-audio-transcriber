"""
Pixel-level tests for PaintedCheckboxStyle (speech_to_text/gui/checkbox_style.py).

The QSS raster tick this replaced was verified once, by eye, and nothing
pinned its states after that - a glyph could render wrong (wrong color,
missing tick, a border that stopped swapping colors on disable) while every
line of Python was present and "correct" by any test that only checks
methods exist. So these tests build a real QCheckBox, apply the real style,
paint it into a real QPixmap, and sample actual pixels - the same class of
regression the rewrite itself was fixing (see checkbox_style.py's module
docstring: the old bug was a rendered stroke coming out at uneven weights,
which no method-existence test would ever catch).

qapp here is pytest-qt's session-scoped `qapp` fixture, a bare
QApplication (no module in this suite defines its own - see "The shared
QApplication" in docs/TESTING.md for why). It does not run
configure_application, so PaintedCheckboxStyle is not installed on it by
default. These tests install it directly on the checkbox's QApplication
instance rather than calling configure_application, because
configure_application also persists/reads the saved UI language and installs
a process-wide keyboard-focus event tracker (speech_to_text.gui.focus) -
side effects unrelated to what's under test here, and undesirable in a
suite that otherwise builds a bare QApplication. Installing
PaintedCheckboxStyle is the one piece of that setup this file's tests
actually depend on (the class reads speech_to_text.gui.theme.COLORS
directly, not QSS, so the stylesheet half of configure_application is not
needed either).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QCheckBox,
    QProxyStyle,
    QStyle,
    QStyleOptionButton,
    QStyleOptionFocusRect,
)

from speech_to_text.gui.checkbox_style import PaintedCheckboxStyle  # noqa: E402
from speech_to_text.gui.theme import COLORS  # noqa: E402

# Antialiasing softens edge pixels toward the background, so exact-match
# comparisons on a stroked/rounded shape are flaky by construction. This is
# generous enough to absorb that blending while still failing if the wrong
# color family entirely gets sampled (e.g. background instead of accent).
_TOLERANCE = 40

# accent_text (the tick's ink color) is a near-black color (#11111b), and
# _TOLERANCE=20 is loose enough that plain antialiased near-black edge
# pixels from the *platform's own default* checkbox rendering land inside
# it too - measured directly: with PaintedCheckboxStyle.drawPrimitive
# deliberately broken to fall through to the base style, scanning the
# indicator for anything within _TOLERANCE of accent_text still found
# matches, because the base style's own border antialiasing happens to be
# close enough in RGB space. A tighter tolerance for this one color-vs-color
# comparison keeps test_checked_tick_ink_is_accent_text able to fail when
# the tick itself stops rendering, rather than passing on an unrelated dark
# pixel it was never checking for.
_TICK_INK_TOLERANCE = 6


def _color_close(actual: QColor, expected_hex: str, tolerance: int = _TOLERANCE) -> bool:
    expected = QColor(expected_hex)
    return (
        abs(actual.red() - expected.red()) <= tolerance
        and abs(actual.green() - expected.green()) <= tolerance
        and abs(actual.blue() - expected.blue()) <= tolerance
    )


# `qapp` is pytest-qt's own session-scoped fixture. It must stay session-scoped
# and must not be shadowed by a local definition here: a module-scoped
# QApplication fixture in this file once dropped the last Python reference to
# the application at the end of this module and left unrelated tests in
# test_gui.py failing. The full incident is written up under "The shared
# QApplication" in docs/TESTING.md.


@pytest.fixture(scope="session")
def painted_style(qapp):
    """
    Install PaintedCheckboxStyle on `qapp`, application-wide, exactly the
    way main_window.configure_application does for the real app
    (`app.setStyle(PaintedCheckboxStyle(app.style()))`) - and never restore
    or replace it afterwards.

    Two other shapes were tried first and both corrupted the process rather
    than just this test's own state - see "The shared QApplication" in
    docs/TESTING.md for the matching story on the QApplication singleton
    itself:

    1. Module-scoped, wrapping `qapp.style()` (the app's live, shared
       style), attached per-widget via QWidget.setStyle() instead of
       QApplication.setStyle(). QProxyStyle takes ownership of the style
       object passed to its constructor and deletes it from its own
       destructor. QApplication.setStyle() also takes C++-side ownership of
       whatever is passed to IT, but does not appear to keep the Python
       wrapper alive on its own - so once this fixture's cache (the only
       remaining Python reference) was torn down at the end of the module,
       the wrapper was garbage-collected, its destructor ran, and it
       deleted the app's real style out from under it while
       QApplication still held a raw pointer to it. Symptom: `Fatal Python
       error: Aborted` a few tests after this module finished.
    2. Module-scoped, wrapping a fresh QStyleFactory.create(...) instance
       (not shared with the app) instead, still attached per-widget. No
       double-free this time, but the same "only Python reference lives in
       a fixture cache that gets torn down mid-session" shape still applied
       to the wrapper itself, and a later run reproduced an outright
       Windows access-violation crash in an unrelated GUI test
       (test_tab_keydown_marks_the_newly_focused_widget) - consistent with
       the same class of premature-deletion bug, just landing on a
       different dangling pointer depending on GC timing.

    Session-scoped and installed application-wide, never uninstalled, is
    what the real app already does for its entire process lifetime - so
    this fixture just does the same thing, once, and never tears it down
    early enough to matter. No other test in the suite asserts anything
    about a QCheckBox's appearance under the platform's default style (see
    the grep this comment is based on - only this file touches QCheckBox
    rendering at all), so there is nothing else in the suite for an
    application-wide style change to break.
    """
    style = PaintedCheckboxStyle(qapp.style())
    qapp.setStyle(style)
    return style


def _make_checkbox(painted_style, checked: bool, enabled: bool = True) -> QCheckBox:
    cb = QCheckBox()  # no text: the indicator is what's under test
    # No explicit cb.setStyle(...): painted_style is already installed
    # application-wide (see the fixture above), so this checkbox picks it
    # up the same way every real QCheckBox in the shipped app does.
    cb.setChecked(checked)
    cb.setEnabled(enabled)
    cb.resize(cb.sizeHint())
    return cb


def _indicator_rect(cb: QCheckBox):
    """The indicator's own rect within the checkbox, in widget coordinates."""
    opt = QStyleOptionButton()
    cb.initStyleOption(opt)
    return cb.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, cb)


def _grab(cb: QCheckBox) -> QPixmap:
    pixmap = QPixmap(cb.size())
    pixmap.fill(QColor(COLORS["bg_primary"]))
    cb.render(pixmap)
    return pixmap


def _scan_for_color(pixmap: QPixmap, rect, expected_hex: str, tolerance: int = _TOLERANCE) -> bool:
    """True if any pixel inside `rect` is close to `expected_hex`."""
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            if _color_close(pixmap.toImage().pixelColor(x, y), expected_hex, tolerance):
                return True
    return False


class TestPaintedCheckboxIndicatorSize:
    def test_indicator_width_and_height_are_18(self, painted_style):
        # The QSS rule this class replaces declared an explicit
        # QCheckBox::indicator { width: 18px; height: 18px; }; nothing else
        # supplies that size now, so this is the one place it's pinned.
        assert painted_style.pixelMetric(QStyle.PM_IndicatorWidth) == 18
        assert painted_style.pixelMetric(QStyle.PM_IndicatorHeight) == 18


class TestPaintedCheckboxRenderedPixels:
    def test_unchecked_has_no_accent_fill(self, qapp, painted_style):
        cb = _make_checkbox(painted_style, checked=False)
        rect = _indicator_rect(cb)
        pixmap = _grab(cb)
        assert not _scan_for_color(pixmap, rect, COLORS["accent"]), (
            "unchecked indicator must not be filled with the accent color"
        )

    def test_checked_has_accent_fill(self, qapp, painted_style):
        cb = _make_checkbox(painted_style, checked=True)
        rect = _indicator_rect(cb)
        pixmap = _grab(cb)
        # Sample the fill away from the tick strokes and the border edge -
        # a point near the indicator's top-left interior is fill, not ink.
        inset = max(2, rect.width() // 4)
        fill_point = (rect.left() + inset, rect.top() + inset)
        color = pixmap.toImage().pixelColor(*fill_point)
        assert _color_close(color, COLORS["accent"]), (
            f"expected accent fill near {fill_point}, got {color.name()}"
        )

    def test_checked_tick_ink_is_accent_text(self, qapp, painted_style):
        """
        The tick itself must render in accent_text somewhere inside the
        indicator. Scanning the whole indicator rect for "does this color
        appear anywhere" is more robust than pinning one exact pixel: the
        tick's exact path (see checkbox_style.py's hard-coded 0.28/0.52 etc.
        fractions) is an implementation detail this test shouldn't have to
        track pixel-for-pixel, but "no accent_text ink anywhere" is exactly
        the failure mode (a tick that silently stops being drawn) this test
        exists to catch.

        Uses _TICK_INK_TOLERANCE, not the module's general _TOLERANCE: see
        that constant's own comment - accent_text is dark enough that the
        wider tolerance also matches plain antialiased dark edge pixels from
        an unrelated (even a broken) rendering, which would make this test
        pass for the wrong reason.
        """
        cb = _make_checkbox(painted_style, checked=True)
        rect = _indicator_rect(cb)
        pixmap = _grab(cb)
        assert _scan_for_color(
            pixmap, rect, COLORS["accent_text"], tolerance=_TICK_INK_TOLERANCE
        ), "expected accent_text tick ink somewhere inside the checked indicator"

    def test_disabled_differs_from_enabled_when_checked(self, qapp, painted_style):
        """
        Checked+disabled must not look like checked+enabled: the fill drops
        to text_disabled instead of accent (see the `if not enabled` branch
        in PaintedCheckboxStyle.drawPrimitive). Comparing checked states
        rather than unchecked ones deliberately - unchecked enabled and
        unchecked disabled currently share the same fill (bg_tertiary) and
        differ only in border color, which is a much smaller, edge-only
        signal to sample reliably.
        """
        enabled_cb = _make_checkbox(painted_style, checked=True, enabled=True)
        disabled_cb = _make_checkbox(painted_style, checked=True, enabled=False)

        rect = _indicator_rect(enabled_cb)
        inset = max(2, rect.width() // 4)
        fill_point = (rect.left() + inset, rect.top() + inset)

        enabled_color = _grab(enabled_cb).toImage().pixelColor(*fill_point)
        disabled_color = _grab(disabled_cb).toImage().pixelColor(*fill_point)

        assert _color_close(enabled_color, COLORS["accent"])
        assert _color_close(disabled_color, COLORS["text_disabled"])
        # And the two must actually be visually distinguishable from each
        # other, not just each individually "close enough" to two colors
        # that happen to be close to one another.
        assert (
            abs(enabled_color.red() - disabled_color.red())
            + abs(enabled_color.green() - disabled_color.green())
            + abs(enabled_color.blue() - disabled_color.blue())
        ) > 60


class _RecordingStyle(QProxyStyle):
    """
    A QProxyStyle stand-in for "whatever base style PaintedCheckboxStyle
    wraps" that records which primitives it was actually asked to draw,
    instead of really painting them. Lets the focus-rect test assert on
    behavior (was the base style's drawPrimitive reached at all) rather
    than trying to detect the presence/absence of a native dotted rectangle
    in a rendered pixmap, which is both platform-style-dependent and not
    guaranteed to paint anything visible under the offscreen platform
    plugin in the first place.
    """

    def __init__(self):
        super().__init__()
        self.drawn = []

    def drawPrimitive(self, element, option, painter, widget=None):
        self.drawn.append(element)
        # Deliberately do not call super(): recording the call is all this
        # spy needs, and QProxyStyle.drawPrimitive with a bare wrapped style
        # may fall through to platform drawing that isn't meaningful here.


class TestPaintedCheckboxFocusRect:
    def test_focus_rect_is_swallowed_for_checkboxes(self, qapp):
        """
        PE_FrameFocusRect must never reach the wrapped base style when the
        widget is a QCheckBox - Qt's default dotted focus rectangle is
        redundant with (and visually wrong next to) the indicator's own
        kbdFocus border. This regressed once already (see
        checkbox_style.py's comment on this branch), so it's pinned here
        directly against the code path rather than only indirectly via
        rendered pixels.
        """
        recorder = _RecordingStyle()
        style = PaintedCheckboxStyle(recorder)
        cb = QCheckBox()

        pixmap = QPixmap(20, 20)
        painter = QPainter(pixmap)
        try:
            opt = QStyleOptionFocusRect()
            style.drawPrimitive(QStyle.PE_FrameFocusRect, opt, painter, cb)
        finally:
            painter.end()

        assert recorder.drawn == [], (
            "PE_FrameFocusRect must be swallowed for a QCheckBox, not forwarded to the base style"
        )

    def test_focus_rect_is_not_swallowed_for_other_widgets(self, qapp):
        """
        Control for the test above: the swallow is specific to QCheckBox,
        not to PE_FrameFocusRect in general - anything else (widget=None
        here, standing in for a non-checkbox control) must still get its
        focus rect forwarded to the base style as normal.
        """
        recorder = _RecordingStyle()
        style = PaintedCheckboxStyle(recorder)

        pixmap = QPixmap(20, 20)
        painter = QPainter(pixmap)
        try:
            opt = QStyleOptionFocusRect()
            style.drawPrimitive(QStyle.PE_FrameFocusRect, opt, painter, None)
        finally:
            painter.end()

        assert recorder.drawn == [QStyle.PE_FrameFocusRect]
