"""
Convert this app's own exported transcript HTML into an RTTM reference, so a
hand-corrected transcript can become a diarization fixture that
tests.eval.compare_diarization / diarization_metrics.read_rttm can score
against.

Why this exists: core/config/diarization.py's DIARIZATION_ENGINE docstring
names the blocker for tuning diarization at all - "powerset is opt-in until
someone measures it against Hebrew audio with real speaker labels - which
does not exist yet". An exported transcript, hand-corrected by a human in the
app's own editor, IS real speaker labels once its per-bubble speaker
attribution is pulled back out - src/core/assets/js/56-export.js's
bakeFormState()/paintBubbleOverride() write every correction into the DOM as
attributes before outerHTML is serialised, so the exported HTML carries the
ground truth verbatim; nothing needs to be replayed or interpreted.

Parsing approach: stdlib html.parser, not a regex. A naive
`data-speaker="..."` regex over one real export matched 375 times but only
156 of those were `.bubble` elements - the rest were the read-only
`.bubble-spk` chip nested inside each bubble (same attribute, decorative
copy) and string literals inside the export's own inlined JavaScript.
html.parser sees element structure, so it can select `<div class="bubble">`
specifically and read that element's own attributes, not a descendant's.

Turn boundaries come from Whisper's own segment timings (each bubble's
data-start/data-end), not from a hand-drawn reference: nobody re-drew turn
boundaries by hand, only speaker labels were corrected. See the RTTM header
this script writes for the DER-comparability caveat that follows from that.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class Bubble:
    start: float
    end: float
    speaker: str  # raw data-speaker id, e.g. "0"


class _TranscriptParser(HTMLParser):
    """
    Pulls two things out of an exported transcript HTML:

    - every `<div class="bubble" data-start=... data-end=... data-speaker=...>`
      (a bubble with no data-speaker is unattributed and is skipped, the same
      way core.diarization.assign_speakers leaves a word unattributed rather
      than guessing).
    - every speaker id -> human name mapping, read from
      `<div class="speaker-row" data-speaker="ID">...<input class="speaker-name"
      value="NAME">`. The mapping is NOT read off `.speaker-name` alone: that
      class also appears on the roster input with no id of its own attached,
      so the id has to come from the enclosing `.speaker-row`.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bubbles: list[Bubble] = []
        self.speaker_names: dict[str, str] = {}
        self._row_speaker_id: str | None = None
        self._row_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: v for k, v in attrs}
        classes = (attr_map.get("class") or "").split()

        if tag == "div" and "bubble" in classes:
            speaker = attr_map.get("data-speaker")
            start = attr_map.get("data-start")
            end = attr_map.get("data-end")
            if speaker is not None and start is not None and end is not None:
                self.bubbles.append(Bubble(start=float(start), end=float(end), speaker=speaker))
            return

        if tag == "div" and "speaker-row" in classes:
            self._row_speaker_id = attr_map.get("data-speaker")
            self._row_depth = 1
            return

        if self._row_speaker_id is not None:
            if tag == "div":
                self._row_depth += 1
            if tag == "input" and "speaker-name" in classes:
                value = attr_map.get("value")
                if value:
                    self.speaker_names[self._row_speaker_id] = value

    def handle_endtag(self, tag: str) -> None:
        if self._row_speaker_id is not None and tag == "div":
            self._row_depth -= 1
            if self._row_depth <= 0:
                self._row_speaker_id = None


def parse_transcript(html: str) -> tuple[list[Bubble], dict[str, str]]:
    """Parse exported transcript HTML into (bubbles in document order, speaker id -> name)."""
    parser = _TranscriptParser()
    parser.feed(html)
    return parser.bubbles, parser.speaker_names


@dataclass
class Turn:
    start: float
    end: float
    speaker: str  # resolved label - human name where known, else the raw id


