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
from PyQt5.QtCore import Qt, QThread, pyqtSignal  # noqa: E402

# No local `qapp` fixture here on purpose: these tests take pytest-qt's
# session-scoped one. A local definition shadows it, and a module-scoped
# QApplication fixture in this suite once broke unrelated tests outright.
# Read "The shared QApplication" in docs/TESTING.md before adding one back.


@pytest.fixture
def hardware_stub():
    """Just enough of HardwareDetector's interface for FileSelectStep.__init__."""
    hw = MagicMock()
    hw.get_hardware_info.return_value = {
        "cpu_cores": 4,
        "ram_gb": 8,
        "has_gpu": False,
        "gpu_name": "",
    }
    return hw


@pytest.fixture
def file_select_step(qtbot, hardware_stub):
    from speech_to_text.gui.steps.file_select import FileSelectStep

    step = FileSelectStep(hardware_stub)
    qtbot.addWidget(step)
    return step


class TestGUI:
    @pytest.mark.skipif(True, reason="PyQt5 GUI testing requires X11 or mocking display")
    def test_main_window_creation(self):
        """Test main window creation."""
        pass

    @patch("speech_to_text.gui.main_window.QMainWindow")
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


class TestFileSelectStepSummaryPlurals:
    """
    One selected file should read "1 file selected", not "1 files selected".

    Worth pinning rather than leaving to review: a single dropped file is an
    ordinary case, and Hebrew inflects the verb and the noun together for it
    (נבחר קובץ אחד against נבחרו N קבצים), so the singular is a different
    string in both languages rather than a formatting detail one of them can
    get away with.
    """

    def test_one_file_reads_singular_in_both_languages(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui import i18n

        monkeypatch.setattr(
            "speech_to_text.gui.steps.file_select.get_audio_duration", lambda _p: 65
        )
        one = tmp_path / "clip.wav"
        one.write_bytes(b"x")
        try:
            for lang, forbidden in (("en", "1 files"), ("he", "1 קבצים")):
                i18n.set_language(lang)
                file_select_step.reset()
                file_select_step._add_files([str(one)])
                text = file_select_step.summary_label.text()
                assert forbidden not in text, (
                    f"{lang}: plural form used for a single file: {text!r}"
                )
        finally:
            i18n.set_language("en")

    def test_several_files_still_read_plural(self, file_select_step, tmp_path, monkeypatch):
        from speech_to_text.gui import i18n

        monkeypatch.setattr(
            "speech_to_text.gui.steps.file_select.get_audio_duration", lambda _p: 65
        )
        paths = []
        for i in range(3):
            p = tmp_path / f"clip_{i}.wav"
            p.write_bytes(b"x")
            paths.append(str(p))
        i18n.set_language("en")
        file_select_step.reset()
        file_select_step._add_files(paths)
        assert "3 files" in file_select_step.summary_label.text()


class TestFileSelectStepDirectDropFiltering:
    """
    A file dropped directly (not via a folder) used to be added whatever it
    was - config.SUPPORTED_FORMATS was only ever consulted for a dropped
    FOLDER's contents (_expand_directory), so a .txt dropped straight onto
    the zone got a green check and sat in the list until the worker choked
    on it much later. _drop now filters a direct drop through the same
    list, and says what it skipped instead of the file just vanishing.
    """

    def test_unsupported_direct_drop_is_skipped_supported_one_is_kept(
        self, file_select_step, tmp_path, monkeypatch
    ):
        from speech_to_text.gui.steps import file_select as file_select_module

        monkeypatch.setattr(file_select_module, "get_audio_duration", lambda path: 30)

        mp3 = tmp_path / "meeting.mp3"
        txt = tmp_path / "notes.txt"
        mp3.write_bytes(b"")
        txt.write_bytes(b"")

        received = []
        file_select_step.files_selected.connect(lambda paths, total: received.append(paths))
        from PyQt5.QtCore import QMimeData, QPoint, QUrl
        from PyQt5.QtGui import QDropEvent

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(mp3)), QUrl.fromLocalFile(str(txt))])
        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        file_select_step._drop(drop)

        # QUrl.fromLocalFile()/toLocalFile() can normalize separators
        # differently from str(Path) on Windows - compare basenames, like
        # TestDropZoneEventPath's real-drop test does, rather than exact
        # path strings.
        assert len(file_select_step.selected_files) == 1
        assert file_select_step.selected_files[0].endswith("meeting.mp3")
        assert received and len(received[-1]) == 1 and received[-1][0].endswith("meeting.mp3")
        summary = file_select_step.summary_label.text()
        assert "1" in summary  # 1 skipped
        assert "notes.txt" not in summary  # count only, no filenames (width is tight)

    def test_a_drop_that_skips_everything_still_updates_the_summary(
        self, file_select_step, tmp_path
    ):
        """
        No supported file at all means _add_files never runs (paths is
        empty), but the skip note still has to reach the summary line -
        otherwise a drop consisting entirely of unsupported files is once
        again a silent no-op.
        """
        from PyQt5.QtCore import QMimeData, QPoint, QUrl
        from PyQt5.QtGui import QDropEvent

        txt = tmp_path / "notes.txt"
        txt.write_bytes(b"")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(txt))])
        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        file_select_step._drop(drop)

        assert file_select_step.selected_files == []
        assert "1" in file_select_step.summary_label.text()

    def test_is_supported_file_uses_config_supported_formats(self, file_select_step):
        """
        config.SUPPORTED_FORMATS holds glob patterns ("*.mp3"), not bare
        extensions - pinning both a match and a non-match guards against a
        future rewrite that assumes the bare-extension shape instead.
        """
        assert file_select_step._is_supported_file("C:/audio/meeting.MP3")
        assert not file_select_step._is_supported_file("C:/docs/notes.txt")


