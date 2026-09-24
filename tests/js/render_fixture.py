"""
Prints a fixture transcript page to stdout, for tests/js/harness.mjs to feed
into jsdom.

Not a pytest module (no test_ prefix - pytest never collects it) and not
imported by anything under tests/: it is invoked as a subprocess, `python
tests/js/render_fixture.py <kind>`, precisely so the jsdom tests exercise
core.formatting.render_html's REAL output rather than a
hand-written stand-in page that could quietly drift out of sync with what
the app actually generates. See tests/test_formatting.py's seg()/doc()
helpers, which the fixtures below are built the same way as.

Fixtures, selected by the one CLI argument:

  full        Two files, each with a speaker on part of it, and timestamps
              on (the default) - exercises every one of the tour's eight
              steps (.file-bar, .outline, .tb-search, .speakers, .turn .ts,
              .turn .body[contenteditable], #toggle-flags, #export) and
              gives the speaker-rename/reassignment and audio-adjacent tests
              something real to click.

  degenerate  One file, no speaker on its one segment, timestamps off. No
              outline (a single file with no speakers to manage - see
              _render_outline_html()'s docstring), no .speakers strip, no
              .ts buttons - only .file-bar, .tb-search, the editable body,
              #toggle-flags and #export are left, so the tour must resolve
              to five steps instead of eight. Exists specifically to prove
              resolveTourSteps() adapts to what a render actually contains
              rather than assuming the full eight every time.

  triple      One file, one turn with THREE sentences under one speaker,
              followed by a second turn under a different speaker - the
              "full" fixture's turns only ever hold one or two sentences,
              which is enough to prove a run merges/splits at a TURN
              boundary but not enough to show a per-sentence override
              opening a run boundary in the MIDDLE of a turn and the
              original speaker resuming right after it (tests/js/
              line-speaker.test.mjs's mid-turn split/resume/merge coverage).

  unattributed  One file, three turns, the MIDDLE one with speaker=None -
              diarization ran and placed the others, but found no span for
              that one. Unlike "degenerate" (where nothing has a speaker and
              no .speakers strip renders at all) this document has a real
              roster, so the unattributed chip has somewhere to reassign to.
              Covers the chip rendering, opening its menu, and the override
              clearing back to the unattributed resting state.

  three-speakers  One file, THREE speakers, the middle one (id 1) holding two
              separate turns. The remove control is hidden below three
              speakers (syncRemoveControls()), so this is the only fixture
              that can exercise deleting one - and deleting the MIDDLE id is
              what leaves the roster non-contiguous, which addSpeaker() has
              to survive.

  split       One file, two sentences under one speaker, and the ONLY fixture
              with real per-word timings. Every other one builds words with
              word(), which pins start=0/end=1 because it exists to carry a
              probability for the low-confidence tests - useless for
              splitting, which needs the boundary between two adjacent words
              to be a distinct number. Six words with clean one-second spans,
              so a test can assert a cut landed on a specific boundary rather
              than merely somewhere inside.


doc_id is pinned per fixture (not left to render_html()'s own random uuid4)
so the two fixtures' localStorage autosave keys ("hebrew-transcript:" +
doc_id) are stable across runs - useful for a test that wants to seed
localStorage before building the window. vista is pinned to vista-03.webp
for the same determinism reason TestVistaBackdrop pins one in
tests/test_formatting.py, and because an unpinned render's own
random.choice() has nothing to do with anything these tests check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from core.formatting import render_html  # noqa: E402
from core.segments import Segment, TranscriptDocument, Word  # noqa: E402

HE = "שלום עולם מה שלומך"

UI_STRINGS = {
    "help": "Help",
    "help_title": "Help",
    "help_close": "Close help",
    "tour_start": "Start guided tour",
}


def seg(start, end, text=HE, speaker=None, words=None):
    return Segment(start=start, end=end, text=text, speaker=speaker, words=words or [])


def word(text, probability):
    return Word(start=0.0, end=1.0, text=text, probability=probability)


def doc(name, segments, failed=False):
    return TranscriptDocument(source_name=name, segments=segments, failed=failed)


def render_full():
    # "שלום" is repeated across all three turns, in two different files, on
    # purpose - tests/js/search.test.mjs needs several matches spread across
    # more than one turn to prove Enter/Shift+Enter actually step between
    # them rather than only ever landing on the first.
    #
    # The first turn's text carries two sentences (the period after "שלוש"
    # is what split_sentences() keys on - see timecode.py) so this fixture
    # renders two <div class="bubble"> under one <article class="turn">, not
    # one - tests/js/bubbles.test.mjs needs a real multi-bubble turn to
    # exercise readParagraphs()/writeParagraphs() actually walking more than
    # a single bubble, and to exercise a paragraph-count change (an edit
    # that drops from two paragraphs to one, or grows from two to three)
    # against a turn that starts with more than one. The three flagged words
    # stay inside the first sentence, so the low-confidence tests elsewhere
    # (editing.test.mjs) are untouched by the split.
    documents = [
        doc(
            "recording-one.wav",
            [
                seg(
                    0,
                    3,
                    "שלום אחד שתיים שלוש. עוד משפט קצר",
                    speaker=0,
                    words=[
                        word("אחד", 0.99),
                        word("שתיים", 0.20),
                        word("שלוש", 0.95),
                    ],
                ),
                seg(5, 8, "שלום ארבע חמש שש", speaker=1),
            ],
        ),
        doc(
            "recording-two.wav",
            [
                seg(0, 4, "שלום שבע שמונה תשע", speaker=0),
            ],
        ),
    ]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=True,
        title="fixture",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-full",
        vista="vista-03.webp",
    )


def render_degenerate():
    documents = [doc("only.wav", [seg(0, 2, HE, speaker=None)])]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=False,
        title="fixture-degenerate",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-degenerate",
        vista="vista-03.webp",
    )


def render_triple():
    # Turn "0-0": one speaker, three sentences (two periods split
    # "אחד. שתיים. שלוש." into three) - enough sentences for a MIDDLE one to
    # be overridden while a real sentence still follows it, so a test can
    # show the original speaker resuming after a mid-turn split rather than
    # just observing the split itself.
    # Turn "0-1": a different speaker, one sentence - gives the last
    # sentence of turn "0-0" a real, differently-named neighbour to merge
    # into when it is reassigned.
    documents = [
        doc(
            "recording-one.wav",
            [
                seg(0, 3, "אחד. שתיים. שלוש.", speaker=0),
                seg(5, 6, "ארבע", speaker=1),
            ],
        ),
    ]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=True,
        title="fixture-triple",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-triple",
        vista="vista-03.webp",
    )


def render_unattributed():
    # A document that HAS diarization but could not place one of its turns -
    # speaker_attribution.py leaves speaker=None when no span overlapped, or
    # when the gap was too wide to borrow a neighbour's label across. That is
    # a different case from "degenerate" above, where NO turn has a speaker
    # because diarization never ran: here a real .speakers strip exists, so
    # the unattributed chip has somewhere to reassign TO.
    documents = [
        doc(
            "recording-one.wav",
            [
                seg(0, 3, "אחד שתיים שלוש", speaker=0),
                seg(5, 6, "ארבע חמש", speaker=None),
                seg(8, 9, "שש שבע", speaker=1),
            ],
        ),
    ]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=True,
        title="fixture-unattributed",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-unattributed",
        vista="vista-03.webp",
    )


def render_three_speakers():
    # THREE speakers, which is the floor + 1: the remove control is hidden
    # while a file has only two (syncRemoveControls() in
    # js/24-speakers-menus.js), so every other fixture here is deliberately
    # unable to exercise it. Speaker 1 is the middle id, so deleting it also
    # covers the non-contiguous-id case addSpeaker() has to survive.
    documents = [
        doc(
            "recording-one.wav",
            [
                seg(0, 3, "אחד שתיים", speaker=0),
                seg(4, 6, "שלוש ארבע", speaker=1),
                seg(7, 9, "חמש שש", speaker=2),
                seg(10, 12, "שבע שמונה", speaker=1),
            ],
        ),
    ]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=True,
        title="fixture-three",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-three",
        vista="vista-03.webp",
    )


def render_split():
    # The only fixture with REAL per-word timings. Every other one builds
    # words with word(), which pins start=0/end=1 because it exists to carry a
    # probability for the low-confidence tests - useless for splitting, which
    # needs the boundary between two adjacent words to be a distinct number.
    #
    # Two sentences under one speaker, six words with clean one-second spans,
    # so a test can assert the cut landed on a specific boundary rather than
    # merely "somewhere inside".
    timed = [
        Word(start=0.0, end=1.0, text="אחד", probability=0.99),
        Word(start=1.0, end=2.0, text=" שתיים", probability=0.99),
        Word(start=2.0, end=3.0, text=" שלוש.", probability=0.99),
        Word(start=3.0, end=4.0, text=" ארבע", probability=0.99),
        Word(start=4.0, end=5.0, text=" חמש", probability=0.99),
        Word(start=5.0, end=6.0, text=" שש", probability=0.99),
    ]
    documents = [
        doc(
            "recording-one.wav",
            [
                Segment(
                    start=0.0, end=6.0, text="אחד שתיים שלוש. ארבע חמש שש", speaker=0, words=timed
                ),
                seg(8, 10, "שבע שמונה", speaker=1),
            ],
        ),
    ]
    return render_html(
        documents,
        speaker_label="Speaker {n}",
        timestamps=True,
        title="fixture-split",
        ui_strings=UI_STRINGS,
        doc_id="js-fixture-split",
        vista="vista-03.webp",
    )


_FIXTURES = {
    "full": render_full,
    "degenerate": render_degenerate,
    "triple": render_triple,
    "unattributed": render_unattributed,
    "three-speakers": render_three_speakers,
    "split": render_split,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in _FIXTURES:
        sys.stderr.write(f"usage: render_fixture.py {{{'|'.join(_FIXTURES)}}}\n")
        sys.exit(2)
    sys.stdout.write(_FIXTURES[sys.argv[1]]())


if __name__ == "__main__":
    main()
