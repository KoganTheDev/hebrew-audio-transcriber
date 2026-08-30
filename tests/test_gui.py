"""
Tests for GUI components (limited GUI testing due to PyQt5 complexity).

FileSelectStep tests build real widgets under Qt's "offscreen" platform
plugin (verified to work in this environment) rather than mocking QWidget
internals - the drag-and-drop/list-row logic these tests care about (folder
expansion, dedup, removal, signal shape) lives in real methods on the real
widget, and mocking around it would just re-describe the implementation.
"""

import os

# Must be set before PyQt5 is imported - Qt reads the platform plugin at import
# time, so the noqa: E402 below is load-bearing, not a style waiver.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def hardware_stub():
    """Just enough of HardwareDetector's interface for FileSelectStep.__init__."""
    hw = MagicMock()
    hw.get_hardware_info.return_value = {
        "cpu_cores": 4, "ram_gb": 8, "has_gpu": False, "gpu_name": "",
    }
    return hw


@pytest.fixture
def file_select_step(qapp, hardware_stub):
    from speech_to_text.gui.steps.file_select import FileSelectStep
    return FileSelectStep(hardware_stub)


class TestGUI:

    @pytest.mark.skipif(True, reason="PyQt5 GUI testing requires X11 or mocking display")
    def test_main_window_creation(self):
        """Test main window creation."""
        pass

    @patch('speech_to_text.gui.main_window.QMainWindow')
    def test_transcription_thread_initialization(self, mock_main_window):
        """TranscriptionThread takes a batch: a list of files and matching durations."""
        from speech_to_text.gui.main_window import TranscriptionThread

        thread = TranscriptionThread(
            audio_files=["a.mp3", "b.mp3"],
            model_size="small",
            device="cpu",
            durations=[10.0, 20.0],
        )

        assert thread.audio_files == ["a.mp3", "b.mp3"]
        assert thread.model_size == "small"
        assert thread.device == "cpu"
        assert thread.options.audio_durations == [10.0, 20.0]
        assert thread.options.total_duration == 30.0


class TestFileSelectStepFolderExpansion:
    """Dropping a folder expands to the supported audio directly inside it."""

    def test_nonrecursive_sorted_and_filtered_to_supported_formats(self, qapp, tmp_path):
        from speech_to_text.gui.steps.file_select import FileSelectStep

        (tmp_path / "b.wav").write_bytes(b"")
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "notes.txt").write_bytes(b"")  # unsupported - must be filtered out
        subfolder = tmp_path / "subfolder"
        subfolder.mkdir()
        (subfolder / "c.wav").write_bytes(b"")  # nested - must NOT be recursed into

        found = FileSelectStep._expand_directory(str(tmp_path))

        assert found == sorted(found)
        names = {os.path.basename(f) for f in found}
        assert names == {"a.mp3", "b.wav"}


class TestFileSelectStepFileList:

    def test_files_selected_signal_carries_paths_and_total_duration(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui.steps import file_select as file_select_module
        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 30)

        f1, f2 = tmp_path / "one.wav", tmp_path / "two.wav"
        f1.write_bytes(b"")
        f2.write_bytes(b"")

        received = []
        file_select_step.files_selected.connect(
            lambda paths, total: received.append((paths, total))
        )
        file_select_step._add_files([str(f1), str(f2)])

        assert len(received) == 1
        paths, total = received[0]
        assert paths == [str(f1), str(f2)]
        assert total == 60

    def test_a_second_drop_of_the_same_file_does_not_duplicate(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui.steps import file_select as file_select_module
        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 10)

        f = tmp_path / "one.wav"
        f.write_bytes(b"")

        file_select_step._add_files([str(f)])
        file_select_step._add_files([str(f)])  # dropped again

        assert file_select_step.selected_files == [str(f)]

    def test_removing_a_file_updates_the_list_and_re_emits(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui.steps import file_select as file_select_module
        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 10)

        f1, f2 = tmp_path / "one.wav", tmp_path / "two.wav"
        f1.write_bytes(b"")
        f2.write_bytes(b"")
        file_select_step._add_files([str(f1), str(f2)])

        received = []
        file_select_step.files_selected.connect(
            lambda paths, total: received.append((paths, total))
        )
        file_select_step._remove_file(str(f1))

        assert file_select_step.selected_files == [str(f2)]
        assert received[-1] == ([str(f2)], 10)
        assert str(f1) not in file_select_step._rows

    def test_multi_file_summary_shows_count_and_total_duration(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui.steps import file_select as file_select_module
        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 90)

        f1, f2 = tmp_path / "one.wav", tmp_path / "two.wav"
        f1.write_bytes(b"")
        f2.write_bytes(b"")
        file_select_step._add_files([str(f1), str(f2)])

        summary = file_select_step.summary_label.text()
        assert "2" in summary  # file count
        assert "3" in summary  # 180s total -> 3m

    def test_reset_clears_the_list(self, file_select_step, tmp_path, monkeypatch):
        from speech_to_text.gui.steps import file_select as file_select_module
        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 10)

        f = tmp_path / "one.wav"
        f.write_bytes(b"")
        file_select_step._add_files([str(f)])

        file_select_step.reset()

        assert file_select_step.selected_files == []
        assert file_select_step.total_duration == 0


