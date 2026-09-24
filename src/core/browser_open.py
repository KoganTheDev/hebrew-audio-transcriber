"""Pick a specific browser to open the transcript in, rather than whatever
Windows currently associates with .html.

The symptom this exists to fix: on a machine with Chrome installed and set
as the actual daily browser, double-clicking or app-launching an .html file
often still opens Edge, because the file association and "default browser"
setting are two different things and installers do not always win both. The
generated transcript is a self-contained interactive page (search, audio
sync, speaker editing - see core/formatting), so which engine renders it is
not cosmetic.

Windows itself maintains the authoritative list of browsers it knows about
under the registry's StartMenuInternet key - that is what Settings > Default
apps reads from - so this reads the same source rather than hardcoding
install paths. Paths are still needed as a backstop: a portable or
per-user install (common for Chrome and Firefox, which both install under
%LOCALAPPDATA% without admin rights) does not always register itself there,
so a short list of well-known locations catches those. Per-user paths are
checked as often as the two Program Files directories because a per-user
install is the common case for exactly the browsers this module prefers.

Everything here degrades to the OS default (webbrowser.open) rather than
raising: failing to pick a preferred browser must never stop the transcript
from opening at all.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

PREFERENCE_ORDER = ("chrome", "firefox", "edge")

# Order matters here: "Microsoft Edge" contains neither "chrome" nor
# "firefox", but nothing stops some future subkey name containing more than
# one of these substrings, so chrome and firefox are matched before edge.
_SUBSTRING_KEYS = ("chrome", "firefox", "edge")

# Backstop absolute paths for installs that do not register themselves under
# StartMenuInternet or App Paths (seen with some portable/per-user builds).
# Per-user (%LOCALAPPDATA%) is listed first because it is the common case for
# a no-admin-rights Chrome/Firefox install, not because Program Files installs
# are rare - both are checked.
_WELL_KNOWN_PATHS = {
    "chrome": [
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    ],
    "firefox": [
        r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe",
        r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
        r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    ],
}

_APP_PATHS_EXE = {
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
}

# shutil.which() names for non-Windows platforms, most-preferred first per key.
_WHICH_NAMES = {
    "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "firefox": ("firefox",),
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
}


def _key_for_subkey_name(name: str) -> str | None:
    """Map a StartMenuInternet/App Paths subkey name to one of our keys."""
    lowered = name.lower()
    for key in _SUBSTRING_KEYS:
        if key in lowered:
            return key
    return None


def _extract_exe_path(command: str) -> str | None:
    r"""Pull the executable path out of a `shell\open\command` value.

    That value is usually `"C:\path\to\exe" -- "%1"` but is not
    guaranteed to be quoted, so both forms are handled.
    """
    command = command.strip()
    if not command:
        return None
    match = re.match(r'^"([^"]+)"', command)
    if match:
        return match.group(1)
    # Unquoted: take the first whitespace-delimited token.
    return command.split()[0] if command.split() else None


def _read_start_menu_internet(browsers: dict[str, str]) -> None:
    """Registry list Windows itself keeps of installed browsers.

    This is what Settings > Default apps reads, so it is authoritative
    ahead of any guessed path, and it is where a StartMenuInternet-aware
    installer registers per-user installs too.
    """
    try:
        import winreg
    except ImportError:
        return

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Clients\StartMenuInternet") as root:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    key = _key_for_subkey_name(subkey_name)
                    if key is None or key in browsers:
                        continue
                    try:
                        with winreg.OpenKey(root, rf"{subkey_name}\shell\open\command") as cmd_key:
                            command, _ = winreg.QueryValueEx(cmd_key, "")
                        exe = _extract_exe_path(command)
                        if exe and os.path.isfile(exe):
                            browsers[key] = exe
                    except OSError:
                        continue
        except OSError:
            continue
        except Exception as exc:
            # Never let a registry quirk stop the search for a browser.
            logger.debug(f"StartMenuInternet lookup failed on this hive: {exc}")
            continue


def _read_app_paths(browsers: dict[str, str]) -> None:
    """Backstop for installs that skip StartMenuInternet registration."""
    try:
        import winreg
    except ImportError:
        return

    for key, exe_name in _APP_PATHS_EXE.items():
        if key in browsers:
            continue
        subpath = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, subpath) as app_key:
                    exe, _ = winreg.QueryValueEx(app_key, "")
                if exe and os.path.isfile(exe):
                    browsers[key] = exe
                    break
            except OSError:
                continue
            except Exception as exc:
                logger.debug(f"App Paths lookup failed for {exe_name}: {exc}")
                continue


def _check_well_known_paths(browsers: dict[str, str]) -> None:
    """Last resort: a short list of common install locations."""
    for key, candidates in _WELL_KNOWN_PATHS.items():
        if key in browsers:
            continue
        for template in candidates:
            path = os.path.expandvars(template)
            if "%" not in path and os.path.isfile(path):
                browsers[key] = path
                break


def _detect_browsers_windows() -> dict[str, str]:
    browsers: dict[str, str] = {}
    try:
        _read_start_menu_internet(browsers)
    except Exception as exc:
        logger.debug(f"registry StartMenuInternet scan failed: {exc}")
    try:
        _read_app_paths(browsers)
    except Exception as exc:
        logger.debug(f"registry App Paths scan failed: {exc}")
    try:
        _check_well_known_paths(browsers)
    except Exception as exc:
        logger.debug(f"well-known browser path scan failed: {exc}")
    return browsers


def _detect_browsers_other() -> dict[str, str]:
    browsers: dict[str, str] = {}
    for key, names in _WHICH_NAMES.items():
        for name in names:
            found = shutil.which(name)
            if found:
                browsers[key] = found
                break
    return browsers


def detect_browsers() -> dict[str, str]:
    """Map each key in PREFERENCE_ORDER to an executable path, for whichever
    of those browsers is actually installed on this machine.

    Never raises: a registry or filesystem error just means that browser is
    reported as not found, since the caller falls back to the OS default
    either way.
    """
    try:
        if sys.platform.startswith("win"):
            return _detect_browsers_windows()
        return _detect_browsers_other()
    except Exception as exc:
        logger.debug(f"browser detection failed entirely: {exc}")
        return {}


def open_html(path: str, order: tuple[str, ...] = PREFERENCE_ORDER) -> str:
    """Open an HTML file in the first available browser from `order`.

    Returns the key of the browser actually used, or "default" when nothing
    in `order` was found or every launch attempt failed - that return value
    is what lets a caller log which browser got it, which is the only way
    to diagnose this from a user's log file after the fact.

    Path is converted with as_uri(): a bare Windows path is not a URL, and
    passing one to webbrowser (or to a browser's argv) mangles the drive
    letter.
    """
    uri = Path(path).as_uri()
    browsers = detect_browsers()
    for key in order:
        exe = browsers.get(key)
        if not exe:
            continue
        try:
            subprocess.Popen([exe, uri])
            return key
        except Exception as exc:
            logger.debug(f"failed to launch {key} at {exe}: {exc}")
            continue
    webbrowser.open(uri)
    return "default"
