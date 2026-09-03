"""
Keyboard-vs-pointer focus-ring gate.

Qt's `:focus` pseudo-state paints identically whether a widget got focus
from a Tab key press, a mouse click, or nothing at all - including a fresh
window's default-focused widget, which is exactly what made the app open
with a sapphire ring around the header language toggle (see theme.py's
app_stylesheet() docstring: that rule was added in an earlier step with no
way to scope it yet). CSS solved the identical problem with
:focus-visible; Qt has no such pseudo-state and no scripted DOM to hang a
data-attribute off of the way this app's OWN generated HTML transcript does
(see core/assets/js/94-layout.js's bindKeyboardModality() - the direct
inspiration for this module). What Qt does have is a QApplication-wide
event stream and dynamic widget properties QSS can select on, which is
enough to build the same idea by hand: track whether the most recent input
was a key press or a pointer press, and stamp a property on exactly the
widget that gains focus while a keyboard is driving - never on a widget
that merely received default or mouse-click focus.
"""

import logging

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Dynamic property name theme.py's QSS keys off, e.g.
# "QPushButton[kbdFocus=\"true\"] { ... }". Set with a real Python bool
# (not the string "true") - Qt's stylesheet engine matches a boolean
# dynamic property against the literal tokens true/false in an attribute
# selector, so setProperty(PROPERTY, True) round-trips correctly.
PROPERTY = "kbdFocus"


class KeyboardFocusTracker(QObject):
    """
    Install exactly once, on the QApplication instance (see
    MainWindow.__init__). Mirrors bindKeyboardModality() from the HTML
    transcript almost line for line:

      - Tab (or Shift+Tab / Backtab) keydown turns keyboard modality on.
        Tab is the one key guaranteed to reach an application-wide filter
        un-swallowed - a plain letter key inside a QSpinBox never would,
        since the widget's own keyPressEvent consumes it first - and it is
        SET rather than toggled off on every other key so a user who tabs
        to a control and then, say, presses Space or an arrow key on it
        doesn't lose the flag mid keyboard session.
      - Any mouse button press turns it off immediately. Button PRESS, not
        click or release, mirroring pointerdown in the JS version: it fires
        before the resulting focus-in, so the flag is already clear by the
        time focusChanged below has to decide whether to stamp a ring on
        whatever the user just clicked.

    QApplication.focusChanged then does the actual stamping: it clears the
    property from whichever widget is losing focus and, only while keyboard
    modality is on, sets it on whichever widget is gaining focus. Programmatic
    focus (a step's showEvent calling drop_zone.setFocus() to seed a sensible
    Tab starting point - see FileSelectStep/ModelSelectStep) fires this same
    signal, but with keyboard modality still at its startup default of False,
    so the seeded widget gets real Qt focus without ever painting a ring -
    which is the whole point: the ring should announce "a keyboard is
    driving", not "something happens to have focus".
    """

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._keyboard_active = False
        app.installEventFilter(self)
        app.focusChanged.connect(self._on_focus_changed)

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self._keyboard_active = True
        elif event_type == QEvent.MouseButtonPress:
            self._keyboard_active = False
            # Clearing the flag is not enough on its own. The property lives
            # on the focused widget and is only rewritten by focusChanged, so
            # a click that does NOT move focus - on a label, a panel, the
            # window background - would leave the previous ring painted until
            # focus happened to move again. The JS original has no equivalent
            # problem because its flag lives on one root element and the CSS
            # reads it live; the per-widget property has to be retracted by
            # hand. Guarded on the current value so an ordinary click, which
            # is the overwhelmingly common case, costs a property read rather
            # than an unpolish/polish cycle.
            focused = QApplication.focusWidget()
            if focused is not None and focused.property(PROPERTY):
                self._set_property(focused, False)
        # Observation only - never claims the event, so normal Tab
        # navigation and mouse handling proceed exactly as they would with
        # no filter installed at all.
        return False

    def _on_focus_changed(self, old, new):
        if old is not None:
            self._set_property(old, False)
        if new is not None and self._keyboard_active:
            self._set_property(new, True)

    def is_keyboard_active(self) -> bool:
        """
        Whether the most recent input was a keyboard press (Tab/Backtab)
        rather than a mouse click - the same flag _on_focus_changed reads to
        decide whether to stamp PROPERTY on the widget actually gaining
        focus.

        Exists for a widget that needs the ring painted on something OTHER
        than the widget Qt gave real focus to - the model-select card is the
        one case in this app: the QRadioButton inside it is what receives
        focus, but the card QFrame around it is what should show the ring
        (see ModelSelectStep._install_card_focus_ring). That widget can't
        just read the radio's own PROPERTY, because by the time its
        FocusIn/FocusOut handler runs the radio's PROPERTY may not be set
        yet - QApplication delivers the QFocusEvent to the widget BEFORE
        emitting focusChanged (see _on_focus_changed above, which is what
        actually sets PROPERTY, and runs off that later signal). Re-deriving
        "is a keyboard driving this focus change" from this flag directly,
        at FocusIn time, sidesteps that ordering question entirely rather
        than depending on it.
        """
        return self._keyboard_active

    @staticmethod
    def _set_property(widget, value: bool) -> None:
        """
        Restyle exactly the one widget whose focus state changed, not the
        whole application - unpolish()/polish() forces Qt to re-evaluate
        that widget's QSS against its (now different) dynamic property,
        which a bare setProperty() call alone does not trigger a repaint
        for.
        """
        widget.setProperty(PROPERTY, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
