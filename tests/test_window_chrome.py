"""
Tests for gui/window_chrome.py: the dark title bar.

The DWM call itself is replaced by a recorder - what matters here is which
attributes are asked for, with which colours, on which windows, and how
often. Whether Windows honours them is checked on a real window instead.
"""

import pytest
from PyQt5.QtWidgets import QDialog, QLabel, QWidget

from gui import window_chrome
from gui.theme import COLORS


@pytest.fixture
def calls(monkeypatch):
    """Record every attribute set; pretend to be Windows."""
    recorded: list[tuple[int, int]] = []

    def fake_set(hwnd, attribute, value):
        recorded.append((attribute, value))
        return True

    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    monkeypatch.setattr(window_chrome, "_set_attribute", fake_set)
    return recorded


def test_colorref_is_bgr():
    # Win32 COLORREF packs blue highest: #181825 -> 0x00251818.
    assert window_chrome._colorref("#181825") == 0x00251818
    assert window_chrome._colorref("#cdd6f4") == 0x00F4D6CD


def test_asks_for_dark_mode_and_the_app_colours(qtbot, calls):
    w = QWidget()
    qtbot.addWidget(w)
    window_chrome.apply_title_bar_colors(w)

    assert calls == [
        (window_chrome._DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
        (window_chrome._DWMWA_CAPTION_COLOR, window_chrome._colorref(COLORS["bg_secondary"])),
        (window_chrome._DWMWA_TEXT_COLOR, window_chrome._colorref(COLORS["text_primary"])),
    ]


def test_older_windows_10_gets_the_old_dark_mode_attribute(qtbot, monkeypatch):
    recorded = []

    def fake_set(hwnd, attribute, value):
        recorded.append(attribute)
        # Builds before 20H1 reject 20 and only know 19.
        return attribute != window_chrome._DWMWA_USE_IMMERSIVE_DARK_MODE

    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    monkeypatch.setattr(window_chrome, "_set_attribute", fake_set)
    w = QWidget()
    qtbot.addWidget(w)
    window_chrome.apply_title_bar_colors(w)

    assert recorded[:2] == [
        window_chrome._DWMWA_USE_IMMERSIVE_DARK_MODE,
        window_chrome._DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
    ]


def test_does_nothing_off_windows(qtbot, calls, monkeypatch):
    monkeypatch.setattr(window_chrome.sys, "platform", "linux")
    w = QWidget()
    qtbot.addWidget(w)
    window_chrome.apply_title_bar_colors(w)
    assert calls == []


def test_a_failing_dwm_call_never_breaks_the_window(qtbot, monkeypatch):
    def boom(hwnd, attribute, value):
        raise OSError("no dwmapi")

    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    monkeypatch.setattr(window_chrome, "_set_attribute", boom)
    w = QWidget()
    qtbot.addWidget(w)
    window_chrome.apply_title_bar_colors(w)  # must not raise


def test_every_window_is_coloured_once_and_children_never(qapp, qtbot, monkeypatch):
    coloured: list[QWidget] = []
    monkeypatch.setattr(window_chrome, "apply_title_bar_colors", coloured.append)
    colorizer = window_chrome.TitleBarColorizer(qapp)
    try:
        dialog = QDialog()
        qtbot.addWidget(dialog)
        child = QLabel("x", dialog)
        dialog.show()
        dialog.hide()
        dialog.show()

        assert coloured.count(dialog) == 1
        assert child not in coloured
    finally:
        qapp.removeEventFilter(colorizer)
        colorizer.deleteLater()


def test_the_filter_comes_off_before_the_app_quits(qapp, qtbot, monkeypatch):
    """Left installed through teardown, it crashed the app at exit."""
    coloured: list[QWidget] = []
    monkeypatch.setattr(window_chrome, "apply_title_bar_colors", coloured.append)
    colorizer = window_chrome.TitleBarColorizer(qapp)
    try:
        colorizer.uninstall()  # what aboutToQuit triggers
        dialog = QDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        assert coloured == []
    finally:
        colorizer.deleteLater()