class TestTranscriptionStepOpenButton:
    """
    The output is an editable HTML application now, not a text file, so the
    run ends with a way into it rather than just a path to go hunting for.
    """

    @pytest.fixture
    def step(self, qapp):
        from speech_to_text.gui.steps.transcription import TranscriptionStep
        return TranscriptionStep()

    def test_open_button_is_hidden_until_a_run_finishes(self, step):
        assert step.result_widget.isHidden()
        step.show_result("C:/tmp/meeting_transcription.html")
        assert not step.result_widget.isHidden()

    def test_opens_the_saved_transcript_as_a_file_uri(self, step):
        """
        A bare Windows path is not a URL - webbrowser would mangle the drive
        letter into a scheme. as_uri() is what makes it openable.
        """
        step.show_result("C:/tmp/meeting_transcription.html")
        with patch("speech_to_text.gui.steps.transcription.webbrowser.open") as opened:
            step._open_result()
        opened.assert_called_once()
        assert opened.call_args[0][0].startswith("file:///")
        assert opened.call_args[0][0].endswith("meeting_transcription.html")

    def test_does_nothing_before_there_is_a_result(self, step):
        with patch("speech_to_text.gui.steps.transcription.webbrowser.open") as opened:
            step._open_result()
        opened.assert_not_called()

    def test_a_failure_to_open_is_not_fatal(self, step):
        """The path is on screen regardless - losing the window over it would not be."""
        step.show_result("C:/tmp/meeting_transcription.html")
        with patch("speech_to_text.gui.steps.transcription.webbrowser.open",
                   side_effect=OSError("no browser")):
            step._open_result()

    def test_button_follows_a_live_language_switch(self, step):
        from speech_to_text.gui import i18n
        i18n.set_language("en")
        step.retranslate()
        assert step.open_button.text() == "Open transcript"
        i18n.set_language("he")
        step.retranslate()
        assert step.open_button.text() == "פתיחת התמלול"
        i18n.set_language("en")


