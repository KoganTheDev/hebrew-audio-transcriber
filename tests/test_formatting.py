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
    Sentence,
    Turn,
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


_INLINED_ASSETS = re.compile(r"<(style|script)\b.*?</\1>", re.S)


def markup(rendered):
    """
    The page with its inlined <style> and <script> blocks removed.

    render_html() splices the whole stylesheet and the whole script into the
    document, so a plain rendered.count("<p>") also counts every occurrence
    of that substring in CSS and JS *source comments*. That has now broken
    twice, both times because someone wrote an accurate comment mentioning
    the markup it manipulates, and both times the reflex fix was to reword
    the comment - which makes source prose hostage to a test assertion and
    leaves the trap armed for the next person.

    Counting assertions should use this instead, so they measure the
    document the renderer produced rather than the assets it carries.
    """
    return _INLINED_ASSETS.sub("", rendered)


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


class TestSentences:
    """
    Turn.sentences() - the time span behind each bubble. text is always
    exactly split_sentences(turn.text); what these tests actually cover is
    the span derivation and its required fallback (turns.py:sentences()).
    """

    def test_spans_are_derived_by_walking_the_word_list(self):
        """
        Two sentences, four words, word.text carrying its own leading space
        the way faster-whisper actually emits it - matching is done on
        whitespace-collapsed length, not exact concatenation, which is what
        this fixture exercises: none of these word strings equal a slice of
        the sentence text byte-for-byte.
        """
        words = [
            Word(start=0.0, end=0.5, text="אחד", probability=0.9),
            Word(start=0.5, end=1.0, text=" שתיים.", probability=0.9),
            Word(start=1.5, end=2.0, text=" שלוש", probability=0.9),
            Word(start=2.0, end=2.5, text=" ארבע.", probability=0.9),
        ]
        segment = seg(0.0, 2.5, "אחד שתיים. שלוש ארבע.", words=words)
        turn = merge_turns([segment])[0]

        sentences = turn.sentences()

        assert [s.text for s in sentences] == ["אחד שתיים.", "שלוש ארבע."]
        assert (sentences[0].start, sentences[0].end) == (0.0, 1.0)
        assert (sentences[1].start, sentences[1].end) == (1.5, 2.5)
        assert [w.text for w in sentences[0].words] == ["אחד", " שתיים."]

    def test_empty_words_falls_back_to_the_turn_span_for_every_sentence(self):
        """
        REQUIRED FALLBACK: no word timestamps (stereo per-channel path, or a
        model run without word_timestamps) must never raise, and must give
        every sentence the turn's own start/end - the same degrade shape
        split_sentences() itself already uses.
        """
        turn = merge_turns([seg(5.0, 10.0, "אחד. שתיים.", words=[])])[0]

        sentences = turn.sentences()

        assert len(sentences) == 2
        assert all(s.start == 5.0 and s.end == 10.0 for s in sentences)
        assert all(s.words == [] for s in sentences)

    def test_empty_text_yields_no_sentences(self):
        # merge_turns() already drops blank segments, so build the Turn
        # directly - this exercises sentences() in isolation, not the
        # merge path.
        turn = Turn(seg(0.0, 1.0, ""))
        assert turn.sentences() == []


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
        sidebar itself disappears rather than rendering an empty shell.

        There used to be a second thing gated the same way: a toolbar
        button (#outline-toggle) that only made sense when there was a
        sidebar to open. That button is gone outright now - the outline is
        always part of the page's own flow (a two-column rail down to a
        stacking breakpoint, then a band above the transcript - see
        transcript.css), so there is nothing left needing a toggle to
        reveal it, in either markup case checked here.
        """
        single = render_html([doc("only.wav", [seg(0, 1)])])
        assert 'class="outline"' not in single
        assert 'id="outline-toggle"' not in single

        multi = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert 'class="outline"' in multi
        assert 'id="outline-toggle"' not in multi

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
        out = markup(render_html([doc("a.wav", [seg(0, 1, "אחד. שתיים. שלוש.")])]))
        assert out.count("<p>") == 3
        # One bubble per paragraph, not three paragraphs in one bubble.
        assert out.count('<div class="bubble"') == 3

    def test_timestamp_has_ltr_direction_and_isolate_characters(self):
        """
        The timestamp is a button that seeks and bounds playback, but the
        bidi contract is unchanged: dir="ltr" is what the browser lays out
        on, and the isolate characters keep copied plain text ordered
        correctly outside the browser. Both, not either. Lives on the
        bubble now - there is no more cluster-header .ts to check, see
        _render_turn_html()'s docstring.
        """
        out = render_html([doc("a.wav", [seg(83, 90)])])
        assert '<button type="button" class="ts" dir="ltr"' in out
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
        .bubble-spk-anchor is what the reassignment menu is positioned
        against (see its comment in transcript.css) - it has to wrap
        .bubble-spk directly, not just appear somewhere in the card, or the
        menu goes back to opening at the wrong place. There is no more
        cluster-header .spk/.spk-anchor pair - see _render_turn_html()'s
        docstring for why the chip (and its menu) now live on the bubble.
        """
        out = render_html([doc("a.wav", [seg(0, 2, speaker=0)])], speaker_label="Speaker {n}")
        assert (
            '<span class="bubble-spk-anchor" contenteditable="false">'
            '<button type="button" class="bubble-spk"'
        ) in out

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

        Rendered with a pinned vista (rather than the default random choice)
        so this test's own no-network guarantee doesn't depend on
        random.choice happening to run at all - the backdrop's url(...) is
        exercised either way once a vista exists on disk.
        """
        out = render_html([
            doc("a.wav", [seg(0, 1, speaker=0)]),
            doc("b.wav", [seg(0, 1)], failed=True),
        ], speaker_label="Speaker {n}", failed_label="failed", vista="vista-01.webp")

        loaders = _external_references(out)
        assert loaders == [], f"document would fetch: {loaders}"
        assert "http://" not in out
        assert "https://" not in out

        # A data: URI is not "external" and must keep passing - the property
        # being protected is "this page fetches nothing", which holds equally
        # whether the image bytes are inline or the element is absent. What
        # must never appear is a url(...) that points off the page: not in a
        # style="" attribute, and not inside the inlined <style> block either.
        # _external_references() above does not catch this on its own: "style"
        # is not in its FETCHING attribute set, since a style attribute's
        # *value* pointing off-page is not the same shape of bug as an
        # href/src doing so, and needs its own check.
        urls = re.findall(r'url\(\s*([^)]*?)\s*\)', out)
        assert urls, "expected at least one url(...) - the pinned backdrop"
        for raw in urls:
            value = raw.strip("'\"")
            assert value.startswith("data:"), f"non-data url(...) found: {raw!r}"


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

    def test_speaker_row_has_no_locate_button_or_turn_count(self):
        """
        Both were deleted as sidebar clutter (not relocated) - the row is now
        just the swatch trigger and the name input. Regression guard for the
        removal, the mirror image of the count test this replaces.
        """
        segments = [
            seg(0, 2, "a", speaker=0), seg(2.2, 4, "b", speaker=0),
            seg(10, 12, "c", speaker=1),
        ]
        out = render_html([doc("a.wav", segments)], speaker_label="Speaker {n}")
        assert "spk-locate" not in out
        assert "spk-count" not in out
        assert "i-locate" not in out
        assert "Step through this speaker" not in out

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
        assert 'class="plain-body" contenteditable="true"' in out
        # No speaker_label passed to this render at all, so no heading can
        # ever render (see _render_plain_row_html()'s docstring) - checked
        # explicitly here since a stray heading div would otherwise sneak
        # past every other assertion in this file.
        assert 'class="plain-heading"' not in out

    def test_plain_text_row_brackets_the_timestamp_inside_the_isolate(self):
        """
        Per-sentence now, not per-turn: the plain-text panel's own range
        moved down to sit beside each sentence's number (see
        _render_plain_row_html()'s docstring), in its OWN isolate, separate
        from the number's - see the RTL-dot tests below for why the two are
        no longer one isolate.
        """
        out = render_html([doc("a.wav", [seg(32, 65)])])
        assert f"{LRI}1{PDI}. {LRI}[0:32 - 1:05]{PDI}" in out
        # The card's pill is unaffected - format_range() is reused, not
        # changed, so the un-bracketed form still appears for it.
        assert f"{LRI}0:32 - 1:05{PDI}" in out

    def test_plain_row_lead_in_is_two_isolates_with_the_dot_outside_both(self):
        """
        Codepoint-level check of the RTL dot fix itself (this file asserts
        bidi at codepoint level on purpose - see the module docstring): the
        number sits in its own isolate, then a literal ". " OUTSIDE any
        isolate, then (with timestamps on) the range in a second isolate of
        its own. A single isolate around the whole lead-in - the old shape -
        put the dot to the digit's right once the paragraph resolved RTL;
        splitting it like this is what puts the dot on the digit's LEFT
        instead (see the review plan's "the RTL dot" section for the
        browser-measured glyph positions this fixes).
        """
        with_ts = render_html([doc("a.wav", [seg(0, 2)])])
        assert f"{LRI}1{PDI}. {LRI}[0:00 - 0:02]{PDI} " in with_ts

        without_ts = render_html([doc("a.wav", [seg(0, 2)])], timestamps=False)
        row = re.search(r'<span class="plain-body"[^>]*>(.*?)</span>', without_ts, re.S).group(1)
        assert row.startswith(f"{LRI}1{PDI}. ")
        # No second isolate at all with timestamps off - there is nothing
        # for it to wrap.
        assert LRI not in row[len(f"{LRI}1{PDI}. "):]

    def test_file_bar_carries_filename_and_position(self):
        out = render_html([doc("a.wav", [seg(0, 1)]), doc("b.wav", [seg(0, 1)])])
        assert out.count('<header class="file-bar"') == 2
        assert "data-file-accent=" in out
        assert "1 / 2" in out and "2 / 2" in out

    def test_toast_element_is_a_live_region(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<div id="toast" class="toast" role="status" aria-live="polite" hidden>' in out


class TestBubbles:
    """
    One sentence, one bubble - the level added inside .turn (now the
    cluster) by the sentence-bubbles rewrite. See _render_bubble_html()'s
    and _render_turn_html()'s docstrings in formatting/document.py.
    """

    def test_bubble_markup_shape(self):
        """
        No speaker_label passed here, so the chip is absent entirely (see
        _render_bubble_html()'s docstring) - test_bubble_carries_a_chip_
        range_and_copy below covers the with-speaker shape, chip included.
        """
        out = render_html([doc("a.wav", [seg(0, 1, "אחד. שתיים.")])])
        assert re.search(
            r'<div class="bubble" data-line="0-0-0" data-turn="0-0"'
            r' data-start="0\.00" data-end="1\.00">'
            r'<p>אחד\.</p>'
            r'<button type="button" class="ts" dir="ltr" contenteditable="false"'
            r' aria-label="[^"]+">.*?</button>'
            r'<button class="icon-btn copy-line" aria-label="[^"]+"'
            r' contenteditable="false">.*?</button>'
            r'</div>',
            out,
        ), out
        # No sentence number on the bubble any more - it lives only in the
        # plain-text panel now (see _render_bubble_html()'s docstring).
        assert 'class="line-no"' not in out

    def test_bubble_carries_a_chip_range_and_copy(self):
        """
        The flat-card shape: a speaker chip (always shown, in the block's
        own palette colour), a play control showing the sentence's RANGE,
        and a copy button - see _render_bubble_html()'s docstring for why
        each moved onto the card once the cluster header went away.
        """
        out = render_html(
            [doc("a.wav", [seg(0, 2, "שלום עולם.", speaker=0)])],
            speaker_label="Speaker {n}",
        )
        bubble = re.search(r'<div class="bubble".*?</div>', out, re.S).group(0)
        assert 'data-line="0-0-0"' in bubble
        assert 'data-start="0.00"' in bubble
        assert 'data-end="2.00"' in bubble
        assert 'data-speaker="0"' in bubble
        assert 'data-palette="0"' in bubble
        chip = re.search(r'<button type="button" class="bubble-spk"[^>]*>.*?</button>', bubble, re.S)
        assert chip, bubble
        assert 'data-speaker="0"' in chip.group(0)
        assert '<span class="bubble-spk-label">Speaker 1</span>' in chip.group(0)
        assert '<button type="button" class="ts" dir="ltr"' in bubble
        assert f'{LRI}0:00 - 0:02{PDI}' in bubble
        assert 'class="icon-btn copy-line"' in bubble

    def test_bubble_timestamp_is_a_real_button(self):
        """
        Reachable by keyboard, not just clickable. bindAudio() binds every
        ".ts" on the page, so a bubble's timestamp is a real click target -
        and a <span> is inert to Tab whatever it is styled to look like,
        which would make the hover and focus styling in 52-bubble.css a
        promise the markup cannot keep. It also needs a label naming the
        instant, since the visible text alone ("0:02") does not say what
        activating it does.
        """
        out = markup(render_html([doc("a.wav", [seg(83, 90, "אחד.")])]))
        bubble = re.search(r'<div class="bubble".*?</div>', out, re.S).group(0)
        button = re.search(r"<button[^>]*class=\"ts\"[^>]*>", bubble)
        assert button, bubble
        assert 'type="button"' in button.group(0)
        assert 'aria-label="Play from 0:01:23"' in button.group(0)

    def test_bubble_furniture_is_not_editable(self):
        """
        A bubble lives inside .body, which is contenteditable="true" so the
        sentence can be corrected in place. That makes every other text node
        in the subtree editable too, so the timestamp has to opt out
        explicitly - otherwise a backspace at the start of a line eats it and
        readParagraphs() persists the damage. The plain-panel lead-in already
        opts out the same way.
        """
        out = markup(render_html([doc("a.wav", [seg(0, 1, "אחד.")])]))
        bubble = re.search(r'<div class="bubble".*?</div>', out, re.S).group(0)
        element = re.search(r'<button[^>]*class="ts"[^>]*>', bubble)
        assert element, bubble
        assert 'contenteditable="false"' in element.group(0), element.group(0)

    def test_bubble_time_shows_a_rounded_range_not_a_degenerate_instant(self):
        """
        The card's play control shows the sentence's RANGE, per the review
        plan's "flat sentence cards" section - reusing _display_end_second()
        (originally added for the plain-text panel) to avoid the degenerate
        "0:00 - 0:00" a sub-second sentence would otherwise render at
        whole-second resolution. data-end still carries the TRUE,
        un-rounded end for playback - only the visible label is floored.
        """
        words = [
            Word(start=0.0, end=0.4, text="אחד", probability=0.9),
            Word(start=0.4, end=0.9, text=" שתיים.", probability=0.9),
        ]
        out = render_html([doc("a.wav", [seg(0.0, 0.9, "אחד שתיים.", words=words)])])
        bubble = re.search(r'<div class="bubble".*?</div>', out, re.S).group(0)
        assert 'data-end="0.90"' in bubble
        assert f'{LRI}0:00 - 0:01{PDI}' in bubble
        assert "0:00 - 0:00" not in bubble

    def test_bubble_carries_its_own_span_not_the_turns(self):
        """
        Per-bubble spans come from Turn.sentences(), not a shared copy of
        the turn's own start/end - two sentences with real word timings
        must show two different bubble ranges.
        """
        words = [
            Word(start=0.0, end=0.4, text="אחד", probability=0.9),
            Word(start=0.4, end=0.8, text=" שתיים.", probability=0.9),
            Word(start=5.0, end=5.4, text=" שלוש", probability=0.9),
            Word(start=5.4, end=5.8, text=" ארבע.", probability=0.9),
        ]
        segment = seg(0.0, 5.8, "אחד שתיים. שלוש ארבע.", words=words)
        out = render_html([doc("a.wav", [segment])])
        assert 'data-line="0-0-0" data-turn="0-0" data-start="0.00" data-end="0.80"' in out
        assert 'data-line="0-0-1" data-turn="0-0" data-start="5.00" data-end="5.80"' in out

    def test_bubble_omits_ts_span_when_timestamps_are_off(self):
        out = render_html([doc("a.wav", [seg(0, 1, "אחד.")])], timestamps=False)
        bubble = re.search(r'<div class="bubble".*?</div>', out, re.S).group(0)
        assert 'class="ts"' not in bubble
        # data-start/data-end stay on the bubble regardless - playback needs
        # them even when the visible range span is hidden, matching the
        # turn article's own always-present data-start.
        assert 'data-start="0.00"' in bubble

    def test_sentence_numbers_run_continuously_across_turns_in_one_document(self):
        """
        Numbering lives only in the plain-text panel now - bubbles carry no
        number of their own any more (see _render_bubble_html()'s
        docstring) - and the panel's count must not reset at a turn
        boundary: a second turn's first sentence continues from the first
        turn's last sentence's number, not from 1 again.
        """
        segments = [
            seg(0, 1, "אחד. שתיים.", speaker=0),
            seg(10, 11, "שלוש.", speaker=1),
        ]
        out = render_html([doc("a.wav", segments)], speaker_label="Speaker {n}")

        # "{LRI}{n}{PDI}." is the plain-row lead-in's own shape (see
        # _render_plain_row_html()); nothing else on the page emits a
        # digit run isolated on its own, immediately followed by a literal
        # dot, so this pattern picks out only the plain-panel numbers.
        plain_numbers = re.findall(f'{LRI}(\\d+){PDI}\\.', out)
        assert plain_numbers == ["1", "2", "3"]

    def test_sentence_numbers_continue_across_multiple_documents_worth_of_turns(self):
        """
        Per-DOCUMENT, not per-batch: a second file's numbering restarts at 1
        rather than continuing from the first file's last sentence, because
        each file's plain-text panel and card set is its own self-contained
        unit a reader copies out independently.
        """
        out = render_html([
            doc("a.wav", [seg(0, 1, "אחד. שתיים.")]),
            doc("b.wav", [seg(0, 1, "שלוש.")]),
        ])
        plain_numbers = re.findall(f'{LRI}(\\d+){PDI}\\.', out)
        assert plain_numbers == ["1", "2", "1"]


class TestHelpPanel:
    """
    The help panel: a server-rendered, initially-hidden overlay explaining
    every toolbar control and reading-column affordance, plus #tour-start -
    the hook a separate guided-tour feature binds to. See
    _render_help_html()'s docstring in formatting.py.
    """

    def test_help_button_renders_with_label_and_aria_controls(self):
        out = render_html([doc("a.wav", [seg(0, 1)])], ui_strings={"help": "Help"})
        button = re.search(r'<button id="help".*?</button>', out, re.S)
        assert button, "#help button not found"
        assert 'aria-controls="help-panel"' in button.group(0)
        assert 'aria-expanded="false"' in button.group(0)
        assert "<span>Help</span>" in button.group(0)

    def test_help_panel_renders_hidden(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert re.search(
            r'<div id="help-panel" class="help-panel" role="dialog" '
            r'aria-modal="true" aria-labelledby="help-title" hidden>',
            out,
        )

    def test_tour_start_button_exists(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<button id="tour-start" class="tb-btn primary">' in out

    def test_hebrew_ui_strings_reach_the_help_panel(self):
        """
        Same "the worker never guesses a language" contract every other
        doc_ string already has (see test_ui_strings_are_carried_as_data_...
        in TestDataPayload) - Hebrew supplied via ui_strings must actually
        appear in the panel, not the English fallback.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])], ui_strings={
            "help": "עזרה",
            "help_title": "עזרה",
            "tour_start": "התחלת סיור מודרך",
            "help_search_title": "חיפוש",
        })
        assert "<span>עזרה</span>" in out
        assert '<h2 id="help-title">עזרה</h2>' in out
        assert '<button id="tour-start" class="tb-btn primary">התחלת סיור מודרך</button>' in out
        assert "חיפוש" in out

    def test_help_panel_covers_every_documented_control(self):
        """
        Regression guard for silently dropping an entry - each of these
        controls is real functionality (see the JS this panel documents),
        not free-standing prose, so losing one from _render_help_html()'s
        entries list should fail here rather than only be noticed by a
        reader who goes looking for it.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])])
        for icon in ("search", "flag", "theme", "save", "list", "plus", "play", "edit", "copy"):
            assert f'<dt><svg class="icon" aria-hidden="true"><use href="#i-{icon}">' in out

    def test_help_close_button_has_its_own_icon(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<button id="help-close" class="icon-btn"' in out
        assert "#i-close" in out


class TestDocStringsHaveBothLanguages:
    """
    formatting.py never imports gui.i18n (see the module docstring) - it can
    only ever render whatever a caller hands it through ui_strings, with an
    English fallback baked into the f-string itself (the `s()` helper). The
    actual translations still have to exist somewhere, though, and this is
    the one place that checks they do: every doc_ key STRINGS defines must
    carry both an "en" and a real "he" value, not just an English one with
    Hebrew silently falling back.
    """

    # The PyQt5/gui.i18n layering guard that used to live here now covers
    # every module under core/, not just formatting/ - see
    # tests/test_layering.py for the AST-walking check itself and its own
    # docstring for why the single-package version this replaced left the
    # other ~16 core/ modules with only a prose promise and no test behind
    # it.

    def test_every_doc_key_has_english_and_hebrew(self):
        from speech_to_text.gui.i18n import STRINGS

        doc_keys = [key for key in STRINGS if key.startswith("doc_help") or key in (
            "doc_help", "doc_tour_start",
        )]
        assert doc_keys, "expected at least the new help-panel doc_ keys to exist"
        for key in doc_keys:
            entry = STRINGS[key]
            assert entry.get("en"), f"{key} missing an 'en' value"
            assert entry.get("he"), f"{key} missing a 'he' value"
            assert entry["he"] != entry["en"], f"{key}'s Hebrew value is not translated"


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
        from speech_to_text.core.formatting.assets import _asset_dir
        assert "body {" in _asset_dir("css")
        assert "localStorage" in _asset_dir("js")


class TestVistaBackdrop:
    """
    The photographic backdrop: one photo per render, embedded as a data URI so
    the document stays a single file (see TestInlinedAssets and the offline
    test above for why nothing here may point off the page).
    """

    def test_pinned_vista_appears_as_a_base64_data_uri(self):
        out = render_html([doc("a.wav", [seg(0, 1)])], vista="vista-01.webp")
        assert 'class="backdrop"' in out
        assert 'aria-hidden="true"' in out
        assert "data:image/webp;base64," in out

    def test_two_default_renders_can_differ(self):
        """
        random.choice over 32 photos failing to differ once in a reasonable
        number of tries would be a red flag that selection isn't random at
        all, not proof it's broken - so this samples rather than asserting on
        a single pair.
        """
        renders = {render_html([doc("a.wav", [seg(0, 1)])]) for _ in range(10)}
        assert len(renders) > 1

    def test_missing_vistas_directory_renders_cleanly_with_no_backdrop(self, monkeypatch, tmp_path):
        import speech_to_text.core.formatting as formatting

        # Patched on formatting.assets, not on the formatting package itself:
        # _vista_names() is defined in formatting/assets.py and reads
        # _VISTAS_DIR from THAT module's own globals (see assets.py's module
        # docstring). Patching the re-exported formatting._VISTAS_DIR name
        # would only rebind the package's alias, leaving the global the
        # function actually closes over untouched - the patch would silently
        # do nothing and this test would pass for the wrong reason.
        formatting._vista_names.cache_clear()
        monkeypatch.setattr(formatting.assets, "_VISTAS_DIR", tmp_path / "does-not-exist")
        try:
            out = render_html([doc("a.wav", [seg(0, 1)])])
            assert 'class="backdrop"' not in out
        finally:
            formatting._vista_names.cache_clear()

    def test_unknown_pinned_vista_raises(self):
        with pytest.raises(ValueError):
            render_html([doc("a.wav", [seg(0, 1)])], vista="not-a-real-file.webp")

    def test_pinning_a_portrait_file_directly_raises(self):
        """
        "-portrait" files are an implementation detail of the landscape they
        belong to (see _vista_names()'s docstring) - callers, including a
        pinned vista=, only ever name the landscape file. Pinning the
        portrait file directly must fail exactly like any other name outside
        _vista_names(), not silently succeed and render a portrait-shaped
        photo as the desktop backdrop.
        """
        with pytest.raises(ValueError):
            render_html([doc("a.wav", [seg(0, 1)])], vista="vista-01-portrait.webp")

    def test_landscape_and_portrait_uris_are_both_embedded(self):
        """
        vista-01 ships a portrait crop (built by tools/build_vistas.py), so a
        pinned render must carry two distinct data URIs: one for the base
        .backdrop rule and one behind the narrow-viewport media query.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])], vista="vista-01.webp")
        uris = re.findall(r'data:image/webp;base64,[A-Za-z0-9+/=]+', out)
        assert len(uris) == 2
        assert uris[0] != uris[1]

    def test_portrait_swap_is_behind_the_narrow_aspect_media_query(self):
        """
        3/4, not orientation:portrait - see the media query's own comment in
        render_html() for why the switch point is an aspect ratio, not the
        orientation flip at 1:1.
        """
        out = render_html([doc("a.wav", [seg(0, 1)])], vista="vista-01.webp")
        assert "@media (max-aspect-ratio: 3/4)" in out
        assert re.search(
            r"@media \(max-aspect-ratio: 3/4\) \{ \.backdrop\{background-image:"
            r"url\(data:image/webp;base64,[A-Za-z0-9+/=]+\)\} \}",
            out,
        )

    def test_portrait_variants_are_excluded_from_random_vista_selection(self, monkeypatch, tmp_path):
        """
        Regression guard for the single most likely bug in art-directed
        backdrops: _vista_names() globs *.webp, and once a "-portrait" file
        sits next to its landscape original in the same directory, an
        unfiltered glob would let random.choice() pick the portrait crop as
        the MAIN backdrop, and would also double the odds of that photo
        being chosen at all relative to a photo with no portrait crop.
        """
        import speech_to_text.core.formatting as formatting

        vistas_dir = tmp_path / "vistas"
        vistas_dir.mkdir()
        (vistas_dir / "vista-01.webp").write_bytes(b"landscape-one")
        (vistas_dir / "vista-01-portrait.webp").write_bytes(b"portrait-one")
        (vistas_dir / "vista-02.webp").write_bytes(b"landscape-two")

        # See test_missing_vistas_directory_renders_cleanly_with_no_backdrop
        # above for why this patches formatting.assets, not formatting.
        monkeypatch.setattr(formatting.assets, "_VISTAS_DIR", vistas_dir)
        formatting._vista_names.cache_clear()
        try:
            names = formatting._vista_names()
            assert names == ("vista-01.webp", "vista-02.webp")
            assert not any(name.endswith("-portrait.webp") for name in names)
        finally:
            formatting._vista_names.cache_clear()

    def test_missing_portrait_variant_renders_landscape_only(self, monkeypatch, tmp_path):
        """
        A photo with no portrait crop on disk (an older installed package, or
        a photo build_vistas.py hasn't rebuilt yet) must still render its
        landscape backdrop with no @media swap, never raise.

        Both _ASSETS and _VISTAS_DIR are redirected into tmp_path (not just
        _VISTAS_DIR, the way test_missing_vistas_directory... above does):
        that test never reads a photo's bytes because it has zero vistas at
        all, but this one pins a real filename and needs _asset_bytes() -
        which reads through _ASSETS, not _VISTAS_DIR - to see the same fake,
        portrait-less file the name lookup does. Both are patched on
        formatting.assets, the module that actually defines and reads them -
        see test_missing_vistas_directory_renders_cleanly_with_no_backdrop's
        comment for why patching the formatting package's re-exported names
        would not do anything.
        """
        import speech_to_text.core.formatting as formatting

        assets_dir = tmp_path / "assets"
        vistas_dir = assets_dir / "vistas"
        vistas_dir.mkdir(parents=True)
        (vistas_dir / "vista-01.webp").write_bytes(b"landscape-only")
        # render_html() also inlines the stylesheet and script through
        # _ASSETS (the text half, _asset_dir() - unrelated to the vista byte
        # lookup this test is about), so the css/ and js/ fragment
        # directories have to exist under the fake root too, or the render
        # fails before it ever reaches the backdrop.
        real_assets = formatting.assets._ASSETS
        for kind in ("css", "js"):
            (assets_dir / kind).mkdir()
            for fragment in sorted((real_assets / kind).iterdir()):
                (assets_dir / kind / fragment.name).write_text(
                    fragment.read_text(encoding="utf-8"), encoding="utf-8",
                )

        monkeypatch.setattr(formatting.assets, "_ASSETS", assets_dir)
        monkeypatch.setattr(formatting.assets, "_VISTAS_DIR", vistas_dir)
        formatting._vista_names.cache_clear()
        formatting._asset_bytes.cache_clear()
        formatting._asset.cache_clear()
        try:
            out = render_html([doc("a.wav", [seg(0, 1)])], vista="vista-01.webp")
            assert 'class="backdrop"' in out
            uris = re.findall(r'data:image/webp;base64,[A-Za-z0-9+/=]+', out)
            assert len(uris) == 1
            # A live media-query rule, not just the phrase - transcript.css's
            # own explanatory comment (copied verbatim into <style>, like all
            # of transcript.css) mentions "@media (max-aspect-ratio: 3/4)" by
            # name, so a bare substring check would false-positive on that
            # comment even with no second backdrop rule present.
            assert not re.search(
                r"@media \(max-aspect-ratio: 3/4\) \{ \.backdrop", out,
            )
        finally:
            formatting._vista_names.cache_clear()
            formatting._asset_bytes.cache_clear()
            formatting._asset.cache_clear()


