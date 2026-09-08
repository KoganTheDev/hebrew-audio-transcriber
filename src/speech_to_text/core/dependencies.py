"""Checking that the runtime dependencies are actually importable.

This used to pip install whatever was missing, into sys.executable, with the
output captured. That was actively harmful rather than merely unhelpful: the
launcher can pick a system interpreter, so the install landed in the user's
GLOBAL Python rather than the project's virtual environment, took minutes with
no visible sign it was doing anything, and still ended in a crash because the
package list it worked from did not include faster-whisper.

Installing is the installer's job. This reports.

It checks with importlib.util.find_spec rather than by importing. That is not a
detail: main.py imports faster_whisper BEFORE PyQt5 on purpose, because the two
ship conflicting copies of MSVCP140.dll on Windows and whichever loads first
wins. A check that imported its way down a dict would decide that order by
dict insertion order instead, and silently reintroduce the access violation
that comment exists to prevent. find_spec locates a module without executing
it, so no DLL is loaded here at all.
"""

import importlib.util
import logging
import sys

logger = logging.getLogger(__name__)


def ensure_dependencies(packages: dict[str, str]) -> bool:
    """Report whether every runtime dependency can be imported.

    Args:
        packages: {import name: pip name}

    Returns:
        True when all are importable. False after logging what is missing and
        how to fix it - the caller exits, rather than this function trying to
        repair the environment behind the user's back.

    """
    missing: list[tuple[str, str]] = []
    for import_name, pip_name in packages.items():
        try:
            found = importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append((import_name, pip_name))

    if not missing:
        logger.info(f"All {len(packages)} required packages are available")
        return True

    logger.error("Missing required packages: %s", ", ".join(n for n, _ in missing))
    logger.error("Python being used: %s", sys.executable)
    logger.error("")
    logger.error("This usually means the app is running on the wrong Python -")
    logger.error("one without the project's dependencies installed.")
    logger.error("")
    logger.error("To fix it, from the project folder:")
    logger.error("    python -m venv .venv")
    logger.error(r"    .venv\Scripts\activate")
    logger.error("    pip install -e .")
    logger.error("")
    logger.error("Then start the app with run.bat or run.ps1, which prefer .venv")
    logger.error("over any system Python.")
    return False
