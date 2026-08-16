"""
Tests for transcript rendering.

The bidi assertions here are deliberately at the codepoint level. Bracketed
timestamps inside Hebrew text are exactly the kind of thing that looks fine in
whichever editor you happen to open and silently regresses everywhere else, so
"it rendered correctly on my machine" is not a test.
"""

import json
import re
from html.parser import HTMLParser

import pytest

from speech_to_text.core.formatting import (
    LRI,
    PDI,
    RLM,
    format_hhmmss,
    format_plain,
    format_range,
    merge_turns,
    render_html,
)
from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD
from speech_to_text.core.segments import Segment, TranscriptDocument, Word

HE = "שלום עולם"


def seg(start, end, text=HE, speaker=None, words=None):
    return Segment(start=start, end=end, text=text, speaker=speaker, words=words or [])


def word(text, probability):
    return Word(start=0.0, end=1.0, text=text, probability=probability)


def payload(rendered):
    """Pull the page's data island back out, undoing the "<" escaping."""
    raw = re.search(r'id="transcript-data">(.*?)</script>', rendered, re.S).group(1)
    return json.loads(raw.replace("\u003c", "<"))


def doc(name, segments, failed=False):
    return TranscriptDocument(source_name=name, segments=segments, failed=failed)


class _ReferenceCollector(HTMLParser):
    """Collects every attribute through which an element would fetch something."""

    FETCHING = {"src", "href", "srcset", "poster", "data", "action"}

    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name.lower() not in self.FETCHING or not value:
                continue
            # A bare fragment points back into this same document - it is what
            # the table of contents is made of, and fetches nothing.
            if value.startswith("#"):
                continue
            self.found.append(f"<{tag} {name}={value!r}>")


def _external_references(rendered):
    parser = _ReferenceCollector()
    parser.feed(rendered)
    return parser.found


