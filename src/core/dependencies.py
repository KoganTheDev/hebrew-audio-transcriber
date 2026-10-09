"""Checking that the runtime dependencies are importable - reporting only;
installing is the launcher's job (installing from here hit whatever Python
happened to run, often not the project's venv).

find_spec, not import: app.py must import faster_whisper before PyQt5 (their
MSVCP140.dll copies conflict), and importing here would decide that order by
dict order instead. find_spec loads no DLL at all.
"""

import importlib.util
import logging
import sys

logger = logging.getLogger(__name__)


def ensure_dependencies(packages: dict[str, str]) -> bool:
    """Whether every {import name: pip name} is importable; when not, logs
    what is missing and how to fix it, and the caller exits.
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

    logger.error(_MISSING_HELP, ", ".join(name for name, _ in missing), sys.executable)
    return False


_MISSING_HELP = """Missing required packages: %s
Python being used: %s

This usually means the app is running on the wrong Python -
one without the project's dependencies installed.

To fix it, double-click run.bat in the project folder - it
will offer to set everything up.

Or do it by hand:
    python -m venv .venv
    .venv\\Scripts\\activate
    python -m pip install --upgrade pip
    pip install -e ."""
