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


class TestTranscriptionStepFolderButton:
    """
    "Open transcript" only ever opened the transcript file itself - the
    other thing people reach for right after a run finishes is the folder
    it landed in, e.g. to attach the file elsewhere or just confirm it's
    really there.
    """

    @pytest.fixture
    def step(self, qapp):
        from speech_to_text.gui.steps.transcription import TranscriptionStep
        return TranscriptionStep()

    def test_opens_the_containing_folder(self, step):
        step.show_result("C:/tmp/meeting/meeting_transcription.html")
        with patch("speech_to_text.gui.steps.transcription.QDesktopServices.openUrl") as opened:
            step._open_folder()
        opened.assert_called_once()
        url = opened.call_args[0][0]
        assert url.toLocalFile().replace("\\", "/").rstrip("/") == "C:/tmp/meeting"

    def test_does_nothing_before_there_is_a_result(self, step):
        with patch("speech_to_text.gui.steps.transcription.QDesktopServices.openUrl") as opened:
            step._open_folder()
        opened.assert_not_called()

    def test_a_failure_to_open_is_not_fatal(self, step):
        step.show_result("C:/tmp/meeting/meeting_transcription.html")
        with patch("speech_to_text.gui.steps.transcription.QDesktopServices.openUrl",
                   side_effect=OSError("no shell")):
            step._open_folder()

    def test_button_follows_a_live_language_switch(self, step):
        from speech_to_text.gui import i18n
        i18n.set_language("en")
        step.retranslate()
        assert step.folder_button.text() == "Show in folder"
        i18n.set_language("he")
        step.retranslate()
        assert step.folder_button.text() == "הצגה בתיקייה"
        i18n.set_language("en")


class TestTranscriptionStepBatchStrip:
    """
    Which file is running, in a ten-file batch, used to be legible only by
    catching the status line at the right instant. set_batch_files +
    update_progress's w_file_progress handling (see transcription.py) make
    it a persistent, always-visible strip instead.
    """

    @pytest.fixture
    def step(self, qapp):
        from speech_to_text.gui.steps.transcription import TranscriptionStep
        return TranscriptionStep()

    @staticmethod
    def _batch_files(n):
        return [f"file{i}.wav" for i in range(1, n + 1)]

    def test_hidden_for_a_single_file_run(self, step):
        step.set_batch_files(["only.wav"])
        assert step.batch_strip.isHidden()

    def test_shown_for_a_batch(self, step):
        step.set_batch_files(self._batch_files(10))
        assert not step.batch_strip.isHidden()
        assert len(step._batch_segment_frames) == 10

    def test_w_file_progress_moves_the_strip_and_updates_the_readout(self, step):
        from speech_to_text.core.progress_scale import STATUS_ONLY_PERCENT

        step.set_batch_files(self._batch_files(10))
        step.update_progress(
            "w_file_progress", {"i": 3, "n": 10, "name": "file3.wav"}, STATUS_ONLY_PERCENT
        )

        assert step.batch_readout.text() == "3 / 10"
        # Segments 1-2 done, 3 current, 4-10 pending - checked via the
        # accent fill that only the current segment's stylesheet carries.
        from speech_to_text.gui.theme import COLORS
        styles = [seg.styleSheet() for seg in step._batch_segment_frames]
        assert COLORS['accent'] in styles[2]
        assert COLORS['success'] in styles[0]
        assert COLORS['success'] in styles[1]
        assert COLORS['accent'] not in styles[0]
        assert COLORS['accent'] not in styles[3]

    def test_each_segment_carries_its_own_filename(self, step):
        filenames = self._batch_files(3)
        step.set_batch_files(filenames)
        for seg, name in zip(step._batch_segment_frames, filenames):
            assert seg.toolTip() == name
            assert seg.accessibleName() == name


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


