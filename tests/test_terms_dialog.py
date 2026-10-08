"""
Tests for the custom terms dialog (gui/terms_dialog.py) and the button on the
model step that opens it.

Every test points the term list at a temp file through the same environment
override the app resolves (config.resolve_terms_path), so nothing here can
write the developer's real hebrew_terms.txt. qapp is pytest-qt's shared one -
see "The shared QApplication" in docs/TESTING.md.
"""

from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QPushButton


@pytest.fixture
def terms_file(tmp_path, monkeypatch):
    path = tmp_path / "hebrew_terms.txt"
    monkeypatch.setenv("SPEECH_TO_TEXT_TERMS_FILE", str(path))
    return path


@pytest.fixture
def english():
    from gui import i18n

    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def dialog(qapp, qtbot, terms_file, english):
    from gui.terms_dialog import TermsDialog

    dialog = TermsDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qapp.processEvents()
    return dialog


@pytest.fixture
def hardware_stub():
    """Just enough of HardwareDetector for ModelSelectStep.__init__."""
    hw = MagicMock()
    hw.tiny_seconds_per_audio_second = None
    hw.recommend_model.return_value = ("ivrit-turbo", "stub")
    hw.estimate_transcription_time.return_value = (60, "stub")
    return hw


def type_term(qtbot, dialog, term):
    """Put a Hebrew term in the field.

    setText, not qtbot.keyClicks: simulating Hebrew key presses kills the
    offscreen Qt platform outright on Windows (no traceback, the process just
    ends). These tests are about what the keyboard DOES - Enter, enabling Add
    - and still send real key events for that; only the text gets in another
    way.
    """
    dialog.field.setText(term)


def listed(dialog):
    rows = dialog.list_area.widget().findChildren(QFrame, "termRow")
    return [row.findChild(QLabel).text() for row in rows]


def add(dialog, term):
    dialog.field.setText(term)
    dialog.add_current()


class TestAdding:
    def test_enter_writes_the_term_and_lists_it(self, qtbot, dialog, terms_file):
        type_term(qtbot, dialog, "קיסריה")
        qtbot.keyClick(dialog.field, Qt.Key_Return)

        assert "קיסריה" in terms_file.read_text(encoding="utf-8").splitlines()
        assert listed(dialog) == ["קיסריה"]
        assert dialog.field.text() == ""

    def test_enter_never_closes_the_dialog(self, qtbot, dialog):
        """QDialog makes its buttons autoDefault; without opting out, Enter in
        the field also clicked Done - the misclick found in the mockup."""
        type_term(qtbot, dialog, "קיסריה")
        qtbot.keyClick(dialog.field, Qt.Key_Return)
        qtbot.keyClick(dialog.field, Qt.Key_Return)

        assert dialog.isVisible()

    def test_add_is_disabled_until_there_is_something_to_add(self, qtbot, dialog):
        assert not dialog.add_button.isEnabled()
        qtbot.keyClicks(dialog.field, "   ")
        assert not dialog.add_button.isEnabled()
        qtbot.keyClicks(dialog.field, "Naor")
        assert dialog.add_button.isEnabled()

    def test_newest_term_is_listed_first(self, dialog):
        add(dialog, "קיסריה")
        add(dialog, "בראודה")
        assert listed(dialog) == ["בראודה", "קיסריה"]

    def test_a_hand_written_comment_survives_an_add(self, qapp, qtbot, terms_file, english):
        from gui.terms_dialog import TermsDialog

        terms_file.write_text("# my people\nנאור\n", encoding="utf-8")
        dialog = TermsDialog()
        qtbot.addWidget(dialog)
        add(dialog, "יוסי")

        assert terms_file.read_text(encoding="utf-8").splitlines() == [
            "# my people",
            "נאור",
            "יוסי",
        ]


class TestRefusals:
    def test_a_duplicate_is_reported_inline_and_not_written_twice(self, dialog, terms_file):
        add(dialog, "קיסריה")
        add(dialog, "קיסריה")

        assert dialog.message.isVisibleTo(dialog)
        assert "קיסריה" in dialog.message.text()
        assert terms_file.read_text(encoding="utf-8").count("קיסריה") == 1
        # Kept and selected, so the next keystroke replaces it.
        assert dialog.field.selectedText() == "קיסריה"

    def test_a_comment_marker_is_refused_with_a_reason(self, dialog, terms_file):
        add(dialog, "#קיסריה")

        assert dialog.message.isVisibleTo(dialog)
        assert "#" in dialog.message.text()
        assert not terms_file.exists()

    def test_a_write_failure_is_shown_and_keeps_what_was_typed(
        self, dialog, terms_file, monkeypatch
    ):
        from core import term_store

        def locked(_src, _dst):
            raise PermissionError("the file is open in another program")

        monkeypatch.setattr(term_store.os, "replace", locked)
        add(dialog, "קיסריה")

        assert "another program" in dialog.message.text()
        assert dialog.field.text() == "קיסריה"
        assert listed(dialog) == []

    def test_a_successful_add_clears_an_earlier_message(self, dialog):
        add(dialog, "#x")
        add(dialog, "קיסריה")
        assert not dialog.message.isVisibleTo(dialog)


