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
