"""
Tests for core/browser_open.py.

detect_browsers() touches the registry and the filesystem, and open_html()
launches a subprocess - none of that is safe to exercise for real in CI (a
runner may have no browsers installed at all, or a different set than this
machine), so every test patches detect_browsers() directly, or the registry
readers and subprocess.Popen it is built from.

The registry readers (_read_start_menu_internet, _read_app_paths) do their
own `import winreg` inside the function body. Since Python caches modules in
sys.modules, swapping the entry there before the function runs is enough to
make that import return a fake - the same trick test_keep_awake.py uses for
ctypes.
"""

import sys
from pathlib import Path
from unittest.mock import patch

from core import browser_open


class _FakeKeyHandle:
    """A context manager standing in for a winreg key handle."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeWinReg:
    """A minimal winreg stand-in, configured per test.

    `subkeys` maps a root path to the list of subkey names EnumKey should
    yield for it. `commands` maps a full `subkey\\shell\\open\\command` (or
    App Paths) path to the registry value OpenKey/QueryValueEx should
    return. Anything not listed raises OSError, matching a real missing key.
    """

    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, subkeys=None, commands=None, raise_on_open=None):
        self.subkeys = subkeys or {}
        self.commands = commands or {}
        self.raise_on_open = raise_on_open or set()
        self.opened = []

    def OpenKey(self, hive, subkey):
        full = (hive, subkey)
        self.opened.append(full)
        if full in self.raise_on_open or subkey in self.raise_on_open:
            raise OSError(f"no such key: {subkey}")
        if subkey in self.subkeys or subkey in self.commands:
            return _FakeKeyHandle(subkey)
        raise OSError(f"no such key: {subkey}")

    def EnumKey(self, key, index):
        names = self.subkeys.get(key.name, [])
        if index >= len(names):
            raise OSError("no more data")
        return names[index]

    def QueryValueEx(self, key, name):
        return self.commands[key.name], 1


class TestOpenHtmlOrdering:
    def test_prefers_chrome_when_everything_is_present(self, tmp_path):
        html = tmp_path / "out.html"
        html.write_text("<html></html>")
        browsers = {"chrome": "C:/chrome.exe", "firefox": "C:/firefox.exe", "edge": "C:/edge.exe"}
        with (
            patch.object(browser_open, "detect_browsers", return_value=browsers),
            patch.object(browser_open.subprocess, "Popen") as popen,
        ):
            used = browser_open.open_html(str(html))
        assert used == "chrome"
        popen.assert_called_once()
        args = popen.call_args[0][0]
        assert args[0] == "C:/chrome.exe"
        assert args[1] == Path(html).as_uri()

    def test_falls_back_to_firefox_when_chrome_is_absent(self, tmp_path):
        html = tmp_path / "out.html"
        html.write_text("<html></html>")
        browsers = {"firefox": "C:/firefox.exe", "edge": "C:/edge.exe"}
        with (
            patch.object(browser_open, "detect_browsers", return_value=browsers),
            patch.object(browser_open.subprocess, "Popen") as popen,
        ):
            used = browser_open.open_html(str(html))
        assert used == "firefox"
        assert popen.call_args[0][0][0] == "C:/firefox.exe"

    def test_falls_back_to_edge_when_only_edge_is_present(self, tmp_path):
        html = tmp_path / "out.html"
        html.write_text("<html></html>")
        browsers = {"edge": "C:/edge.exe"}
        with (
            patch.object(browser_open, "detect_browsers", return_value=browsers),
            patch.object(browser_open.subprocess, "Popen") as popen,
        ):
            used = browser_open.open_html(str(html))
        assert used == "edge"
        assert popen.call_args[0][0][0] == "C:/edge.exe"


class TestOpenHtmlFallback:
    def test_uses_webbrowser_when_nothing_is_detected(self, tmp_path):
        html = tmp_path / "out.html"
        html.write_text("<html></html>")
        with (
            patch.object(browser_open, "detect_browsers", return_value={}),
            patch.object(browser_open.webbrowser, "open") as opened,
        ):
            used = browser_open.open_html(str(html))
        assert used == "default"
        opened.assert_called_once_with(Path(html).as_uri())

    def test_a_launch_that_raises_falls_through_to_the_next_candidate(self, tmp_path):
        """
        A detected browser can still fail to launch (moved exe, permission
        error, whatever) - that must not sink the whole open, only that one
        candidate.
        """
        html = tmp_path / "out.html"
        html.write_text("<html></html>")
        browsers = {"chrome": "C:/chrome.exe", "firefox": "C:/firefox.exe"}
        with (
            patch.object(browser_open, "detect_browsers", return_value=browsers),
            patch.object(
                browser_open.subprocess,
                "Popen",
                side_effect=OSError("exe not found"),
            ) as popen,
            patch.object(browser_open.webbrowser, "open") as opened,
        ):
            used = browser_open.open_html(str(html))
        assert used == "default"
        assert popen.call_count == 2
        opened.assert_called_once_with(Path(html).as_uri())


class TestDetectBrowsersNeverRaises:
    def test_a_registry_read_that_raises_does_not_propagate(self, monkeypatch):
        monkeypatch.setattr(browser_open.sys, "platform", "win32")
        with (
            patch.object(
                browser_open,
                "_read_start_menu_internet",
                side_effect=OSError("registry unavailable"),
            ),
            patch.object(browser_open, "_read_app_paths"),
            patch.object(browser_open, "_check_well_known_paths"),
        ):
            assert browser_open.detect_browsers() == {}

    def test_detection_itself_never_raises_even_on_a_totally_broken_platform(self, monkeypatch):
        monkeypatch.setattr(browser_open.sys, "platform", "win32")
        with patch.object(
            browser_open, "_detect_browsers_windows", side_effect=RuntimeError("boom")
        ):
            assert browser_open.detect_browsers() == {}


class TestExtractExePath:
    def test_quoted_command_string(self):
        assert (
            browser_open._extract_exe_path('"C:\\Program Files\\Chrome\\chrome.exe" -- "%1"')
            == "C:\\Program Files\\Chrome\\chrome.exe"
        )

    def test_unquoted_command_string(self):
        assert browser_open._extract_exe_path("C:\\chrome.exe %1") == "C:\\chrome.exe"

    def test_empty_command_string(self):
        assert browser_open._extract_exe_path("") is None


class TestKeyForSubkeyName:
    def test_matches_chrome_case_insensitively(self):
        assert browser_open._key_for_subkey_name("Google Chrome") == "chrome"

    def test_matches_firefox_variants(self):
        assert browser_open._key_for_subkey_name("Firefox-308046B0AF4A39CB") == "firefox"
        assert browser_open._key_for_subkey_name("Mozilla Firefox") == "firefox"

    def test_edge_does_not_match_chrome(self):
        assert browser_open._key_for_subkey_name("Microsoft Edge") == "edge"

    def test_unknown_subkey_is_none(self):
        assert browser_open._key_for_subkey_name("Internet Explorer") is None


class TestReadStartMenuInternet:
    def test_finds_a_browser_via_the_command_string(self, monkeypatch):
        fake = FakeWinReg(
            subkeys={r"Software\Clients\StartMenuInternet": ["Google Chrome"]},
            commands={
                r"Google Chrome\shell\open\command": '"C:\\chrome.exe" -- "%1"',
            },
        )
        monkeypatch.setitem(sys.modules, "winreg", fake)
        monkeypatch.setattr(browser_open.os.path, "isfile", lambda p: True)
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {"chrome": "C:\\chrome.exe"}

    def test_a_key_that_does_not_map_to_a_known_browser_is_skipped(self, monkeypatch):
        fake = FakeWinReg(subkeys={r"Software\Clients\StartMenuInternet": ["Internet Explorer"]})
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {}

    def test_an_already_found_key_is_not_looked_up_again(self, monkeypatch):
        fake = FakeWinReg(subkeys={r"Software\Clients\StartMenuInternet": ["Google Chrome"]})
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers = {"chrome": "C:\\already\\chrome.exe"}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {"chrome": "C:\\already\\chrome.exe"}
        # The command subkey was never opened because chrome was already found.
        assert not any("shell" in str(entry) for entry in fake.opened)

    def test_a_missing_command_subkey_is_swallowed(self, monkeypatch):
        fake = FakeWinReg(subkeys={r"Software\Clients\StartMenuInternet": ["Google Chrome"]})
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {}

    def test_a_missing_start_menu_internet_key_on_a_hive_is_swallowed(self, monkeypatch):
        fake = FakeWinReg()
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {}

    def test_a_non_os_error_from_a_hive_does_not_propagate(self, monkeypatch):
        class ExplodingWinReg(FakeWinReg):
            def OpenKey(self, hive, subkey):
                raise ValueError("registry is on fire")

        monkeypatch.setitem(sys.modules, "winreg", ExplodingWinReg())
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {}

    def test_no_winreg_module_is_a_no_op(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winreg", None)
        browsers: dict[str, str] = {}
        browser_open._read_start_menu_internet(browsers)
        assert browsers == {}


class TestReadAppPaths:
    def test_finds_a_browser_via_app_paths(self, monkeypatch):
        subpath = r"Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
        fake = FakeWinReg(commands={subpath: "C:\\firefox.exe"})
        monkeypatch.setitem(sys.modules, "winreg", fake)
        monkeypatch.setattr(browser_open.os.path, "isfile", lambda p: True)
        browsers: dict[str, str] = {}
        browser_open._read_app_paths(browsers)
        assert browsers == {"firefox": "C:\\firefox.exe"}

    def test_an_already_found_key_is_skipped(self, monkeypatch):
        fake = FakeWinReg()
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers = {"chrome": "C:\\already\\chrome.exe", "firefox": "x", "edge": "y"}
        browser_open._read_app_paths(browsers)
        assert fake.opened == []

    def test_missing_app_paths_entries_are_swallowed(self, monkeypatch):
        fake = FakeWinReg()
        monkeypatch.setitem(sys.modules, "winreg", fake)
        browsers: dict[str, str] = {}
        browser_open._read_app_paths(browsers)
        assert browsers == {}

    def test_a_non_os_error_does_not_propagate(self, monkeypatch):
        class ExplodingWinReg(FakeWinReg):
            def OpenKey(self, hive, subkey):
                raise ValueError("registry is on fire")

        monkeypatch.setitem(sys.modules, "winreg", ExplodingWinReg())
        browsers: dict[str, str] = {}
        browser_open._read_app_paths(browsers)
        assert browsers == {}

    def test_no_winreg_module_is_a_no_op(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winreg", None)
        browsers: dict[str, str] = {}
        browser_open._read_app_paths(browsers)
        assert browsers == {}


class TestCheckWellKnownPaths:
    def test_finds_the_first_existing_candidate_per_key(self, monkeypatch):
        monkeypatch.setattr(
            browser_open.os.path,
            "isfile",
            lambda p: p.endswith("Google\\Chrome\\Application\\chrome.exe"),
        )
        browsers: dict[str, str] = {}
        browser_open._check_well_known_paths(browsers)
        assert "chrome" in browsers
        assert "firefox" not in browsers
        assert "edge" not in browsers

    def test_an_already_found_key_is_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(browser_open.os.path, "isfile", lambda p: True)
        browsers = {"chrome": "C:\\already\\chrome.exe"}
        browser_open._check_well_known_paths(browsers)
        assert browsers["chrome"] == "C:\\already\\chrome.exe"

    def test_nothing_found_leaves_the_map_untouched(self, monkeypatch):
        monkeypatch.setattr(browser_open.os.path, "isfile", lambda p: False)
        browsers: dict[str, str] = {}
        browser_open._check_well_known_paths(browsers)
        assert browsers == {}


class TestDetectBrowsersWindows:
    def test_combines_all_three_sources(self, monkeypatch):
        with (
            patch.object(
                browser_open,
                "_read_start_menu_internet",
                side_effect=lambda b: b.update({"chrome": "C:\\chrome.exe"}),
            ),
            patch.object(
                browser_open,
                "_read_app_paths",
                side_effect=lambda b: b.update({"firefox": "C:\\firefox.exe"}),
            ),
            patch.object(
                browser_open,
                "_check_well_known_paths",
                side_effect=lambda b: b.update({"edge": "C:\\edge.exe"}),
            ),
        ):
            browsers = browser_open._detect_browsers_windows()
        assert browsers == {
            "chrome": "C:\\chrome.exe",
            "firefox": "C:\\firefox.exe",
            "edge": "C:\\edge.exe",
        }

    def test_a_failure_in_one_source_does_not_block_the_others(self):
        with (
            patch.object(
                browser_open, "_read_start_menu_internet", side_effect=RuntimeError("boom")
            ),
            patch.object(
                browser_open,
                "_read_app_paths",
                side_effect=lambda b: b.update({"firefox": "C:\\firefox.exe"}),
            ),
            patch.object(browser_open, "_check_well_known_paths"),
        ):
            browsers = browser_open._detect_browsers_windows()
        assert browsers == {"firefox": "C:\\firefox.exe"}

    def test_the_well_known_path_stage_failing_does_not_propagate(self):
        with (
            patch.object(browser_open, "_read_start_menu_internet"),
            patch.object(browser_open, "_read_app_paths"),
            patch.object(browser_open, "_check_well_known_paths", side_effect=RuntimeError()),
        ):
            assert browser_open._detect_browsers_windows() == {}


class TestDetectBrowsersOther:
    def test_uses_the_first_matching_which_name_per_key(self, monkeypatch):
        def fake_which(name):
            return {"google-chrome": "/usr/bin/google-chrome", "firefox": "/usr/bin/firefox"}.get(
                name
            )

        monkeypatch.setattr(browser_open.shutil, "which", fake_which)
        browsers = browser_open._detect_browsers_other()
        assert browsers == {"chrome": "/usr/bin/google-chrome", "firefox": "/usr/bin/firefox"}

    def test_falls_through_which_name_aliases(self, monkeypatch):
        def fake_which(name):
            return "/usr/bin/chromium" if name == "chromium" else None

        monkeypatch.setattr(browser_open.shutil, "which", fake_which)
        browsers = browser_open._detect_browsers_other()
        assert browsers == {"chrome": "/usr/bin/chromium"}

    def test_nothing_found_is_an_empty_map(self, monkeypatch):
        monkeypatch.setattr(browser_open.shutil, "which", lambda name: None)
        assert browser_open._detect_browsers_other() == {}


class TestDetectBrowsersDispatch:
    def test_dispatches_to_the_windows_path(self, monkeypatch):
        monkeypatch.setattr(browser_open.sys, "platform", "win32")
        with patch.object(
            browser_open, "_detect_browsers_windows", return_value={"chrome": "C:\\chrome.exe"}
        ) as windows:
            assert browser_open.detect_browsers() == {"chrome": "C:\\chrome.exe"}
        windows.assert_called_once()

    def test_dispatches_to_the_non_windows_path(self, monkeypatch):
        monkeypatch.setattr(browser_open.sys, "platform", "linux")
        with patch.object(
            browser_open, "_detect_browsers_other", return_value={"firefox": "/usr/bin/firefox"}
        ) as other:
            assert browser_open.detect_browsers() == {"firefox": "/usr/bin/firefox"}
        other.assert_called_once()
