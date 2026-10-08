"""
Tests for editing the term list file.

The file has two editors - the app's terms dialog and a person in a text
editor - so most of these pin what the app must NOT do to a hand-edited file:
drop its comments, duplicate an entry, or leave it half-written.
"""

import os

import pytest

from core import term_store
from core.hebrew_corrections import TermList


def write(path, text):
    path.write_text(text, encoding="utf-8")


class TestReadTerms:
    def test_missing_file_is_an_empty_list(self, tmp_path):
        assert term_store.read_terms(str(tmp_path / "absent.txt")) == []

    def test_comments_and_blanks_are_not_terms(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "# header\n\nקיסריה\n   # indented comment\n  באר שבע  \n")
        assert term_store.read_terms(str(path)) == ["קיסריה", "באר שבע"]

    def test_a_notepad_byte_order_mark_does_not_stick_to_the_first_term(self, tmp_path):
        """Plain utf-8 decoding keeps the BOM, and "\\ufeffקיסריה" never matches."""
        path = tmp_path / "terms.txt"
        path.write_bytes("קיסריה\n".encode("utf-8-sig"))
        assert term_store.read_terms(str(path)) == ["קיסריה"]

    def test_windows_line_endings_are_read_cleanly(self, tmp_path):
        path = tmp_path / "terms.txt"
        path.write_bytes("קיסריה\r\nבראודה\r\n".encode())
        assert term_store.read_terms(str(path)) == ["קיסריה", "בראודה"]


class TestAddTerm:
    def test_first_add_creates_the_file_with_a_header_and_no_examples(self, tmp_path):
        path = tmp_path / "terms.txt"
        assert term_store.add_term(str(path), "קיסריה")

        text = path.read_text(encoding="utf-8")
        assert text.startswith("#")
        assert term_store.read_terms(str(path)) == ["קיסריה"]

    def test_creates_a_missing_parent_directory(self, tmp_path):
        """The per-user fallback location does not exist until the first add."""
        path = tmp_path / "speech-to-text" / "terms.txt"
        assert term_store.add_term(str(path), "קיסריה")
        assert path.exists()

    def test_appends_and_keeps_hand_written_comments(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "# my places\nקיסריה\n\n# my people\n")
        term_store.add_term(str(path), "בראודה")

        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines == ["# my places", "קיסריה", "", "# my people", "בראודה"]

    def test_input_is_stripped(self, tmp_path):
        path = tmp_path / "terms.txt"
        term_store.add_term(str(path), "  קיסריה \n")
        assert term_store.read_terms(str(path)) == ["קיסריה"]

    @pytest.mark.parametrize(
        "variant",
        ["קיסריה", "קֵיסָרְיָה", " קיסריה "],
        ids=["exact", "with-nikud", "padded"],
    )
    def test_an_equivalent_spelling_is_a_duplicate(self, tmp_path, variant):
        path = tmp_path / "terms.txt"
        write(path, "קיסריה\n")
        before = path.read_text(encoding="utf-8")

        assert term_store.add_term(str(path), variant) is False
        assert path.read_text(encoding="utf-8") == before

    def test_final_letter_spelling_is_a_duplicate(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "ירושלים\n")
        assert term_store.add_term(str(path), "ירושלימ") is False

    def test_inner_whitespace_does_not_make_a_new_term(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "באר שבע\n")
        assert term_store.add_term(str(path), "באר   שבע") is False

    def test_a_commented_out_term_is_not_a_duplicate(self, tmp_path):
        """Commenting a line out is how a person disables a term by hand."""
        path = tmp_path / "terms.txt"
        write(path, "# קיסריה\n")
        assert term_store.add_term(str(path), "קיסריה")
        assert term_store.read_terms(str(path)) == ["קיסריה"]

    @pytest.mark.parametrize("bad", ["", "   ", "#קיסריה", "קיסריה\nבראודה"])
    def test_input_that_cannot_be_a_term_is_refused(self, tmp_path, bad):
        path = tmp_path / "terms.txt"
        with pytest.raises(ValueError):
            term_store.add_term(str(path), bad)
        assert not path.exists()


class TestRemoveTerm:
    def test_removes_only_that_term_and_keeps_comments_and_blanks(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "# places\nקיסריה\n\nבראודה\n# end\n")

        assert term_store.remove_term(str(path), "קיסריה")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines == ["# places", "", "בראודה", "# end"]

    def test_a_commented_out_copy_survives(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "# קיסריה\nקיסריה\n")
        term_store.remove_term(str(path), "קיסריה")
        assert path.read_text(encoding="utf-8").splitlines() == ["# קיסריה"]

    def test_removes_by_equivalent_spelling(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "קיסריה\n")
        assert term_store.remove_term(str(path), "קֵיסָרְיָה")
        assert term_store.read_terms(str(path)) == []

    def test_absent_term_changes_nothing(self, tmp_path):
        path = tmp_path / "terms.txt"
        write(path, "קיסריה\n")
        before = os.stat(path).st_mtime_ns

        assert term_store.remove_term(str(path), "בראודה") is False
        assert os.stat(path).st_mtime_ns == before

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert term_store.remove_term(str(tmp_path / "absent.txt"), "קיסריה") is False


class TestAtomicWrite:
    def test_a_failed_write_leaves_the_old_list_and_no_temp_file(self, tmp_path, monkeypatch):
        """A half-written list fails silently - the pass just has fewer terms."""
        path = tmp_path / "terms.txt"
        write(path, "קיסריה\n")

        def refuse(_src, _dst):
            raise PermissionError("file is locked")

        monkeypatch.setattr(term_store.os, "replace", refuse)
        with pytest.raises(OSError):
            term_store.add_term(str(path), "בראודה")

        assert term_store.read_terms(str(path)) == ["קיסריה"]
        assert os.listdir(tmp_path) == ["terms.txt"]


class TestTermListReadsWhatTheStoreWrites:
    def test_round_trip_into_the_matcher(self, tmp_path):
        path = tmp_path / "terms.txt"
        term_store.add_term(str(path), "קיסריה")
        term_store.add_term(str(path), "בראודה")

        terms = TermList.load(str(path))
        assert terms.terms == ["קיסריה", "בראודה"]
        assert terms.best_match("כיסריה") is not None
