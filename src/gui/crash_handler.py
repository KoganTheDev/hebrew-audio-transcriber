"""Global exception hook, so nothing crashes silently.

Without this, an exception raised after the event loop starts has nowhere to
go: PyQt's C++ event loop catches exceptions raised inside slots/callbacks
itself and just prints to stderr (invisible in a packaged, console-less
build) rather than letting them reach sys.excepthook. The result was exactly
the kind of report this module exists to prevent - a user hits a crash and
has nothing usable to hand back, because the crash was never logged and
never shown.

install_global_exception_hook() covers the two ways an exception can now go
uncaught:
  - Outside the event loop (import-time errors after logging is configured,
    a thread target that isn't a Qt slot) via sys.excepthook.
  - Inside a Qt slot/event callback via DiagnosticApplication.notify(),
    which routes back through the same sys.excepthook so there is one code
    path for both.

Either way, the exception is always logged with a full traceback first,
before any UI work is attempted - so even if the crash dialog itself fails,
the log file still has what happened.
"""

import logging
import sys
import traceback
from types import TracebackType

from PyQt5.QtCore import QEvent, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def format_exception(
    exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
) -> str:
    """Render a full traceback as one string, shared by the log call and the crash dialog."""
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


class CrashSignalBridge(QObject):
    """Carries an uncaught exception from wherever it was caught to the GUI thread.

    sys.excepthook can fire from any thread; Qt widgets may only be touched
    from the main thread. A signal/slot connection (Qt queues the emit onto
    the receiver's thread) is what makes showing a dialog from here safe
    regardless of which thread the exception happened on.
    """

    crashed = pyqtSignal(str, str)  # (message, formatted traceback)


_bridge: CrashSignalBridge | None = None
_previous_excepthook = None


def get_crash_bridge() -> CrashSignalBridge:
    """The module-level bridge singleton, created by install_global_exception_hook()."""
    global _bridge
    if _bridge is None:
        _bridge = CrashSignalBridge()
    return _bridge


def _handle_uncaught(
    exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
) -> None:
    # KeyboardInterrupt/SystemExit are normal control flow (Ctrl+C, sys.exit()),
    # not crashes - let the interpreter's default handling deal with them.
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        if _previous_excepthook is not None:
            _previous_excepthook(exc_type, exc_value, exc_tb)
        else:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    formatted = format_exception(exc_type, exc_value, exc_tb)
    # Always logged first - this alone satisfies "never silently disappear",
    # even if everything below (the app instance, the dialog) fails too.
    logger.critical("Unhandled exception:\n%s", formatted)

    app = QApplication.instance()
    if app is not None:
        get_crash_bridge().crashed.emit(str(exc_value), formatted)
    else:
        # No QApplication yet (e.g. a failure during early startup, before
        # logging/app are fully configured) - fall back to stderr so a
        # console/packaged-with-console build still shows something.
        sys.stderr.write(formatted)


def install_global_exception_hook(app: QApplication | None) -> None:
    """Install sys.excepthook, so any exception that would otherwise be lost is logged and shown.

    Safe to call once, early in main(), right after the QApplication is
    created and before app.exec_() starts. `app` is accepted (rather than
    relying only on QApplication.instance() later) so the caller's intent is
    explicit, even though _handle_uncaught re-resolves it at hook time -
    the instance existing then is what actually matters, since this can
    also catch failures during startup before app.exec_() runs.
    """
    global _previous_excepthook
    _previous_excepthook = sys.excepthook
    sys.excepthook = _handle_uncaught


class DiagnosticApplication(QApplication):
    """QApplication that routes exceptions raised inside Qt slots/callbacks to sys.excepthook.

    PyQt's event loop swallows exceptions raised inside notify() targets
    (slots, event handlers) by default - they never reach sys.excepthook on
    their own. Overriding notify() to catch and re-raise through
    sys.excepthook is the standard fix, and keeps this as the one path
    everything (event-loop exceptions and anything else) funnels through.
    """

    def notify(self, receiver: QObject, event: QEvent) -> bool:
        try:
            return super().notify(receiver, event)
        except Exception:
            sys.excepthook(*sys.exc_info())
            return False
