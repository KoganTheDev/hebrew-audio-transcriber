"""Global exception hook, so nothing crashes silently.

PyQt's event loop prints slot exceptions to stderr - invisible without a
console - instead of raising them. Both paths now reach sys.excepthook:
exceptions outside the loop directly, and those inside slots through
DiagnosticApplication.notify(). Each is logged with a traceback before any UI
is attempted, so the log has it even if the crash dialog fails.
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
    """Carries an uncaught exception to the GUI thread: excepthook can fire
    on any thread, and a queued signal is the safe way to reach widgets.
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
    """Install sys.excepthook so any otherwise-lost exception is logged and
    shown. Call once, right after creating the QApplication - it also catches
    startup failures before exec_().
    """
    global _previous_excepthook
    _previous_excepthook = sys.excepthook
    sys.excepthook = _handle_uncaught


class DiagnosticApplication(QApplication):
    """QApplication whose notify() re-raises slot exceptions through
    sys.excepthook, which PyQt's event loop would otherwise swallow.
    """

    def notify(self, receiver: QObject | None, event: QEvent | None) -> bool:
        try:
            return super().notify(receiver, event)
        except Exception:
            sys.excepthook(*sys.exc_info())
            return False