class TestMainWindowStepNavigation:
    """
    _set_step (see main_window.py) is the single funnel every navigation
    method now routes through - _go_back, _go_next, _start_transcription,
    _return_to_model_select, and _reset used to each hand-roll
    setCurrentIndex + back_btn.show()/hide() + next_btn enablement
    themselves. These pin the two things that funnel was built to
    guarantee: the step indicator actually reflects self.current_step
    after each transition, and next_btn's single clicked connection
    (_on_next_clicked) reaches the right handler for its current mode
    without the old disconnect/reconnect dance.
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

    def test_forward_and_back_update_the_step_indicator(self, main_window):
        from speech_to_text.gui.steps import Step

        assert main_window.step_indicator._current_step == Step.FILE_SELECT

        main_window.file_step.selected_files = ["a.wav"]
        main_window.next_btn.setEnabled(True)
        main_window._go_next()

        assert main_window.current_step == Step.MODEL_SELECT
        assert main_window.stacked_widget.currentWidget() is main_window.model_step
        assert main_window.step_indicator._current_step == Step.MODEL_SELECT
        assert main_window.back_btn.isVisible()

        main_window._go_back()

        assert main_window.current_step == Step.FILE_SELECT
        assert main_window.stacked_widget.currentWidget() is main_window.file_step
        assert main_window.step_indicator._current_step == Step.FILE_SELECT
        assert not main_window.back_btn.isVisible()

    def test_next_button_click_dispatches_to_go_next_in_next_mode(self, main_window):
        assert main_window._next_btn_mode == "next"
        # A disabled QPushButton silently swallows .click() - enable it
        # first (this fixture starts with no file selected, which is what
        # leaves it disabled at construction).
        main_window.next_btn.setEnabled(True)
        with patch.object(main_window, "_go_next") as go_next, \
             patch.object(main_window, "_reset") as reset:
            main_window.next_btn.click()
        go_next.assert_called_once()
        reset.assert_not_called()

    def test_next_button_click_dispatches_to_reset_in_new_file_mode(self, main_window):
        """
        A completed run switches next_btn to "New File" mode (see
        _on_transcription_complete) without ever touching
        next_btn.clicked's connections - _on_next_clicked reads
        self._next_btn_mode instead. Pinning that a real .click() reaches
        _reset in this mode is what the old disconnect/reconnect dance
        used to accomplish by rewiring the signal itself.
        """
        main_window._set_next_button_mode("new_file")
        main_window.next_btn.setEnabled(True)
        with patch.object(main_window, "_go_next") as go_next, \
             patch.object(main_window, "_reset") as reset:
            main_window.next_btn.click()
        reset.assert_called_once()
        go_next.assert_not_called()

    def test_reset_returns_to_step_one(self, main_window):
        from speech_to_text.gui.steps import Step

        main_window.selected_files = ["a.wav"]
        main_window.selected_model = "tiny"
        main_window.audio_duration = 120
        main_window._set_next_button_mode("new_file")

        main_window._reset()

        assert main_window.current_step == Step.FILE_SELECT
        assert main_window.stacked_widget.currentWidget() is main_window.file_step
        assert main_window.step_indicator._current_step == Step.FILE_SELECT
        assert main_window.selected_files == []
        assert main_window.selected_model is None
        assert main_window.audio_duration == 0
        assert main_window._next_btn_mode == "next"
        assert not main_window.back_btn.isVisible()
        assert not main_window.next_btn.isEnabled()


class TestMainWindowCancelConfirm:
    """
    Cancel on step 3 stops a possibly 40-minute run with no further
    confirmation, so it's a two-press control (see
    MainWindow._on_cancel_clicked) rather than a single click - the first
    press only arms it, the second actually cancels.
    """

    @pytest.fixture
    def main_window(self, qapp, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module
        from speech_to_text.gui.steps import Step

        hw = MagicMock()
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
        # Simulate being mid-run on step 3, with a live thread stub so
        # _cancel_transcription's disconnect/stop/wait calls have something
        # real (well, MagicMock-real) to act on.
        window.current_step = Step.TRANSCRIPTION
        window.transcription_thread = MagicMock()
        window.cancel_btn.show()
        yield window
        window.close()

    def test_first_press_arms_but_does_not_stop_the_thread(self, main_window):
        with patch.object(main_window, "_cancel_transcription") as cancel:
            main_window._on_cancel_clicked()
        cancel.assert_not_called()
        assert main_window._cancel_armed
        assert main_window.cancel_confirm_label.isVisible()

    def test_second_press_stops_the_thread(self, main_window):
        main_window._on_cancel_clicked()  # arm
        with patch.object(main_window, "_cancel_transcription") as cancel:
            main_window._on_cancel_clicked()  # confirm
        cancel.assert_called_once()
        assert not main_window._cancel_armed
        assert not main_window.cancel_confirm_label.isVisible()

    def test_arming_reverts_after_its_timeout(self, main_window):
        main_window._on_cancel_clicked()  # arm
        assert main_window._cancel_armed

        # Simulate the arm timer expiring rather than waiting on a real
        # QTimer in a test - _disarm_cancel is exactly what its timeout is
        # connected to (see MainWindow.__init__).
        main_window._disarm_cancel()

        assert not main_window._cancel_armed
        assert not main_window.cancel_confirm_label.isVisible()
        with patch.object(main_window, "_cancel_transcription") as cancel:
            main_window._on_cancel_clicked()
        cancel.assert_not_called()  # reverted, so this press only re-arms

    def test_escape_on_step_3_drives_the_same_two_press_flow(self, main_window):
        with patch.object(main_window, "_cancel_transcription") as cancel:
            main_window._on_escape_shortcut()  # arm
            cancel.assert_not_called()
            main_window._on_escape_shortcut()  # confirm
        cancel.assert_called_once()

    def test_navigating_away_disarms_cancel(self, main_window):
        main_window._on_cancel_clicked()  # arm
        assert main_window._cancel_armed

        main_window._return_to_model_select()

        assert not main_window._cancel_armed
        assert not main_window.cancel_confirm_label.isVisible()