class TestRemoving:
    def test_remove_deletes_only_that_term(self, qapp, qtbot, terms_file, english):
        from gui.terms_dialog import TermsDialog

        terms_file.write_text("# mine\nקיסריה\nבראודה\n", encoding="utf-8")
        dialog = TermsDialog()
        qtbot.addWidget(dialog)
        dialog.show()

        button = next(
            b
            for b in dialog.list_area.widget().findChildren(QPushButton)
            if "קיסריה" in b.accessibleName()
        )
        qtbot.mouseClick(button, Qt.LeftButton)

        assert terms_file.read_text(encoding="utf-8").splitlines() == ["# mine", "בראודה"]
        assert listed(dialog) == ["בראודה"]

    def test_the_remove_button_is_an_icon_named_for_its_term(self, dialog):
        add(dialog, "קיסריה")
        button = dialog.list_area.widget().findChild(QPushButton)

        assert "קיסריה" in button.accessibleName()
        assert button.text() == ""
        assert not button.icon().isNull()


class TestLayout:
    def test_an_empty_list_says_so(self, dialog):
        texts = [label.text() for label in dialog.list_area.widget().findChildren(QLabel)]
        assert any("No terms yet" in text for text in texts)
        assert not dialog.count_label.isVisibleTo(dialog)

    def test_the_count_reads_naturally(self, dialog):
        add(dialog, "קיסריה")
        assert dialog.count_label.text() == "1 term"
        add(dialog, "בראודה")
        assert dialog.count_label.text() == "2 terms"

    def test_no_whats_this_button_in_the_title_bar(self, dialog):
        assert not dialog.windowFlags() & Qt.WindowContextHelpButtonHint

    def test_hebrew_ui_lays_the_dialog_out_right_to_left(self, qtbot, terms_file, english):
        from gui import i18n
        from gui.terms_dialog import TermsDialog

        i18n.set_language("he")
        dialog = TermsDialog()
        qtbot.addWidget(dialog)

        assert dialog.layoutDirection() == Qt.RightToLeft
        assert dialog.field.alignment() & Qt.AlignRight

    def test_hebrew_terms_sit_on_the_left_in_the_english_ui(self, dialog):
        """A plain AlignLeft is mirrored for a label whose text is Hebrew -
        found in the mockup; AlignAbsolute pins it."""
        add(dialog, "קיסריה")
        label = dialog.list_area.widget().findChild(QFrame, "termRow").findChild(QLabel)
        assert label.alignment() & Qt.AlignAbsolute
        assert label.alignment() & Qt.AlignLeft


class TestThePanelOnTheModelStep:
    @pytest.fixture
    def step(self, qapp, qtbot, hardware_stub, terms_file, english):
        from gui.steps.model_select import ModelSelectStep

        terms_file.write_text("# c\nקיסריה\nבראודה\n", encoding="utf-8")
        step = ModelSelectStep(hardware_stub)
        qtbot.addWidget(step)
        return step

    def test_the_panel_counts_the_terms_on_disk(self, step, terms_file):
        assert step.terms_count_label.text() == "2"
        assert step.term_chips._terms == ["קיסריה", "בראודה"]
        assert str(terms_file) in step.terms_button.toolTip()

    def test_chips_that_do_not_fit_become_a_more_label(self, qapp, step, terms_file):
        from core import term_store

        for term in ("ירושלים", "באר שבע", "יובל קוגן", "מכללת בראודה", "קריית שמונה"):
            term_store.add_term(str(terms_file), term)
        step._refresh_terms()
        chips = step.term_chips
        # A real panel's width. Offscreen Qt has no real fonts and inflates
        # text widths, so a narrower row can fit no chip at all.
        chips.resize(320, chips.sizeHint().height())
        chips._fit()

        shown = sum(1 for chip in chips._chips if not chip.isHidden())
        assert 0 < shown < 7
        assert chips._more.text() == f"+{7 - shown} more"

    def test_the_count_updates_after_the_dialog_closes(self, step, terms_file, monkeypatch):
        from core import term_store
        from gui.steps import model_select

        def exec_and_add(_dialog):
            term_store.add_term(str(terms_file), "נאור")
            return 1

        monkeypatch.setattr(model_select.TermsDialog, "exec_", exec_and_add)
        step.terms_button.click()

        assert step.terms_count_label.text() == "3"
        assert "נאור" in step.term_chips._terms

    def test_the_button_follows_a_live_language_switch(self, step):
        from gui import i18n

        i18n.set_language("he")
        step.retranslate()
        assert step.terms_title.text() == "מונחים מותאמים"
        assert step.terms_button.text() == "עריכה"

    def test_an_unreadable_list_still_renders_the_button(self, step, monkeypatch):
        from core import term_store

        def unreadable(_path):
            raise PermissionError("denied")

        monkeypatch.setattr(term_store, "read_terms", unreadable)
        step.retranslate()
        assert step.terms_count_label.text() == "0"
        assert step.term_chips._more.text() == "No terms yet."