class TestTranscriptionStepOpenButton:
    """
    The output is an editable HTML application now, not a text file, so the
    run ends with a way into it rather than just a path to go hunting for.
    """

    @pytest.fixture
    def step(self, qtbot):
        from speech_to_text.gui.steps.transcription import TranscriptionStep

        s = TranscriptionStep()
        qtbot.addWidget(s)
        return s

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
        with patch(
            "speech_to_text.gui.steps.transcription.webbrowser.open",
            side_effect=OSError("no browser"),
        ):
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
    def step(self, qtbot):
        from speech_to_text.gui.steps.transcription import TranscriptionStep

        s = TranscriptionStep()
        qtbot.addWidget(s)
        return s

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
        with patch(
            "speech_to_text.gui.steps.transcription.QDesktopServices.openUrl",
            side_effect=OSError("no shell"),
        ):
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


class TestTranscriptionStepResultPathElision:
    """
    result_path used to be one QLabel holding "Saved to:\\n<path>" with
    setWordWrap(True), which makes a label's height a function of its
    width (Qt's heightForWidth). Under this layout's Qt.AlignCenter, a
    width-dependent child can get compressed below the height its own
    content needs even when the step has room to spare - measured
    concretely at 900x1000 (hundreds of spare pixels top and bottom):
    minimumSizeHint reported 50px, the label was only allocated 37px, and
    the glyph bottoms of the path line were sliced off. This is the same
    AlignCenter-plus-width-dependent-child trap the layout-spacing comment
    in __init__ already documents for the case that made it overflow
    outright; here it clipped without ever overflowing the step at all.

    The fix (see _render_result_path) splits the caption and the path into
    two plain, unwrapped, single-line labels and middle-elides the path in
    code to fit the panel's actual width, so the label's height depends
    only on the font's line height - never on width - and the full path
    still reaches the user via the tooltip and accessible description.
    These tests pin the height side of that (the label must never be
    allocated less than its own minimumSizeHint - if the old wrapped
    two-line label ever came back, this fails the same way it failed for
    real) and the elision/full-text side.
    """

    @pytest.fixture
    def step(self, qtbot):
        from speech_to_text.gui.steps.transcription import TranscriptionStep

        s = TranscriptionStep()
        qtbot.addWidget(s)
        # show() matters here, not just resize(): an un-shown top-level
        # widget's resize() sets its own geometry but Qt doesn't cascade a
        # real QResizeEvent down to children without a window handle, so
        # the elision-follows-width test below would see a stale width
        # with only resize(). Every other TranscriptionStep fixture in this
        # file skips show() because nothing else here depends on real
        # child-geometry propagation.
        s.show()
        s.resize(900, 1000)
        return s

    def test_allocated_height_matches_minimum_size_hint(self, qapp, step):
        from PyQt5.QtGui import QFontMetrics

        step.set_file_info("meeting.m4a", "tiny")
        step.show_result(r"C:\Users\yuval\Desktop\meeting_transcription.html")
        qapp.processEvents()

        rp = step.result_path
        # A layout is never supposed to allocate a widget less than its own
        # minimumSizeHint - this is the invariant the old wrapped label
        # violated in the wild (50px needed, 37px given at 900x1000 inside
        # a real MainWindow). It doesn't reliably reproduce as a pixel gap
        # here (Qt's offscreen test platform resolves font metrics
        # differently from a real screen - see config.py's
        # GUI_WINDOW_MIN_HEIGHT comment for the same platform quirk showing
        # up elsewhere in this suite), so the two checks below pin the
        # actual mechanism instead of a pixel count that would only hold on
        # one platform:
        #
        # 1. hasHeightForWidth() must be False. This is Qt's own flag for
        #    "this widget's height depends on the width it's given" - True
        #    on the old wrapped, multi-line label (setWordWrap(True) plus
        #    an embedded "\n" both set it), False here because
        #    _render_result_path keeps the label single-line. If a wrapped
        #    label ever comes back, this fails immediately, on any
        #    platform, without needing a specific window size to trigger
        #    the clip.
        assert not rp.hasHeightForWidth()
        # 2. With no width dependency, the label's allocated height has to
        #    track a single line of its own font - not a second wrapped
        #    line's worth taller, and never compressed below it. A few
        #    pixels of frame/margin slack is fine; a whole extra text line
        #    (the old bug's failure mode) is not.
        single_line = QFontMetrics(rp.font()).height()
        assert single_line <= rp.height() <= single_line + 4
        assert rp.height() >= rp.minimumSizeHint().height()

    def test_the_displayed_line_is_elided_but_the_full_path_is_recoverable(self, qapp, step):
        long_path = r"C:\Users\yuval\Desktop\a very long meeting name that will not fit on one line without eliding.html"
        step.set_file_info("meeting.m4a", "tiny")
        step.show_result(long_path)
        qapp.processEvents()

        rp = step.result_path
        # Elided, not wrapped - a second line would mean heightForWidth is
        # back in play.
        assert "\n" not in rp.text()
        assert rp.text() != long_path
        assert rp.text().endswith(".html")
        # The truncation costs nothing precisely because the full path is
        # still reachable here.
        assert long_path in rp.toolTip()
        assert long_path in rp.accessibleDescription()

    def test_reflows_when_the_panel_is_resized_narrower(self, qapp, step):
        """The elision has to track the panel's actual width, not just the width at show_result time."""
        long_path = r"C:\Users\yuval\Desktop\a very long meeting name that will not fit on one line without eliding.html"
        step.set_file_info("meeting.m4a", "tiny")
        step.show_result(long_path)
        qapp.processEvents()
        wide_text = step.result_path.text()

        # Below roughly 750px this bare, parentless step hits its own
        # layout's minimum width (the two result buttons side by side) and
        # stops shrinking further - not a bound that exists in the real
        # app, where MainWindow's own minimum is what stops the shrink
        # (see config.GUI_WINDOW_MIN_WIDTH), just a detail of testing this
        # step standalone. 700 stays comfortably inside the range where it
        # actually does shrink.
        step.resize(700, 1000)
        qapp.processEvents()
        narrow_text = step.result_path.text()

        assert len(narrow_text) < len(wide_text)
        assert step.result_path.height() >= step.result_path.minimumSizeHint().height()