class TestDropZoneEventPath:
    """
    Drag-and-drop exercised through Qt's own event delivery, not by calling
    _add_files() directly.

    Every other drop test in this file reaches past the event handlers and
    invokes _add_files() itself, so the wiring between them - setAcceptDrops,
    the three assigned handlers, and the mimeData/URL unpacking in _drop() -
    was covered by nothing. Deleting any one of those lines would have left
    the suite green while the drop zone became inert, which is exactly the
    kind of silent loss that prompts "was this feature ever there?".

    The handlers are assigned onto the QFrame instance rather than defined on
    a subclass (see FileSelectStep._init_ui). That works, but it is the sort
    of thing a refactor rewrites without thinking, so it is worth pinning
    from the outside.
    """

    @staticmethod
    def _mime(*paths):
        from PyQt5.QtCore import QMimeData, QUrl
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return mime

    def test_a_real_drop_event_adds_the_file(self, qapp, file_select_step, tmp_path):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent

        audio = tmp_path / "meeting.wav"
        audio.write_bytes(b"RIFF")
        mime = self._mime(str(audio))

        received = []
        file_select_step.files_selected.connect(
            lambda paths, seconds: received.append(paths)
        )

        enter = QDragEnterEvent(
            QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        qapp.sendEvent(file_select_step.drop_zone, enter)
        assert enter.isAccepted(), (
            "the drop zone refused a drag carrying file URLs - _drag_enter is "
            "not reaching the zone, so nothing can ever be dropped on it"
        )

        drop = QDropEvent(
            QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        qapp.sendEvent(file_select_step.drop_zone, drop)
        assert received, "a dropped file produced no files_selected signal"
        assert received[0][0].endswith("meeting.wav")

    def test_the_zone_accepts_drops_at_all(self, file_select_step):
        """
        The one line the whole feature hangs off. Without it Windows never
        offers the window as a drop target and the cursor shows "no entry"
        before any handler could run.
        """
        assert file_select_step.drop_zone.acceptDrops()

    def test_a_drag_carrying_no_urls_is_refused(self, qapp, file_select_step):
        """Dragged text is not a file - the zone should not light up for it."""
        from PyQt5.QtCore import QMimeData, QPoint, Qt
        from PyQt5.QtGui import QDragEnterEvent

        mime = QMimeData()
        mime.setText("just some text")
        enter = QDragEnterEvent(
            QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        qapp.sendEvent(file_select_step.drop_zone, enter)
        assert not enter.isAccepted()


class TestDropZoneKeyboardAccess:
    """
    Before this step the drop zone was a bare QFrame with no focus policy
    and no key handler at all (see DropZone in gui/widgets.py) - a
    keyboard-only user could never reach it, and since it doubles as the
    only "browse" control in the app, that meant they could never select a
    file at all. These pin the fix rather than just eyeballing it.
    """

    def test_the_zone_is_a_real_tab_stop(self, file_select_step):
        from PyQt5.QtCore import Qt
        assert file_select_step.drop_zone.focusPolicy() == Qt.StrongFocus

    @pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter])
    def test_space_and_enter_open_the_browse_dialog(self, qapp, file_select_step, key):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        with patch(
            "speech_to_text.gui.steps.file_select.QFileDialog.getOpenFileNames",
            return_value=([], ""),
        ) as dialog:
            qapp.sendEvent(file_select_step.drop_zone, event)
        dialog.assert_called_once()

    def test_an_unrelated_key_does_not_open_the_dialog(self, qapp, file_select_step):
        """A key the zone doesn't own must not accidentally trigger browse."""
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier)
        with patch(
            "speech_to_text.gui.steps.file_select.QFileDialog.getOpenFileNames"
        ) as dialog:
            qapp.sendEvent(file_select_step.drop_zone, event)
        dialog.assert_not_called()

    def test_accessible_name_and_description_are_set(self, file_select_step):
        """
        Set once, from i18n, rather than left at Qt's default (empty) -
        without these a screen reader announces the zone as an unlabeled
        frame, the same silence a sighted keyboard user is spared by the
        StrongFocus/keyPressEvent work above.
        """
        assert file_select_step.drop_zone.accessibleName()
        assert file_select_step.drop_zone.accessibleDescription()


