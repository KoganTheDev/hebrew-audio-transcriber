"""Keyboard-vs-pointer focus-ring gate.

Qt's :focus paints for keyboard, mouse and default focus alike - the app used
to open with a ring on the language toggle. Qt has no :focus-visible, so this
builds it, as the HTML transcript's bindKeyboardModality() does: track whether
the latest input was a key or a pointer press, and stamp a QSS-selectable
property only on a widget that gains focus while the keyboard is driving.
"""

import logging

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Dynamic property name theme.py's QSS keys off, e.g.
# "QPushButton[kbdFocus=\"true\"] { ... }". Set with a real Python bool
# (not the string "true") - Qt's stylesheet engine matches a boolean
# dynamic property against the literal tokens true/false in an attribute
# selector, so setProperty(PROPERTY, True) round-trips correctly.
PROPERTY = "kbdFocus"


class KeyboardFocusTracker(QObject):
    """Install once, on the QApplication.

    Tab/Backtab turns keyboard modality on (Tab always reaches an app-wide
    filter; other keys get eaten by widgets) and other keys leave it on; any
    mouse PRESS turns it off, before the focus change it causes.
    focusChanged then moves the property from the old widget to the new one,
    only while modality is on - so programmatic focus (a step seeding its
    first Tab stop) gets real focus but no ring.
    """

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._keyboard_active = False
        app.installEventFilter(self)
        app.focusChanged.connect(self._on_focus_changed)
        # Detach at aboutToQuit: focusChanged keeps firing during teardown
        # with half-destroyed widgets, and polishing one crashes after exec_().
        app.aboutToQuit.connect(self._detach)

    def _detach(self) -> None:
        """Stop observing, on the way out. Safe to call more than once."""
        # isinstance rather than "is not None": QApplication.instance() is
        # typed as the QCoreApplication base, which has no focusChanged. A
        # console-only QCoreApplication could never have got here anyway, so
        # narrowing to the type this code actually needs is the honest guard.
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        app.removeEventFilter(self)
        try:
            app.focusChanged.disconnect(self._on_focus_changed)
        except TypeError:
            # Already disconnected - _detach ran twice, which is fine.
            pass

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None:
            return False
        event_type = a1.type()
        # isinstance narrows QEvent to the subclass that actually has key();
        # a KeyPress is always a QKeyEvent, so this never rejects a real one.
        if (
            event_type == QEvent.Type.KeyPress
            and isinstance(a1, QKeyEvent)
            and a1.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        ):
            self._keyboard_active = True
        elif event_type == QEvent.Type.MouseButtonPress:
            self._keyboard_active = False
            # Also retract the ring now: a click that does not move focus would
            # otherwise leave it painted. Guarded, so a plain click costs one
            # property read.
            focused = QApplication.focusWidget()
            if focused is not None and focused.property(PROPERTY):
                self._set_property(focused, False)
        # Observation only - never claims the event, so normal Tab
        # navigation and mouse handling proceed exactly as they would with
        # no filter installed at all.
        return False

    def _on_focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        if old is not None:
            self._set_property(old, False)
        if new is not None and self._keyboard_active:
            self._set_property(new, True)

    def is_keyboard_active(self) -> bool:
        """Whether the latest input was Tab/Backtab rather than a mouse press.

        For a widget that paints the ring on something other than the focused
        widget - the model card around its radio button. It cannot read the
        radio's property at FocusIn: Qt sends the focus event before
        focusChanged, which is what sets it.
        """
        return self._keyboard_active

    @staticmethod
    def _set_property(widget: QWidget, value: bool) -> None:
        """Re-apply QSS to the one widget whose property changed;
        setProperty() alone does not repaint.
        """
        widget.setProperty(PROPERTY, value)
        style = widget.style()
        # style() is typed Optional and is genuinely None for a widget whose
        # C++ side has already gone; skipping the repaint is the right answer
        # there, since there is nothing left to paint.
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()