class TestTranscriptionStepBatchStrip:
    """
    Which file is running, in a ten-file batch, used to be legible only by
    catching the status line at the right instant. set_batch_files +
    update_progress's w_file_progress handling (see transcription.py) make
    it a persistent, always-visible strip instead.
    """

    @pytest.fixture
    def step(self, qtbot):
        from speech_to_text.gui.steps.transcription import TranscriptionStep

        s = TranscriptionStep()
        qtbot.addWidget(s)
        return s

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
        assert COLORS["accent"] in styles[2]
        assert COLORS["success"] in styles[0]
        assert COLORS["success"] in styles[1]
        assert COLORS["accent"] not in styles[0]
        assert COLORS["accent"] not in styles[3]

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
        file_select_step.files_selected.connect(lambda paths, seconds: received.append(paths))

        enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        qapp.sendEvent(file_select_step.drop_zone, enter)
        assert enter.isAccepted(), (
            "the drop zone refused a drag carrying file URLs - _drag_enter is "
            "not reaching the zone, so nothing can ever be dropped on it"
        )

        drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
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
        enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
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
        with patch("speech_to_text.gui.steps.file_select.QFileDialog.getOpenFileNames") as dialog:
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
            qapp.sendEvent(
                tracker,
                QMouseEvent(
                    QEvent.MouseButtonPress,
                    QPoint(0, 0),
                    Qt.LeftButton,
                    Qt.LeftButton,
                    Qt.NoModifier,
                ),
            )
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
                QEvent.MouseButtonPress,
                btn.rect().center(),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            qapp.sendEvent(btn, click)
            btn.setFocus()
            qapp.processEvents()
            assert not btn.property(PROPERTY)
        finally:
            btn.setParent(None)
            btn.deleteLater()
            tracker.deleteLater()

    def test_the_tracker_stops_stamping_once_the_application_is_quitting(self, qapp):
        """
        The tracker must let go of focusChanged before QApplication starts
        destroying widgets.

        QApplication keeps emitting focusChanged while it tears its widget
        tree down at the end of a run, handing over an "old" widget that is
        already on its way out - and _on_focus_changed answers that by
        calling unpolish()/polish() on it, i.e. by reaching into a
        half-destroyed C++ object. That took the process down with an access
        violation after exec_() had already returned: a crash on exit with no
        Python frame anywhere in it. Measured at 7 of 8 runs on the real
        windowing system, 2 of 6 offscreen, which is why this pins the
        mechanism (the tracker detaches on aboutToQuit) rather than trying to
        catch an intermittent segfault in a subprocess.
        """
        from PyQt5.QtWidgets import QPushButton

        from speech_to_text.gui.focus import PROPERTY, KeyboardFocusTracker

        tracker = KeyboardFocusTracker(qapp)
        btn = QPushButton()
        btn.show()
        try:
            tracker._keyboard_active = True
            qapp.aboutToQuit.emit()

            # focusChanged still fires during teardown; the tracker must no
            # longer be listening to it.
            btn.setFocus()
            qapp.processEvents()
            assert not btn.property(PROPERTY), "tracker was still stamping focus after aboutToQuit"

            # Idempotent: aboutToQuit can reach it more than once (and
            # nothing should raise on the second pass).
            tracker._detach()
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
    def main_window(self, qtbot, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module

        hw = MagicMock()
        # Not None - MainWindow only starts CalibrationThread's background
        # subprocess when this is unset.
        hw.tiny_seconds_per_audio_second = 1.0
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4,
            "ram_gb": 8,
            "has_gpu": False,
            "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)

        window = main_window_module.MainWindow()
        qtbot.addWidget(window)
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
    def main_window(self, qtbot, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module

        hw = MagicMock()
        # Not None - MainWindow only starts CalibrationThread's background
        # subprocess when this is unset.
        hw.tiny_seconds_per_audio_second = 1.0
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4,
            "ram_gb": 8,
            "has_gpu": False,
            "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)

        window = main_window_module.MainWindow()
        qtbot.addWidget(window)
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
        with (
            patch.object(main_window, "_go_next") as go_next,
            patch.object(main_window, "_reset") as reset,
        ):
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
        with (
            patch.object(main_window, "_go_next") as go_next,
            patch.object(main_window, "_reset") as reset,
        ):
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
    def main_window(self, qtbot, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module
        from speech_to_text.gui.steps import Step

        hw = MagicMock()
        hw.tiny_seconds_per_audio_second = 1.0
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4,
            "ram_gb": 8,
            "has_gpu": False,
            "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)

        window = main_window_module.MainWindow()
        qtbot.addWidget(window)
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


class TestMainWindowResizing:
    """
    Step 9: the window used to be setFixedSize'd at 650x600 with the
    maximize hint stripped, which hid a genuine shortfall rather than
    avoiding it - see config.py's GUI_WINDOW_MIN_HEIGHT comment for the
    628px measurement behind these numbers (chrome of 153px plus the
    transcription step's own 475px minimum once show_result() has
    populated the completion panel). These pin that the window is now
    genuinely resizable, that its floor is honest (at or above that
    measured content floor rather than the old, never-enforced 550), and
    that the transcription step's completion panel - the single tightest
    state of any step - actually fits once the window is dragged down to
    that floor. The last of these is the regression test for the bug this
    step fixes.
    """

    @pytest.fixture
    def main_window(self, qtbot, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module

        hw = MagicMock()
        # Not None - MainWindow only starts CalibrationThread's background
        # subprocess when this is unset.
        hw.tiny_seconds_per_audio_second = 1.0
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4,
            "ram_gb": 8,
            "has_gpu": False,
            "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)

        window = main_window_module.MainWindow()
        qtbot.addWidget(window)
        window.show()
        yield window
        window.close()

    def test_window_is_resizable_with_maximize_available(self, main_window):
        # setFixedSize() clamps maximumSize() down to minimumSize(); a
        # genuinely resizable window's maximum stays far above its minimum
        # (Qt's default is effectively unbounded), and the maximize button
        # - deliberately stripped from the old fixed-size window since
        # maximizing a window that can't resize would do nothing - is back.
        assert main_window.maximumHeight() > main_window.minimumHeight() + 1000
        assert main_window.maximumWidth() > main_window.minimumWidth() + 1000
        assert bool(main_window.windowFlags() & Qt.WindowMaximizeButtonHint)

    def test_minimum_size_is_at_least_the_measured_content_floor(self, main_window):
        from speech_to_text import config

        # 628px is the measured floor (153px chrome + the transcription
        # step's worst-case 475px minimumSizeHint once show_result() has
        # run) - see config.py's GUI_WINDOW_MIN_HEIGHT comment. The old
        # 550 constant sat below this and was simply never enforced, since
        # the window was fixed-size and nothing ever read it.
        assert config.GUI_WINDOW_MIN_HEIGHT >= 628
        assert main_window.minimumHeight() == config.GUI_WINDOW_MIN_HEIGHT
        assert main_window.minimumWidth() == config.GUI_WINDOW_MIN_WIDTH

    def test_transcription_step_does_not_overflow_at_minimum_height_once_show_result_has_run(
        self, main_window, qapp
    ):
        from speech_to_text import config

        main_window.resize(config.GUI_WINDOW_MIN_WIDTH, config.GUI_WINDOW_MIN_HEIGHT)
        ts = main_window.transcription_step
        ts.set_file_info("meeting.m4a", "tiny")
        ts.show_result(r"C:\Users\yuval\Desktop\meeting_transcription.html")
        main_window.stacked_widget.setCurrentWidget(ts)
        qapp.processEvents()

        # Chrome measured the same way config.py's own comment measured it
        # (header + step indicator + nav bar - NOT the stacked widget's
        # content area, which is what varies per step) via public widgets
        # rather than layout-item indices, so this stays correct if the
        # layout is ever restructured. header and nav_widget aren't kept
        # as self attributes, but title_label and next_btn each live
        # inside one, which is a stable enough anchor for a test.
        header = main_window.title_label.parentWidget()
        nav_bar = main_window.next_btn.parentWidget()
        chrome = header.height() + main_window.step_indicator.height() + nav_bar.height()

        # This is the regression this step fixes: the old GUI_WINDOW_MIN_HEIGHT
        # (550) was never actually enforced (the window was setFixedSize'd to
        # 600, so nothing ever resized down to 550 in the first place) and was
        # wrong regardless - chrome plus the transcription step's own
        # minimumSizeHint once show_result() has populated the completion
        # panel exceeds it. Asserting against the config constant itself
        # (rather than the window's current allocated height) is what makes
        # this fail against the old value: the old fixed-size window's
        # accidental 600px default happened to be tall enough under this
        # test environment's own font metrics to mask the undersized
        # constant, which is exactly how the bug shipped unnoticed. Real
        # font metrics (see config.py's GUI_WINDOW_MIN_HEIGHT comment) need
        # more room still (628px), so the margin asserted here is a lower
        # bound on the real one, not a substitute for it.
        assert config.GUI_WINDOW_MIN_HEIGHT >= chrome + ts.minimumSizeHint().height()


class TestModelDownloadSize:
    """
    config.MODELS.download_size is a structured, per-model download-size
    figure (see that dict's own module docstring for why it exists at all:
    there is no live download-progress signal anywhere in this app, so the
    GUI's only honest option is to say the cost up front, before the model
    is picked). A model added to that table later without this field should
    fail a test, not silently render a blank or "None" note on its card.
    """

    def test_every_model_declares_a_download_size(self):
        from speech_to_text import config

        missing = [name for name, info in config.MODELS.items() if "download_size" not in info]
        assert not missing, f"config.MODELS entries missing download_size: {missing}"

    def test_download_size_is_non_empty_text(self):
        """Guards against a present-but-blank value slipping through the check above."""
        from speech_to_text import config

        for name, info in config.MODELS.items():
            assert isinstance(info["download_size"], str) and info["download_size"].strip(), (
                f"{name}'s download_size is empty or not a string: {info.get('download_size')!r}"
            )


class TestModelDownloadRootSharedWithCore:
    """
    gui/steps/model_select.py used to hand-mirror core/transcriber.py's
    download_root literal ("./whisper_models") in its own module-level
    _WHISPER_DOWNLOAD_ROOT, with a comment admitting there was no shared
    constant to import instead. That made the "not yet downloaded" note a
    model card shows an independent guess that could silently drift from
    what the real downloader does. Both sides now read
    config.MODEL_DOWNLOAD_ROOT - these pin that there is exactly one
    definition left, not two kept in sync by hand.
    """

    def test_model_select_has_no_hand_mirrored_literal(self):
        from speech_to_text.gui.steps import model_select as model_select_module

        assert not hasattr(model_select_module, "_WHISPER_DOWNLOAD_ROOT")

    def test_model_is_downloaded_reads_config_download_root(self, monkeypatch, tmp_path):
        """
        _model_is_downloaded() must look under whatever config.MODEL_DOWNLOAD_ROOT
        currently resolves to - proof the presence check and the downloader
        share one root rather than two literals that can drift apart.
        """
        from speech_to_text import config
        from speech_to_text.gui.steps import model_select as model_select_module

        fake_root = tmp_path / "wherever_config_points"
        cache_dir = fake_root / "models--Systran--faster-whisper-tiny" / "snapshots" / "abc123"
        cache_dir.mkdir(parents=True)
        (cache_dir / "model.bin").write_bytes(b"stub")

        monkeypatch.setattr(config, "MODEL_DOWNLOAD_ROOT", str(fake_root))

        assert model_select_module._model_is_downloaded("tiny") is True
        assert model_select_module._model_is_downloaded("medium") is False


@pytest.fixture
def model_hardware_stub():
    """
    Just enough of HardwareDetector's interface for ModelSelectStep.__init__
    plus the calls _desc_text/update_audio_duration make on it.
    """
    hw = MagicMock()
    hw.tiny_seconds_per_audio_second = None  # calibration not yet run - see the tests below
    hw.recommend_model.return_value = ("tiny", "stub")
    hw.estimate_transcription_time.return_value = (60, "stub")
    hw.get_time_estimate_display.return_value = "~1 min"
    return hw


class TestModelSelectStepCardWidth:
    """
    The model cards must never be wider than what the scroll area actually
    shows, or their right border is clipped and each card reads as a box
    left open on one side.

    setWidgetResizable(True) re-fits the scrolled widget from QScrollArea's
    own resizeEvent - which fires when the scroll area changes size, not
    when the viewport alone narrows because the vertical scrollbar has just
    appeared. Content growing (the common trigger: MainWindow's
    _on_calibration_done rewrites every estimate once the benchmark lands)
    brings the bar in without any resize reaching the scroll area, so the
    container keeps its old, now-too-wide width. Qt's own updateScrollBars()
    also re-widens the widget to the full scroll area during its first pass
    before deciding a bar is needed, which is why the fix is a maximum
    width - a constraint Qt honours inside that pass - rather than a
    resize() that the next layout undoes.
    """

    def test_container_is_clamped_to_the_viewport_on_a_viewport_resize(
        self, qapp, model_hardware_stub
    ):
        from PyQt5.QtGui import QResizeEvent
        from PyQt5.QtWidgets import QWIDGETSIZE_MAX

        from speech_to_text.gui.steps.model_select import ModelSelectStep

        step = ModelSelectStep(model_hardware_stub)
        step.resize(600, 320)
        step.show()
        qapp.processEvents()
        try:
            scroll = step._scroll_area
            viewport = scroll.viewport()
            container = scroll.widget()

            # Stand in for the state Qt leaves behind: the container is
            # wider than the strip of it that is actually visible. The
            # ceiling has to be lifted first - showing the step already
            # applied one, which is the fix under test doing its job.
            container.setMaximumWidth(QWIDGETSIZE_MAX)
            container.resize(viewport.width() + 40, container.height())
            assert container.width() > viewport.width()

            qapp.sendEvent(viewport, QResizeEvent(viewport.size(), viewport.size()))

            assert container.maximumWidth() == viewport.width()
            assert container.width() <= viewport.width()
            for name, card in step._cards.items():
                assert card.width() <= viewport.width(), (
                    f"card {name!r} is {card.width()}px inside a "
                    f"{viewport.width()}px viewport - its right border is clipped"
                )
        finally:
            step.hide()
            step.deleteLater()


class TestModelSelectStepEstimateLanguage:
    """
    A model card's time estimate has to be rendered in the language the UI
    is in right now, not the one it was in when the estimate was computed.

    The estimate used to be cached as a finished string from
    hardware_detection's English-only formatter, so a Hebrew reader saw
    "1 דק' 35 שנ'" for a file's length on step 1 and "משוער: 1m 46s" for the
    estimate on step 2 - two notations for the same unit, two screens apart.
    retranslate() deliberately re-renders text WITHOUT recomputing estimates
    (recomputing would re-run and re-log the hardware estimator on a mere
    language toggle), so the cache has to hold seconds and the units have to
    come from the string table at render time.
    """

    def test_toggling_the_language_re_renders_the_estimate(self, qapp, model_hardware_stub):
        from speech_to_text.gui import i18n
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        original = i18n.get_language()
        try:
            i18n.set_language("en", save=False)
            step = ModelSelectStep(model_hardware_stub)
            english = step._desc_labels["tiny"].text()

            i18n.set_language("he", save=False)
            step.retranslate()
            hebrew = step._desc_labels["tiny"].text()

            # The stub estimates 60s, which elides to a bare minute.
            assert "1m" in english, english
            assert "דק'" in hebrew, hebrew
            assert "1m" not in hebrew, hebrew
        finally:
            i18n.set_language(original, save=False)


class TestModelSelectStepCalibrationNote:
    """
    Every time estimate on this step is a placeholder (config.SPEED_FACTORS'
    guessed constants) until the background hardware benchmark
    (CalibrationThread, started in MainWindow.__init__) finishes - and
    nothing said so before this. These pin the three states the note can be
    in: shown while unmeasured, hidden once a real measurement lands, and a
    different, permanent message if the benchmark fails outright instead of
    just taking a while.
    """

    def test_note_is_shown_while_calibration_is_unmeasured(self, qapp, model_hardware_stub):
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        step = ModelSelectStep(model_hardware_stub)

        assert not step.calibration_note.isHidden()
        assert step.calibration_note.text()  # not just visible, actually says something

    def test_note_is_cleared_once_calibration_lands(self, qapp, model_hardware_stub):
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        step = ModelSelectStep(model_hardware_stub)
        assert not step.calibration_note.isHidden()

        # Simulate MainWindow._on_calibration_done: the hardware object now
        # knows a real value, then update_audio_duration is called (exactly
        # as MainWindow does after a successful calibration).
        model_hardware_stub.tiny_seconds_per_audio_second = 0.5
        step.update_audio_duration(120)

        assert step.calibration_note.isHidden()

    def test_update_audio_duration_does_not_clear_the_note_while_still_unmeasured(
        self, qapp, model_hardware_stub
    ):
        """
        update_audio_duration also runs on every step-1-to-2 advance
        regardless of calibration state (see MainWindow._go_next) - it must
        not blindly hide an accurate "still measuring" note just because the
        user picked a file before the benchmark finished.
        """
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        step = ModelSelectStep(model_hardware_stub)
        step.update_audio_duration(120)

        assert not step.calibration_note.isHidden()

    def test_failed_calibration_shows_a_different_permanent_note(self, qapp, model_hardware_stub):
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        step = ModelSelectStep(model_hardware_stub)
        pending_text = step.calibration_note.text()

        step.mark_calibration_unmeasured()

        assert not step.calibration_note.isHidden()
        assert step.calibration_note.text() != pending_text
        assert step._calibration_note_key == "calibration_unmeasured"

    def test_note_hidden_from_the_start_once_calibration_is_already_known(
        self, qapp, model_hardware_stub
    ):
        """The common case: calibration usually finishes before step 2 is ever built."""
        from speech_to_text.gui.steps.model_select import ModelSelectStep

        model_hardware_stub.tiny_seconds_per_audio_second = 0.5
        step = ModelSelectStep(model_hardware_stub)

        assert step.calibration_note.isHidden()


class _FakeCalibrationThread(QThread):
    """Stand-in for CalibrationThread that never spawns anything.

    The real thread starts a subprocess that loads a Whisper model and
    benchmarks it, which takes seconds - far too much for a unit test. What
    the teardown tests below actually need is only the parts MainWindow
    touches: the two signals it connects to, a start() that does not run a
    thread, and a record of whether stop() was ever called.
    """

    calibrated = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, cpu_cores: int):
        super().__init__()
        self.cpu_cores = cpu_cores
        self.start_called = False
        self.stop_called = False

    def start(self, *args, **kwargs):  # type: ignore[override]
        self.start_called = True

    def stop(self):
        self.stop_called = True

    def wait(self, *args, **kwargs):  # type: ignore[override]
        return True

    def run(self):  # pragma: no cover - never actually started
        pass


class TestCalibrationThreadTeardown:
    """
    MainWindow starts CalibrationThread in __init__ and wires `calibrated`
    to a slot that writes to live widgets (_on_calibration_done calls
    model_step.update_audio_duration). Nothing used to stop or unwire that
    thread when the window closed, so a benchmark still running at close
    time could deliver its result into slots whose widgets Qt is already
    tearing down.

    That is the same shape as the focusChanged problem gui/focus.py had to
    solve: a signal source outliving the widgets its slot reaches into,
    which surfaces as a native access violation with no Python frame rather
    than as an exception you can catch. These tests pin the two halves of
    the guard - the thread is stopped, and its signals can no longer reach
    a slot.
    """

    @pytest.fixture
    def uncalibrated_window(self, qtbot, monkeypatch):
        from speech_to_text.gui import main_window as main_window_module

        hw = MagicMock()
        # None is what makes MainWindow start a calibration thread at all -
        # a cached calibration (the common case on a developer machine)
        # skips it entirely, which is exactly why this gap is easy to miss.
        hw.tiny_seconds_per_audio_second = None
        hw.cpu_count = 4
        hw.get_hardware_info.return_value = {
            "cpu_cores": 4,
            "ram_gb": 8,
            "has_gpu": False,
            "gpu_name": "",
        }
        hw.recommend_model.return_value = ("tiny", "stub")
        hw.estimate_transcription_time.return_value = (60, "stub")
        hw.get_time_estimate_display.return_value = "~1 min"
        hw.get_device_recommendation.return_value = ("cpu", "stub")
        monkeypatch.setattr(main_window_module, "HardwareDetector", lambda: hw)
        monkeypatch.setattr(main_window_module, "CalibrationThread", _FakeCalibrationThread)

        window = main_window_module.MainWindow()
        qtbot.addWidget(window)
        window.show()
        yield window
        window.close()

    def test_an_uncalibrated_window_really_does_start_a_calibration_thread(
        self, uncalibrated_window
    ):
        """Guards the fixture itself: if MainWindow ever stopped starting the
        thread here, the two teardown tests below would pass vacuously."""
        assert isinstance(uncalibrated_window.calibration_thread, _FakeCalibrationThread)
        assert uncalibrated_window.calibration_thread.start_called

    def test_closing_the_window_stops_a_still_running_calibration_thread(self, uncalibrated_window):
        thread = uncalibrated_window.calibration_thread
        uncalibrated_window.close()
        assert thread.stop_called

    def test_a_calibration_result_arriving_after_close_never_reaches_the_widgets(
        self, uncalibrated_window
    ):
        """The failure this change exists to prevent: `calibrated` fires late
        and _on_calibration_done writes into a widget tree that is on its way
        out. Stopping the thread is not enough on its own - a result can
        already be in flight - so the signals have to be disconnected too."""
        thread = uncalibrated_window.calibration_thread
        uncalibrated_window.model_step.update_audio_duration = MagicMock()
        uncalibrated_window.model_step.mark_calibration_unmeasured = MagicMock()

        uncalibrated_window.close()
        thread.calibrated.emit(0.5)
        thread.failed.emit("too late")

        uncalibrated_window.model_step.update_audio_duration.assert_not_called()
        uncalibrated_window.model_step.mark_calibration_unmeasured.assert_not_called()


class TestMakeLabelFactory:
    """make_label exists purely to collapse the construct/setFont/
    setStyleSheet/setAlignment boilerplate, so what it must guarantee is
    that it produces exactly what the hand-written four lines produced -
    including leaving properties untouched when an argument is omitted."""

    def test_a_label_built_with_every_argument_matches_the_hand_written_four_liner(self, qapp):
        from PyQt5.QtWidgets import QLabel

        from speech_to_text.gui import theme
        from speech_to_text.gui.theme import Fonts
        from speech_to_text.gui.widgets import make_label

        expected = QLabel("hello")
        expected.setFont(Fonts.BODY_BOLD)
        expected.setStyleSheet(theme.text_qss("text_primary"))
        expected.setAlignment(Qt.AlignCenter)

        built = make_label(
            "hello", font=Fonts.BODY_BOLD, color="text_primary", align=Qt.AlignCenter
        )

        assert built.text() == expected.text()
        assert built.font() == expected.font()
        assert built.styleSheet() == expected.styleSheet()
        assert built.alignment() == expected.alignment()

    def test_omitted_arguments_leave_the_label_at_the_qt_defaults(self, qapp):
        from PyQt5.QtWidgets import QLabel

        from speech_to_text.gui.widgets import make_label

        plain = QLabel()
        built = make_label()

        assert built.text() == ""
        assert built.styleSheet() == plain.styleSheet()
        assert built.alignment() == plain.alignment()
        assert built.font() == plain.font()

    def test_the_colour_argument_is_a_theme_key_routed_through_text_qss(self, qapp):
        """Colour keys must not become a second vocabulary: whatever
        theme.text_qss returns for a key is what the label gets, verbatim."""
        from speech_to_text.gui import theme
        from speech_to_text.gui.widgets import make_label

        for key in ("text_primary", "text_secondary", "text_tertiary", "error", "success"):
            assert make_label(color=key).styleSheet() == theme.text_qss(key)

    def test_a_parent_passed_to_the_factory_really_becomes_the_labels_parent(self, qapp):
        from PyQt5.QtWidgets import QWidget

        from speech_to_text.gui.widgets import make_label

        parent = QWidget()
        assert make_label("x", parent=parent).parent() is parent
