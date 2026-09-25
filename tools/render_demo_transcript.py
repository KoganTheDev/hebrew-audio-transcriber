"""Render a demo transcript page for the README, from invented dialogue.

WHY THIS EXISTS, AND WHY IT DOES NOT TOUCH REAL AUDIO: the README needs to
show what the finished transcript actually looks like, and every real
transcript this app produces is somebody's private recording. Screenshotting
one would publish their words. So the dialogue below is written for this
file - a fictional two-person conversation about scheduling a meeting - and
handed straight to render_html() without any transcription running at all.

Nothing here reads an audio file, a model, or any path under mp3_test/.

Timings are invented too, but plausibly shaped: word spans are contiguous
inside a sentence and leave realistic gaps between turns, so the timestamps
and the per-sentence word timings behave like a real render's would. That
matters because the page is a working editor in the screenshot - a split or
a playback click has to look right, not just the text.

    py -3.11 tools/render_demo_transcript.py [--out PATH] [--lang he|en]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.formatting import render_html  # noqa: E402
from core.segments import Segment, TranscriptDocument, Word  # noqa: E402
from gui import i18n  # noqa: E402

# (speaker, text, start, end). Invented dialogue - two colleagues agreeing a
# meeting time. Deliberately ordinary: the screenshot should show the app,
# not the content, and anything quotable would distract from that.
DIALOGUE: list[tuple[int, str, float, float]] = [
    (0, "בוקר טוב, רציתי לדבר איתך על הפגישה של יום רביעי.", 0.0, 4.2),
    (1, "בוקר טוב. כן, בטח. מה השאלה?", 4.9, 7.6),
    (0, "האם נוח לך להזיז אותה לשעה עשר? יש לי משהו שנסגר בתשע וחצי.", 8.1, 13.4),
    (1, "עשר זה בסדר גמור מבחינתי.", 14.0, 16.3),
    (1, "רק תוודא שגם דנה פנויה, היא הייתה צריכה להציג את הנתונים.", 16.3, 21.0),
    (0, "אני אשלח לה הודעה עכשיו ואעדכן אותך.", 21.6, 25.1),
    (0, "אם היא לא יכולה, נדחה לחמישי באותה שעה.", 25.1, 29.0),
    (1, "מצוין. תודה רבה.", 29.8, 31.5),
]


def _words(text: str, start: float, end: float) -> list[Word]:
    """Spread a sentence's words evenly across its own span.

    Even spacing rather than random jitter: a real render's word timings come
    from the model, and nothing in a screenshot can show the difference, but
    an even split keeps every boundary inside the sentence and monotonic,
    which is what the page's split and playback paths actually rely on.
    """
    parts = text.split(" ")
    if not parts:
        return []
    step = (end - start) / len(parts)
    return [
        Word(
            start=round(start + i * step, 2),
            end=round(start + (i + 1) * step, 2),
            text=(" " if i else "") + part,
            # One deliberately-uncertain word, so the README screenshot can
            # show the low-confidence highlighting the app is partly for.
            probability=0.42 if part == "דנה" else 0.97,
        )
        for i, part in enumerate(parts)
    ]


def build_document() -> TranscriptDocument:
    segments = [
        Segment(start=start, end=end, text=text, speaker=speaker, words=_words(text, start, end))
        for speaker, text, start, end in DIALOGUE
    ]
    return TranscriptDocument(source_name="demo-meeting.m4a", segments=segments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/demo-transcript.html")
    parser.add_argument("--lang", default="he", choices=["he", "en"])
    args = parser.parse_args()

    i18n.set_language(args.lang)
    html = render_html(
        [build_document()],
        speaker_label=i18n.t("speaker_label"),
        timestamps=True,
        title="demo-meeting",
        ui_strings=i18n.document_strings(),
        # Pinned so regenerating for a fresh screenshot does not mint a new
        # localStorage identity or reshuffle the backdrop.
        doc_id="readme-demo-transcript",
        vista="vista-03.webp",
    )
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"wrote {args.out} ({len(html) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