class TestTimeFormatting:

    @pytest.mark.parametrize("seconds,expected", [
        (0, "0:00:00"),
        (5, "0:00:05"),
        (83, "0:01:23"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
        (36000, "10:00:00"),
    ])
    def test_hhmmss(self, seconds, expected):
        assert format_hhmmss(seconds) == expected

    def test_negative_and_junk_do_not_raise(self):
        assert format_hhmmss(-5) == "0:00:00"
        assert format_hhmmss(None) == "0:00:00"
        assert format_hhmmss("abc") == "0:00:00"


class TestBidi:
    """The RTL bracket/hyphen problem - see the module docstring in core/formatting."""

    def test_range_is_wrapped_in_a_single_ltr_isolate(self):
        """
        One LRI/PDI pair around the whole range, not one per half: the hyphen
        separating the two times is itself a neutral character sitting
        between two LTR digit runs, the same shape that used to make the
        mirrored brackets misplace themselves inside RTL text.
        """
        out = format_range(83, 90)
        assert out.startswith(LRI)
        assert out.endswith(PDI)
        assert out.count(LRI) == 1 and out.count(PDI) == 1

    def test_start_time_appears_before_end_time_in_logical_order(self):
        """
        Same "logical order is not display order" property the old bracket
        test pinned, moved onto the separator: whatever a renderer does with
        the hyphen, the characters are stored start-then-end.
        """
        out = format_range(83, 150)
        assert out.index("1:23") < out.index("2:30")

    def test_range_promotes_both_ends_together_past_an_hour(self):
        """
        A long file must not render one end promoted and the other bare -
        "0:05:00 - 1:12:15" is legible, "5:00 - 72:15" reads as a wrong
        number rather than an hour boundary.
        """
        assert format_range(300, 4335) == f"{LRI}0:05:00 - 1:12:15{PDI}"

    def test_range_stays_unpromoted_under_an_hour(self):
        assert format_range(32, 65) == f"{LRI}0:32 - 1:05{PDI}"

    def test_control_characters_are_the_isolating_variants(self):
        """
        U+2066/U+2069, not the older U+202A/U+202C embeddings, which leak
        direction into surrounding text instead of isolating from it.
        """
        assert ord(LRI) == 0x2066
        assert ord(PDI) == 0x2069
        assert ord(RLM) == 0x200F


class TestTurnMerging:

    def test_consecutive_close_segments_merge(self):
        turns = merge_turns([seg(0, 3, "אחד"), seg(3.5, 6, "שתיים")])
        assert len(turns) == 1
        assert turns[0].text == "אחד שתיים"
        assert turns[0].start == 0
        assert turns[0].end == 6

    def test_long_pause_splits_a_turn(self):
        turns = merge_turns([seg(0, 3, "אחד"), seg(10, 12, "שתיים")])
        assert len(turns) == 2

    def test_speaker_change_splits_a_turn(self):
        turns = merge_turns([
            seg(0, 3, "אחד", speaker=0),
            seg(3.2, 6, "שתיים", speaker=1),
        ])
        assert len(turns) == 2
        assert [t.speaker for t in turns] == [0, 1]

    def test_turn_is_capped_so_it_stays_scannable(self):
        segments = [seg(i * 5, i * 5 + 5, f"חלק{i}") for i in range(30)]
        turns = merge_turns(segments)
        assert len(turns) > 1
        assert all(t.end - t.start <= 30 for t in turns)

    def test_blank_segments_are_skipped(self):
        turns = merge_turns([seg(0, 1, "אחד"), seg(1, 2, "   "), seg(2, 3, "שתיים")])
        assert len(turns) == 1
        assert turns[0].text == "אחד שתיים"


class TestFormatPlain:

    def test_empty_input(self):
        assert format_plain("") == ""

    def test_splits_sentences(self):
        assert format_plain("One. Two. Three!") == "One.\nTwo.\nThree!"


class TestRenderHtml:
    """
    render_html() replaced the plain-text render() entirely - see the module
    docstring for why a .txt file can't be fixed (direction has to be
    declared, not guessed) and the plan this shipped from for the decisions
    behind the HTML shape.
    """

    def test_document_shell(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        # data-doc-id rides on the same tag, so match the opening rather
        # than the whole element.
        assert '<html lang="he" dir="rtl"' in out
        assert "data-doc-id=" in out
        assert '<meta charset="utf-8">' in out

    def test_one_section_per_document_with_filename_heading(self):
        out = render_html([doc("first.wav", [seg(0, 1)]), doc("second.wav", [seg(0, 1)])])
        assert out.count('<section class="source"') == 2
        assert "<h1>first.wav</h1>" in out
        assert "<h1>second.wav</h1>" in out

    def test_outline_present_only_when_there_is_something_for_it_to_show(self):
        """
        No file list to show (one document) and no speaker to manage - the
        sidebar itself, and the toolbar button that opens it, both disappear
        rather than rendering an empty shell.
        """
        single = render_html([doc("only.wav", [seg(0, 1)])])
        assert 'class="outline"' not in single
        assert 'id="outline-toggle"' not in single

        multi = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert 'class="outline"' in multi
        assert 'id="outline-toggle"' in multi

    def test_outline_file_list_anchors_resolve_to_existing_section_ids(self):
        out = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert 'class="outline-file"' in out
        assert 'href="#src-0"' in out and 'id="src-0"' in out
        assert 'href="#src-1"' in out and 'id="src-1"' in out

    def test_single_document_with_speakers_still_gets_an_outline(self):
        """The sidebar is not gated purely on file count - one file with
        speakers to manage still needs somewhere for that roster to live."""
        out = render_html([doc("a.wav", [seg(0, 1, speaker=0)])], speaker_label="Speaker {n}")
        assert 'class="outline"' in out

    def test_one_article_per_merged_turn(self):
        segments = [seg(0, 2, "אחד"), seg(30, 32, "שתיים")]
        assert len(merge_turns(segments)) == 2
        out = render_html([doc("a.wav", segments)])
        assert out.count('<article class="turn"') == 2

    def test_sentence_heavy_turn_yields_multiple_paragraphs(self):
        out = render_html([doc("a.wav", [seg(0, 1, "אחד. שתיים. שלוש.")])])
        assert out.count("<p>") == 3

    def test_timestamp_has_ltr_direction_and_isolate_characters(self):
        """
        The timestamp is a button that seeks and bounds playback, but the
        bidi contract is unchanged: dir="ltr" is what the browser lays out
        on, and the isolate characters keep copied plain text ordered
        correctly outside the browser. Both, not either.
        """
        out = render_html([doc("a.wav", [seg(83, 90)])])
        assert '<button class="ts" dir="ltr"' in out
        assert f'{LRI}1:23 - 1:30{PDI}' in out

    def test_timestamp_button_carries_both_playback_bounds(self):
        out = render_html([doc("a.wav", [seg(83, 90)])])
        assert 'data-start="83.00"' in out
        assert 'data-end="90.00"' in out

    def test_speaker_numbering_is_one_based(self):
        out = render_html([doc("a.wav", [seg(0, 2, speaker=0)])], speaker_label="Speaker {n}")
        assert "Speaker 1" in out
        assert "Speaker 0" not in out

    def test_unattributed_segment_gets_no_speaker_span(self):
        out = render_html([doc("a.wav", [seg(0, 2, speaker=None)])], speaker_label="דובר {n}")
        assert 'class="spk"' not in out

    def test_toolbar_controls_sit_in_a_shared_grid_column_wrapper(self):
        """
        .tb-row is what ties the toolbar's actual controls to main's own grid
        track (see --layout-columns in transcript.css) - .toolbar itself is
        the three-track grid, but only .tb-row is placed in track 2, so the
        toolbar's controls occupy exactly the width the reading column does.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<div class="tb-row">' in out
        # The search and action groups are still inside the wrapper, not
        # siblings of it - .tb-row wraps them, it doesn't replace them.
        tb_row_start = out.index('<div class="tb-row">')
        header_end = out.index("</header>")
        assert 'class="tb-group tb-search"' in out[tb_row_start:header_end]
        assert 'class="tb-group tb-actions"' in out[tb_row_start:header_end]

    def test_speaker_button_is_wrapped_in_its_own_menu_anchor(self):
        """
        .spk-anchor is what the reassignment menu is positioned against (see
        its comment in transcript.css) - it has to wrap .spk directly, not
        just appear somewhere in the card, or the menu goes back to opening
        at the wrong place.
        """
        out = render_html([doc("a.wav", [seg(0, 2, speaker=0)])], speaker_label="Speaker {n}")
        assert '<span class="spk-anchor"><button type="button" class="spk"' in out

    def test_no_timestamps_no_speakers_gives_bare_paragraphs(self):
        out = render_html([doc("a.wav", [seg(0, 1, "שלום עולם. מה שלומך?")])], timestamps=False)
        assert "<h2>" not in out
        assert "<p>שלום עולם.</p>" in out
        assert "<p>מה שלומך?</p>" in out

    def test_failed_document_renders_notice_and_surrounding_documents_still_render(self):
        out = render_html([
            doc("before.wav", [seg(0, 1, "אחד")]),
            doc("broken.wav", [], failed=True),
            doc("after.wav", [seg(0, 1, "שתיים")]),
        ], failed_label="Transcription failed")
        assert "<h1>before.wav</h1>" in out
        assert "<h1>broken.wav</h1>" in out
        assert "<h1>after.wav</h1>" in out
        assert '<p class="failed">Transcription failed</p>' in out
        assert "אחד" in out and "שתיים" in out

    def test_escaping_prevents_live_script_injection(self):
        out = render_html([doc("a.wav", [seg(0, 1, "<script>alert(1)</script>")])])
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_output_is_fully_offline(self):
        """
        This app's whole premise is offline operation - no CDN, no fonts, no
        stylesheets, no scripts fetched from anywhere.

        Asserted by walking the parsed attributes rather than grepping for
        "src=", because the inlined script legitimately mentions that string
        in its own comments and code. What matters is that no *element* points
        at anything the browser would have to go and fetch.
        """
        out = render_html([
            doc("a.wav", [seg(0, 1, speaker=0)]),
            doc("b.wav", [seg(0, 1)], failed=True),
        ], speaker_label="Speaker {n}", failed_label="failed")

        loaders = _external_references(out)
        assert loaders == [], f"document would fetch: {loaders}"
        assert "http://" not in out
        assert "https://" not in out

        # No url(...) should appear at all now that the backdrop photo (the
        # one thing that ever needed one, embedded as a data: URI) is gone -
        # not in a style="" attribute, and not inside the inlined <style>
        # block either. A url(...) reappearing here would mean something new
        # is pointing off the page, which this app's offline premise forbids.
        urls = re.findall(r'url\(\s*([^)]*?)\s*\)', out)
        assert urls == [], f"unexpected url(...) in output: {urls}"


class TestDataPayload:
    """
    The page carries its own data island: per-word confidences the renderer
    would otherwise throw away, plus the already-translated chrome strings.
    """

    def test_low_confidence_words_are_published_with_probability(self):
        segments = [seg(0, 4, "אחד שתיים שלוש", words=[
            word("אחד", 0.99), word("שתיים", 0.30), word("שלוש", 0.95),
        ])]
        data = payload(render_html([doc("a.wav", segments)]))
        assert data["low"]["0-0"] == [["שתיים", 0.3, 0]]

    def test_confident_words_are_not_published(self):
        segments = [seg(0, 4, "אחד שתיים", words=[word("אחד", 0.99), word("שתיים", 0.98)])]
        data = payload(render_html([doc("a.wav", segments)]))
        assert data["low"] == {}

    def test_threshold_matches_the_hebrew_correction_pass(self):
        """One number, one meaning: 'uncertain' must not drift between the two."""
        data = payload(render_html([doc("a.wav", [seg(0, 1)])]))
        assert data["threshold"] == CONFIDENCE_THRESHOLD

    def test_repeated_word_is_flagged_only_where_it_was_uncertain(self):
        """
        The occurrence index is what stops a confident word being shaded just
        because an identical string elsewhere in the turn was doubted.
        """
        segments = [seg(0, 4, "כן ודאי כן", words=[
            word("כן", 0.99), word("ודאי", 0.97), word("כן", 0.20),
        ])]
        data = payload(render_html([doc("a.wav", segments)]))
        assert data["low"]["0-0"] == [["כן", 0.2, 1]]

    def test_payload_escapes_angle_brackets_so_it_cannot_close_the_script(self):
        segments = [seg(0, 4, "x", words=[word("</script><b>", 0.1)])]
        out = render_html([doc("a.wav", segments)])
        assert "</script><b>" not in out
        assert payload(out)["low"]["0-0"][0][0] == "</script><b>"

    def test_ui_strings_are_carried_as_data_not_rendered_by_the_worker(self):
        out = render_html([doc("a.wav", [seg(0, 1)])], ui_strings={"search": "חיפוש"})
        assert payload(out)["strings"]["search"] == "חיפוש"
        assert "חיפוש" in out


class TestEditableDocument:

    def test_turn_bodies_are_editable_and_labelled(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert 'contenteditable="true"' in out
        assert 'role="textbox"' in out
        assert 'aria-multiline="true"' in out

    def test_turns_carry_stable_identity_and_start_time(self):
        out = render_html([doc("a.wav", [seg(0, 2, "אחד"), seg(30, 32, "שתיים")])])
        assert 'data-turn="0-0"' in out
        assert 'data-turn="0-1"' in out
        assert 'data-start="30.00"' in out

    def test_doc_id_is_stable_within_a_render_and_unique_between_them(self):
        """It keys the browser's saved edits, so a collision would cross-load them."""
        def doc_id_of(rendered):
            return re.search(r'data-doc-id="(\w+)"', rendered).group(1)

        first = render_html([doc("a.wav", [seg(0, 1)])])
        second = render_html([doc("a.wav", [seg(0, 1)])])
        assert doc_id_of(first) != doc_id_of(second)

        pinned = render_html([doc("a.wav", [seg(0, 1)])], doc_id="fixed")
        assert 'data-doc-id="fixed"' in pinned

    def test_speaker_span_carries_its_translated_fallback(self):
        """The page cannot rebuild a translated label once a custom name is cleared."""
        out = render_html([doc("a.wav", [seg(0, 1, speaker=0)])], speaker_label="Speaker {n}")
        assert 'data-fallback="Speaker 1"' in out

    def test_speakers_strip_lists_each_speaker_once(self):
        segments = [seg(0, 2, "a", speaker=0), seg(10, 12, "b", speaker=1),
                    seg(20, 22, "c", speaker=0)]
        out = render_html([doc("a.wav", segments)], speaker_label="Speaker {n}")
        assert out.count('class="speaker-row"') == 2

    def test_speaker_row_turn_count_matches_rendered_turns(self):
        """
        The count next to each locate button has to describe reality, not
        just "how many segments came in" - two same-speaker segments close
        together merge into one turn (see TestTurnMerging), and the reading
        column only ever shows one .turn for that pair. The sidebar's count
        must agree with what a reader scrolling the column actually sees.
        """
        segments = [
            seg(0, 2, "a", speaker=0), seg(2.2, 4, "b", speaker=0),  # one merged turn
            seg(10, 12, "c", speaker=1),
            seg(20, 22, "d", speaker=1),
            seg(30, 32, "e", speaker=1),
        ]
        out = render_html([doc("a.wav", segments)], speaker_label="Speaker {n}")

        for speaker, expected in ((0, 1), (1, 3)):
            row = re.search(
                r'<div class="speaker-row" data-speaker="%d"[^>]*>.*?</div>' % speaker, out, re.S,
            ).group(0)
            # .turn's own data-speaker (not .spk's, which every turn also
            # carries) is the thing the reading column actually renders one
            # of per turn - counting that, rather than trusting the count
            # logic to grade its own homework, is what this test is for.
            turn_count = len(re.findall(
                r'<article class="turn" data-turn="[^"]*" data-start="[^"]*"'
                r' data-speaker="%d"' % speaker, out,
            ))
            assert turn_count == expected
            # The count is carried in two forms and both have to be right.
            # Visibly it is the bare number - the full phrase only fitted the
            # narrow sidebar button at an unreadable ~10px. In the accessible
            # name it is the full phrase, so a screen reader gets the count
            # too rather than an action label with the number stripped out.
            # Asserting only one of the two would let the other rot silently,
            # and the audible one is exactly the half nobody notices.
            assert f'<span class="spk-count" aria-hidden="true">{expected}</span>' in row
            assert f'({expected} turns)' in row
            assert 'aria-label="Step through this speaker&#x27;s turns (' in row

    def test_merge_turns_called_once_per_document(self, monkeypatch):
        """
        _render_speakers_html() needs the same merged turns
        _render_document_html() renders, and it used to get them by calling
        merge_turns() a second time on the same segments - real work
        (grouping every segment in the file) repeated for no reason. Spying
        on merge_turns itself, rather than just checking the output still
        looks right, is what actually catches a regression here: two calls
        that produce identical turns would pass every other assertion in
        this file while still doing the redundant work this test exists to
        rule out.
        """
        import speech_to_text.core.formatting as formatting_module

        calls = []
        real_merge_turns = formatting_module.merge_turns

        def spy(segments, *args, **kwargs):
            calls.append(segments)
            return real_merge_turns(segments, *args, **kwargs)

        monkeypatch.setattr(formatting_module, "merge_turns", spy)

        docs = [
            doc("a.wav", [seg(0, 1, "x", speaker=0)]),
            doc("b.wav", [seg(0, 1, "y", speaker=0)]),
        ]
        formatting_module.render_html(docs, speaker_label="Speaker {n}")
        assert len(calls) == len(docs)

    def test_no_speakers_means_no_speakers_strip(self):
        out = render_html([doc("a.wav", [seg(0, 1, speaker=None)])], speaker_label="Speaker {n}")
        assert 'class="speakers"' not in out

    def test_speakers_strip_lives_in_the_sidebar_not_the_source_section(self):
        """
        The strip moved out of the reading column entirely (Phase 3) - it
        used to render once per <section class="source">, duplicating the
        roster for every scroll past a file boundary. Asserted by checking
        the outline's own speakers wrapper contains it and no
        <section class="source">...</section> slice does.
        """
        import re

        segments = [seg(0, 2, "a", speaker=0), seg(10, 12, "b", speaker=1)]
        out = render_html([doc("a.wav", segments)], speaker_label="Speaker {n}")
        assert 'class="outline-speakers"' in out
        for section in re.findall(r'<section class="source".*?</section>', out, re.S):
            assert 'class="speakers' not in section
            assert 'class="speaker-row"' not in section

    def test_first_files_speakers_panel_is_marked_active(self):
        out = render_html([
            doc("a.wav", [seg(0, 1, speaker=0)]),
            doc("b.wav", [seg(0, 1, speaker=0)]),
        ], speaker_label="Speaker {n}")
        assert 'class="speakers active" data-file="0"' in out
        assert 'class="speakers" data-file="1"' in out

    def test_audio_is_referenced_relatively_and_only_for_usable_documents(self):
        out = render_html([
            doc("meeting.m4a", [seg(0, 1)]),
            doc("broken.mkv", [], failed=True),
        ], failed_label="failed")
        assert 'data-audio="meeting.m4a"' in out
        assert 'data-audio="broken.mkv"' not in out

    def test_plain_text_panel_exists_per_document(self):
        out = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert out.count('<section class="plain">') == 2

    def test_plain_text_panel_is_not_collapsible(self):
        """
        It was the thing this document gets used for most (pasting the whole
        recording elsewhere) and burying it inside a collapsed <details> was
        the wrong trade - see _render_plain_html()'s docstring.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert "<details" not in out
        assert "<summary" not in out

    def test_plain_text_rows_are_rendered_server_side_with_matching_turn_ids(self):
        """
        Two-way editing (Phase 4) is a relocation the other direction too:
        the plain-text panel used to be pure JavaScript output with nothing
        for a script-disabled reader to see. Each row is now rendered up
        front, keyed by the same data-turn id as its card, so
        transcript.js's rebuildPlain() only ever has to sync an existing
        element rather than build the panel from nothing.
        """
        out = render_html([doc("a.wav", [seg(0, 2, "אחד"), seg(30, 32, "שתיים")])])
        assert 'class="plain-row" data-turn="0-0"' in out
        assert 'class="plain-row" data-turn="0-1"' in out
        assert 'class="plain-prefix" contenteditable="false"' in out
        assert 'class="plain-body" contenteditable="true"' in out

    def test_plain_text_row_brackets_the_timestamp_inside_the_isolate(self):
        """
        The card's own pill stays bare ("0:32 - 1:05"); the plain-text
        panel - copied out into apps with no bidi engine - gets the
        stronger "[0:32 - 1:05]" cue, with the brackets inside the same
        LRI/PDI isolate as the range itself (see the module docstring and
        transcript.js's bracketedRange() for why outside the isolate would
        let them reorder the same way the range's own hyphen could).
        """
        out = render_html([doc("a.wav", [seg(32, 65)])])
        assert f"{LRI}[0:32 - 1:05]{PDI}" in out
        # The card's pill is unaffected - format_range() is reused, not
        # changed, so the un-bracketed form still appears for it.
        assert f"{LRI}0:32 - 1:05{PDI}" in out

    def test_file_bar_carries_filename_and_position(self):
        out = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert out.count('<header class="file-bar"') == 2
        assert "data-file-accent=" in out
        assert "1 / 2" in out and "2 / 2" in out

    def test_toast_element_is_a_live_region(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<div id="toast" class="toast" role="status" aria-live="polite" hidden>' in out


class TestInlinedAssets:

    def test_stylesheet_and_script_are_inlined(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert "<style>" in out and "</style>" in out
        assert "<script>" in out

    def test_assets_are_readable_through_the_package(self):
        """
        They are package data, not source-tree files - an install that drops
        them produces a silently broken document rather than an import error.
        """
        from speech_to_text.core.formatting import _asset
        assert "body {" in _asset("transcript.css")
        assert "localStorage" in _asset("transcript.js")


class TestPopoverStackingAndAnchoring:
    """
    Structural preconditions for the three popover bugs fixed alongside the
    centred layout: a card painting behind its own reassignment menu, that
    menu opening at the card's edge instead of under the clicked button, and
    the colour swatch menu being clipped by the sidebar's own scrollbar.

    The actual painting behaviour (does this pixel really sit on top of that
    one) is not something a Python test can observe - it was verified in a
    real browser instead (see the plan's verification section). What IS
    checked here, cheaply and on every run, is that the mechanism each fix
    depends on still exists: the explicit open-state class CSS keys off of,
    and the JS that sets/clears it.
    """

    def test_turn_menu_open_class_exists_with_a_higher_stack_level(self):
        """
        Every .turn is position: relative with no z-index of its own, so a
        card holding an open menu needs an explicit, higher-than-zero stack
        level or its later siblings (painted after it in DOM order, at the
        same stack level 0) cover it - see the long comment on
        .turn.menu-open in transcript.css for why this can't be :hover-keyed.
        """
        from speech_to_text.core.formatting import _asset

        css = _asset("transcript.css")
        match = re.search(r"\.turn\.menu-open\s*\{([^}]*)\}", css)
        assert match, ".turn.menu-open rule not found in transcript.css"
        assert re.search(r"z-index\s*:\s*[1-9]", match.group(1)), (
            "the open-state rule must set a positive z-index, or it ties "
            "with (rather than beats) its zero-level siblings"
        )

    def test_javascript_sets_and_clears_the_menu_open_class(self):
        """
        The class is only useful if transcript.js actually toggles it when a
        .spk-menu opens and closes - see menuOpenTurn in toggleMenu()/
        closeMenu().
        """
        from speech_to_text.core.formatting import _asset

        js = _asset("transcript.js")
        assert "classList.add('menu-open')" in js
        assert "classList.remove('menu-open')" in js

    def test_spk_menu_is_anchored_to_its_own_wrapper_not_the_turn(self):
        """
        .spk-anchor - not .spk itself (which cannot hold the menu's own
        <button> descendants - see the content-model comment in
        transcript.css) and not .turn (the old, wrong anchor that opened the
        menu at the card's edge) - has to be the positioned ancestor.
        """
        from speech_to_text.core.formatting import _asset

        css = _asset("transcript.css")
        match = re.search(r"\.spk-anchor\s*\{([^}]*)\}", css)
        assert match, ".spk-anchor rule not found in transcript.css"
        assert "position: relative" in match.group(1)

    def test_swatch_menu_is_detached_from_the_scrolling_sidebar_when_opened(self):
        """
        .outline is overflow-y: auto, which clips any ordinary
        position: absolute popover inside it at the sidebar's own edge - see
        the .swatch-menu comment in transcript.css for the two options
        weighed and why detaching to <body> with computed fixed coordinates
        was picked over restructuring the sidebar's scroll container.
        """
        from speech_to_text.core.formatting import _asset

        js = _asset("transcript.js")
        assert "document.body.appendChild(menu)" in js
        assert "positionDetachedMenu" in js
        assert "menu.style.position = 'fixed'" in js