class TestKeyboardFocusTracker:
    """
    gui/focus.py's modality gate: the ring should be scoped to a keyboard
    session in progress, not to "some widget merely has focus" (native
    :focus's actual behaviour, and the bug this module exists to fix - see
    its module docstring).
    """

    def test_tab_keydown_marks_the_newly_focused_widget(self, qapp):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QKeyEvent
        from PyQt5.QtWidgets import QPushButton

        from speech_to_text.gui.focus import PROPERTY, KeyboardFocusTracker

        tracker = KeyboardFocusTracker(qapp)
        btn = QPushButton()
        btn.show()
        try:
            qapp.sendEvent(btn, QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier))
            btn.setFocus()
            qapp.processEvents()
            assert btn.property(PROPERTY) is True
        finally:
            btn.setParent(None)
            btn.deleteLater()
            tracker.deleteLater()

    def test_a_click_retracts_the_ring_even_when_focus_does_not_move(self, qapp):
        """
        Clicking a non-focusable area (a label, a panel, the window ground)
        leaves focus exactly where it was, so focusChanged never fires. The
        property lives on the widget, not on a root element the way the JS
        original's data-kbd does, so without an explicit retraction the ring
        stays painted on a widget the user has stopped driving by keyboard.
        """
        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QKeyEvent, QMouseEvent
        from PyQt5.QtWidgets import QPushButton

        from speech_to_text.gui.focus import PROPERTY, KeyboardFocusTracker

        tracker = KeyboardFocusTracker(qapp)
        btn = QPushButton()
        btn.show()
        try:
            qapp.sendEvent(btn, QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier))
            btn.setFocus()
            qapp.processEvents()
            assert btn.property(PROPERTY) is True, "precondition: keyboard session is on"

            # Deliberately NOT sent to btn, and btn keeps focus throughout.
            qapp.sendEvent(tracker, QMouseEvent(
                QEvent.MouseButtonPress, QPoint(0, 0),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            ))
            qapp.processEvents()
            assert btn.hasFocus(), "focus must not have moved for this to be the case under test"
            assert btn.property(PROPERTY) is False
        finally:
            btn.setParent(None)
            btn.deleteLater()
            tracker.deleteLater()

    def test_a_mouse_click_does_not_mark_the_focused_widget(self, qapp):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtWidgets import QPushButton

        from speech_to_text.gui.focus import PROPERTY, KeyboardFocusTracker

        tracker = KeyboardFocusTracker(qapp)
        btn = QPushButton()
        btn.show()
        try:
            click = QMouseEvent(
                QEvent.MouseButtonPress, btn.rect().center(),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            )
            qapp.sendEvent(btn, click)
            btn.setFocus()
            qapp.processEvents()
            assert not btn.property(PROPERTY)
        finally:
            btn.setParent(None)
            btn.deleteLater()
            tracker.deleteLater()


class TestMainWindowKeyboardGuards:
    """
    MainWindow._on_advance_shortcut: Enter is wired at the window level to
    act like clicking Next (see MainWindow._init_shortcuts), which would be
    actively harmful on step 2 if it fired while the user is mid-entry in
    the speaker-count QSpinBox - typing "10" and pressing Enter must
    confirm the number, not silently skip to Transcribing.

    Builds a real MainWindow rather than testing the guard in isolation:
    HardwareDetector is stubbed (its real implementation spawns a
    background calibration subprocess - see CalibrationThread - which has
    no place in a unit test), but everything downstream of that, including
    QApplication.focusWidget() actually reflecting which widget has focus,
    is exercised for real.
    """

    @pytest.fixture
    def main_window(self, qapp, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module

        hw = MagicMock()
        # Not None - MainWindow only starts CalibrationThread's background
        # subprocess when this is unset.
        hw.tiny_seconds_per_audio_second = 1.0
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4, "ram_gb": 8, "has_gpu": False, "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)

        window = main_window_module.MainWindow()
        window.show()
        yield window
        window.close()

    def test_enter_does_not_advance_while_the_spinbox_has_focus(self, qapp, main_window):
        # setFocus() is a no-op on a widget Qt considers invisible, and
        # model_step starts hidden behind file_step in the QStackedWidget -
        # bring it to the front first, the same way _go_next() would.
        main_window.stacked_widget.setCurrentWidget(main_window.model_step)
        main_window.model_step.speaker_count_spin.setFocus()
        qapp.processEvents()
        assert qapp.focusWidget() is main_window.model_step.speaker_count_spin

        with patch.object(main_window.next_btn, "click") as click:
            main_window._on_advance_shortcut()
        click.assert_not_called()

    def test_enter_advances_when_focus_is_elsewhere(self, qapp, main_window):
        main_window.file_step.drop_zone.setFocus()
        qapp.processEvents()
        main_window.next_btn.setEnabled(True)
        main_window.next_btn.show()

        with patch.object(main_window.next_btn, "click") as click:
            main_window._on_advance_shortcut()
        click.assert_called_once()

    def test_escape_goes_back_only_on_model_select(self, main_window):
        from speech_to_text.gui.steps import Step

        main_window.current_step = Step.FILE_SELECT
        with patch.object(main_window, "_go_back") as go_back:
            main_window._on_escape_shortcut()
        go_back.assert_not_called()

        main_window.current_step = Step.MODEL_SELECT
        with patch.object(main_window, "_go_back") as go_back:
            main_window._on_escape_shortcut()
        go_back.assert_called_once()