def merge_turns(bubbles: list[Bubble], speaker_names: dict[str, str]) -> list[Turn]:
    """
    Merge consecutive same-speaker bubbles into one contiguous turn.

    RTTM turns are "one speaker talking, uninterrupted"; a Whisper segment
    boundary inside a run by the same speaker is not a turn boundary, and
    scoring 156 one-bubble turns instead of ~76 real ones would not change
    DER's total-overlap arithmetic, but it defeats the merge test any
    diarization RTTM consumer might reasonably do on this fixture, and turns
    that stop and restart on the same speaker every few seconds do not
    resemble what the reference actually looked like: two people talking,
    not fifty.
    """
    turns: list[Turn] = []
    for bubble in bubbles:
        raw_label = speaker_names.get(bubble.speaker, bubble.speaker)
        # RTTM's speaker field is one positional column among nine
        # (read_rttm splits each line on whitespace), so a human name with a
        # space in it - "יאיר שיזף" is two words - would shift every column
        # after it and corrupt parsing. Underscore-join rather than drop the
        # space, so the name stays recognisable in the file.
        label = "_".join(raw_label.split())
        if turns and turns[-1].speaker == label and bubble.start >= turns[-1].end - 1e-6:
            # Extend the open turn rather than start a new one. Bubbles are
            # assumed to arrive in chronological, non-overlapping order (as
            # the app itself renders them); a same-speaker bubble starting
            # before the previous one ends would mean an inconsistent export,
            # so it starts a fresh turn instead of silently rewinding one.
            turns[-1] = Turn(
                start=turns[-1].start, end=max(turns[-1].end, bubble.end), speaker=label
            )
        else:
            turns.append(Turn(start=bubble.start, end=bubble.end, speaker=label))
    return turns


def turns_to_rttm(turns: list[Turn], file_id: str) -> str:
    """Render turns as RTTM SPEAKER lines, matching read_rttm's expected column layout
    (see tests/eval/diarization_metrics.py:read_rttm and fixtures/diarization/ES2004a.rttm):

        SPEAKER <file-id> <channel> <start> <duration> <NA> <NA> <speaker> <NA> <NA>
    """
    lines = []
    for turn in turns:
        duration = turn.end - turn.start
        if duration <= 0:
            continue
        lines.append(
            f"SPEAKER {file_id} 1 {turn.start:.2f} {duration:.2f} <NA> <NA> {turn.speaker} <NA> <NA>"
        )
    return "\n".join(lines) + ("\n" if lines else "")


# read_rttm (tests/eval/diarization_metrics.py) only recognises rows whose
# first field is exactly "SPEAKER" and skips everything else, so a
# provenance/caveat header can be plain text lines rather than a "#"-comment
# RTTM has no syntax for.
_HEADER_TEMPLATE = """\
# RTTM generated by tests/eval/transcript_to_rttm.py from: {source}
# Speaker labels are hand-corrected by a human in this app's own transcript
# editor (see src/core/assets/js/56-export.js bakeFormState/
# paintBubbleOverride) and are the trustworthy part of this fixture.
# Turn BOUNDARIES come from Whisper's own segment timings, not from a
# hand-drawn reference - nobody re-drew turn edges by hand, only speaker
# labels were corrected. That inflates absolute DER slightly versus a
# hand-drawn reference (AMI's included), so A/B comparison BETWEEN
# diarization configurations on this fixture stays valid, but absolute DER
# here is not comparable to AMI's absolute DER.
"""


def build_rttm(html: str, file_id: str, source: str) -> str:
    bubbles, speaker_names = parse_transcript(html)
    if not bubbles:
        raise ValueError("No labelled bubbles found in transcript - is this an exported HTML?")
    turns = merge_turns(bubbles, speaker_names)
    return _HEADER_TEMPLATE.format(source=source) + turns_to_rttm(turns, file_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("transcript_html", help="Exported transcript HTML (hand-corrected)")
    parser.add_argument("output_rttm", help="Path to write the RTTM to")
    parser.add_argument(
        "--file-id",
        default=None,
        help="RTTM file-id field (default: the transcript filename's stem)",
    )
    args = parser.parse_args(argv)

    with open(args.transcript_html, encoding="utf-8") as handle:
        html = handle.read()

    import os

    # RTTM's file-id is a single positional field (read_rttm splits each line
    # on whitespace), so it cannot contain spaces - the exported filename
    # normally does, so the default replaces them rather than emitting a
    # multi-word field that would shift every column after it.
    default_id = os.path.splitext(os.path.basename(args.transcript_html))[0]
    file_id = args.file_id or "_".join(default_id.split())

    rttm = build_rttm(html, file_id=file_id, source=os.path.basename(args.transcript_html))

    with open(args.output_rttm, "w", encoding="utf-8") as handle:
        handle.write(rttm)

    bubble_count = rttm.count("\nSPEAKER") + (1 if rttm.startswith("SPEAKER") else 0)
    print(f"Wrote {bubble_count} turn(s) to {args.output_rttm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
