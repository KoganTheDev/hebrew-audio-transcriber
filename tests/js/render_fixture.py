"""
Prints a fixture transcript page to stdout, for tests/js/harness.mjs to feed
into jsdom.

Not a pytest module (no test_ prefix - pytest never collects it) and not
imported by anything under tests/: it is invoked as a subprocess, `python
tests/js/render_fixture.py <kind>`, precisely so the jsdom tests exercise
speech_to_text.core.formatting.render_html's REAL output rather than a
hand-written stand-in page that could quietly drift out of sync with what
the app actually generates. See tests/test_formatting.py's seg()/doc()
helpers, which the two fixtures below are built the same way as.

Two fixtures, selected by the one CLI argument:

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from speech_to_text.core.formatting import render_html  # noqa: E402
from speech_to_text.core.segments import Segment, TranscriptDocument, Word  # noqa: E402

HE = "שלום עולם מה שלומך"

UI_STRINGS = {
    "help": "Help", "help_title": "Help", "help_close": "Close help",
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
    documents = [
        doc("recording-one.wav", [
            seg(0, 3, "שלום אחד שתיים שלוש", speaker=0, words=[
                word("אחד", 0.99), word("שתיים", 0.20), word("שלוש", 0.95),
            ]),
            seg(5, 8, "שלום ארבע חמש שש", speaker=1),
        ]),
        doc("recording-two.wav", [
            seg(0, 4, "שלום שבע שמונה תשע", speaker=0),
        ]),
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


_FIXTURES = {"full": render_full, "degenerate": render_degenerate}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in _FIXTURES:
        sys.stderr.write(f"usage: render_fixture.py {{{'|'.join(_FIXTURES)}}}\n")
        sys.exit(2)
    sys.stdout.write(_FIXTURES[sys.argv[1]]())


if __name__ == "__main__":
    main()