class TestRemovedIdentifiersNeverReappear:
    """
    The one place transcript.js/transcript.css are still checked by plain
    text search, and the only sanctioned reason left to do so: proving an
    identifier is ABSENT is not something behaviour can demonstrate. A
    passing jsdom test only ever proves the code paths it actually exercises
    behave correctly - it cannot prove a dead code path was never re-added,
    because nothing calls into a dead path to observe the difference. A grep
    can, cheaply, on every run.

    spk-locate (a sidebar "step through this speaker" button) and its whole
    supporting mechanism (spk-count, stepSpeakerTurns, speakerCycle,
    refreshSpeakerCounts, i-locate) were deleted outright, not relocated -
    see TestEditableDocument.test_speaker_row_has_no_locate_button_or_turn_count
    above for the render_html()-level half of this same guard (that one
    checks the rendered markup; this one checks the source those identifiers
    would have to appear in even if nothing wired them up to anything). A
    regression that brought either one back anywhere in the JS or CSS source
    should fail here rather than only be noticed by a reader who goes
    looking for it.

    Everything else that used to live here as a source-text assertion -
    applyNames() resolving its inputs from .speakers rather than .source,
    the menu-open class, the keyboard-modality flag, the help panel's
    wiring, the guided tour's stepping/cleanup/bidi/focus behaviour - is now
    a behavioural test in tests/js/ (see harness.mjs and its sibling
    *.test.mjs files), run via node --test and surfaced through pytest by
    tests/test_js_behaviour.py. Those assertions could observe the actual
    behaviour a reader experiences, so they moved; this one can't, so it
    stayed.
    """

    def test_no_locate_button_or_turn_count_mechanism_remains(self):
        from speech_to_text.core.formatting.assets import _asset_dir

        js, css = _asset_dir("js"), _asset_dir("css")
        for name in ("spk-locate", "spk-count", "stepSpeakerTurns", "speakerCycle",
                     "refreshSpeakerCounts", "i-locate"):
            assert name not in js, f"{name} still in the transcript script"
        for name in ("spk-locate", "spk-count"):
            assert name not in css, f"{name} still in the transcript stylesheet"


class TestPlayPauseGlyph:
    """
    _ICON_DEFS used to have "play" and no "pause" at all, so #player-toggle
    rendered a play triangle once and never changed, even while audio was
    playing.
    """

    def test_pause_symbol_exists_in_the_sprite(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        assert '<symbol id="i-pause" viewBox="0 0 24 24">' in out
        # Stroked, like every other glyph in the sprite (fill: none comes
        # from .icon in CSS) - a filled pair of bars would be the odd one
        # out here, and this locks that in rather than trusting the SVG to
        # merely look right once.
        match = re.search(r'<symbol id="i-pause"[^>]*>(.*?)</symbol>', out)
        assert match and "fill=" not in match.group(1)

    def test_player_toggle_starts_on_the_play_glyph(self):
        out = render_html([doc("a.wav", [seg(0, 1)])])
        toggle = re.search(r'<button id="player-toggle".*?</button>', out, re.S).group(0)
        assert '#i-play' in toggle
        assert '#i-pause' not in toggle

    # The JS half - the glyph and aria-label actually swapping on the
    # audio element's own play/pause events - is now
    # tests/js/chrome.test.mjs's "the play/pause glyph and its aria-label
    # swap together off the audio element's own play/pause events" test.


class TestPopoverStackingAndAnchoring:
    """
    Structural preconditions for the three popover bugs fixed alongside the
    centred layout: a card painting behind its own reassignment menu, that
    menu opening at the card's edge instead of under the clicked button, and
    the colour swatch menu being clipped by the sidebar's own scrollbar.

    The actual painting behaviour (does this pixel really sit on top of that
    one) is not something a Python test can observe - it was verified in a
    real browser instead (see the plan's verification section). What IS
    checked here, cheaply and on every run, is that the CSS mechanism each
    fix depends on still exists: the explicit open-state class, and
    .spk-anchor's own positioning context. The JS half of each - transcript.js
    actually toggling .menu-open, and actually detaching the swatch menu to
    <body> as position: fixed - is now behavioural, in
    tests/js/chrome.test.mjs.
    """

    def test_bubble_menu_open_class_exists_with_a_higher_stack_level(self):
        """
        Every .bubble is position: relative with no z-index of its own, so a
        card holding an open menu needs an explicit, higher-than-zero stack
        level or its later siblings (painted after it in DOM order, at the
        same stack level 0) cover it - see the long comment on
        .bubble.menu-open in 52-bubble.css for why this can't be
        :hover-keyed. Used to be .turn.menu-open, keyed to the cluster
        header's own card - now that cards are flat, one sentence wide, the
        card that needs raising is the .bubble the menu opened from.
        """
        from speech_to_text.core.formatting.assets import _asset_dir

        css = _asset_dir("css")
        match = re.search(r"\.bubble\.menu-open\s*\{([^}]*)\}", css)
        assert match, ".bubble.menu-open rule not found in transcript.css"
        assert re.search(r"z-index\s*:\s*[1-9]", match.group(1)), (
            "the open-state rule must set a positive z-index, or it ties "
            "with (rather than beats) its zero-level siblings"
        )

    def test_spk_menu_is_anchored_to_its_own_wrapper_not_the_turn(self):
        """
        .bubble-spk-anchor - not .bubble-spk itself (which cannot hold the
        menu's own <button> descendants - see the content-model comment in
        transcript.css) and not .turn (which would open the menu at the
        block's edge, not under the chip that was actually clicked) - has to
        be the positioned ancestor.
        """
        from speech_to_text.core.formatting.assets import _asset_dir

        css = _asset_dir("css")
        match = re.search(r"\.bubble-spk-anchor\s*\{([^}]*)\}", css)
        assert match, ".bubble-spk-anchor rule not found in transcript.css"
        assert "position: relative" in match.group(1)


class TestTourStrings:
    """
    Every doc_tour_* key STRINGS defines has to exist in both languages -
    same contract TestDocStringsHaveBothLanguages already checks for
    doc_help_*, extended here to cover the tour's own keys, which that
    test's key filter deliberately does not match.
    """

    def test_every_tour_key_has_english_and_hebrew(self):
        from speech_to_text.gui.i18n import STRINGS

        # doc_tour_step_position (like the pre-existing doc_file_position it
        # mirrors) is a bare "{i} / {n}" placeholder template with nothing
        # language-specific to translate - legitimately identical in both
        # languages, unlike every other key here.
        untranslated_ok = {"doc_tour_step_position"}

        doc_keys = [key for key in STRINGS if key.startswith("doc_tour")]
        assert doc_keys, "expected the tour's doc_tour_* keys to exist"
        for key in doc_keys:
            entry = STRINGS[key]
            assert entry.get("en"), f"{key} missing an 'en' value"
            assert entry.get("he"), f"{key} missing a 'he' value"
            if key not in untranslated_ok:
                assert entry["he"] != entry["en"], f"{key}'s Hebrew value is not translated"

    def test_step_and_control_keys_all_exist(self):
        from speech_to_text.gui.i18n import STRINGS

        required = [
            "doc_tour_start", "doc_tour_next", "doc_tour_back", "doc_tour_skip",
            "doc_tour_step_position",
            "doc_tour_file_title", "doc_tour_file_body",
            "doc_tour_outline_title", "doc_tour_outline_body",
            "doc_tour_search_title", "doc_tour_search_body",
            "doc_tour_speakers_title", "doc_tour_speakers_body",
            "doc_tour_playback_title", "doc_tour_playback_body",
            "doc_tour_editing_title", "doc_tour_editing_body",
            "doc_tour_flags_title", "doc_tour_flags_body",
            "doc_tour_export_title", "doc_tour_export_body",
        ]
        for key in required:
            assert key in STRINGS, f"{key} missing from STRINGS"

    def test_document_strings_carries_tour_keys_stripped_of_the_doc_prefix(self):
        from speech_to_text.gui.i18n import document_strings, set_language

        set_language("en")
        strings = document_strings()
        assert strings.get("tour_next") == "Next"
        assert strings.get("tour_step_position") == "{i} / {n}"
        assert "tour_file_title" in strings
