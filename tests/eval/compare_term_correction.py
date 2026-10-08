r"""
Measure the Hebrew term-correction pass on real recordings with human
transcripts: what it fixes, what it breaks, and what it leaves alone.

Dev-only, outside the pytest suite like the other compare_* harnesses: it
needs real audio and an ivrit-turbo transcription runs for minutes per file.

Two stages, so the expensive one runs once:

    python -m tests.eval.compare_term_correction transcribe
        Transcribes every fixture through the app's own path (audio_source.load,
        per-channel for true-stereo calls, the default model) and caches the
        segments - words, timings, confidences - as JSON in eval_output/.

    python -m tests.eval.compare_term_correction score --terms TERMS_FILE
        Loads the cache, runs core.hebrew_corrections.correct() over a copy,
        and scores before/after against the human transcript.

`score` uses whatever core/ is first on sys.path, so the same cached words can
be scored against an older commit's corrector:

    git worktree add ../old <commit>
    PYTHONPATH=../old/src python -m tests.eval.compare_term_correction score ...

What the numbers can and cannot say
-----------------------------------
The references are human-typed: the podcast's transcript.txt was corrected
by hand, the two calls' .docx transcripts were typed while listening. They
leave out backchannels, false starts and crosstalk, so ABSOLUTE WER is
inflated and is not a model-quality figure. Every variant here is scored on
the identical cached hypothesis, though, and the corrector only ever rewrites
a handful of words, so the DELTA is real.

The per-change verdicts are the point. Each rewritten word is located in a
word alignment against the reference and called:
    fixed   - the replacement is what the reference has there
    broke   - the ORIGINAL was what the reference had; the pass made it wrong
    neither - wrong before and still wrong (or no reference word to compare)
"broke" is the failure this pass most has to avoid: it puts a plausible real
word into a real sentence, and nobody notices without the audio.

What it has measured (2026-10-08, ivrit-turbo, one 23-term list frozen from
the references before any output was read, all three fixtures)
---------------------------------------------------------------------------
* The correction pass at the 0.55 gate: 0 fixed, 0 broke, after the
  known-word guard (main broke 1: ענבל for אבל). ivrit-turbo already wrote
  33/33 term mentions in the podcast right; on the calls the names it missed
  came out CONFIDENT (ציל for צליל at 0.96, יופי for יוסי at 0.98).
* Lowering the gate does not reach them safely: with no gate, 1 fixed for
  every ~5 broken, and even with the guard 1 real flag in 18.
* On Small (--model small), where mistakes are far more often uncertain
  (WER 8%/30%/44%), the same list and gate: 6 names fixed, 0 broke, 4
  already-wrong words turned into a different wrong name (ניתור -> נאור
  where the speaker said ניצור). main's corrector on the same words: 3
  fixed, 22 broke - אבל -> ענבל throughout. The known-word guard is the
  difference; the term list earns its place for anyone on a smaller model.
* --hotwords (the terms in faster-whisper's decoder prompt) is far worse:
  WER 2.9% -> 47% on the podcast, 10-13% -> 45-53% on the calls - repeated
  phrases, dropped sentences, digits spelled out. Do not ship it.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
if not any(p.rstrip("\\/").endswith("src") for p in sys.path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from tests.eval.hebrew_metrics import (  # noqa: E402
    character_error_rate,
    tokens,
    word_error_rate,
)

OUTPUT_DIR = "eval_output"
CACHE_DIR = os.path.join(OUTPUT_DIR, "term_correction")

# (name, audio, reference). References are read by _reference_text().
FIXTURES = [
    (
        "podcast",
        "mp3_test/podcast_transcript_test/podcast.mp4",
        "mp3_test/podcast_transcript_test/transcript.txt",
    ),
    (
        "call_avi_naor",
        "mp3_test/diarization_test/test#2/הקלטת שיחה אבי מורלי זוק_240829_150856.m4a",
        "mp3_test/diarization_test/test#2/אבי ונאור תמלול.docx",
    ),
    (
        "call_alon_naor",
        "mp3_test/diarization_test/test#3/הקלטת שיחה אלון קופרמן _ ביילה_240917_201900.m4a",
        "mp3_test/diarization_test/test#3/אלון קופרמן ונאור .docx",
    ),
]


def _cache_path(name: str, model: str, variant: str = "") -> str:
    label = f"{model}.{variant}" if variant else model
    return os.path.join(CACHE_DIR, f"{name}.{label}.segments.json")


def _reference_text(path: str) -> str:
    if path.endswith(".docx"):
        from tests.eval.docx_to_rttm import parse_docx

        _speakers, blocks = parse_docx(path)
        return "\n".join(text for block in blocks for _speaker, text in block.lines)
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()


# --- transcribe ---------------------------------------------------------------


def transcribe(model: str, only: list[str] | None, hotwords_file: str | None = None) -> None:
    import config
    from core import audio_source
    from core.transcriber import Transcriber
    from core.worker import _transcribe_per_channel

    os.makedirs(CACHE_DIR, exist_ok=True)
    transcriber = Transcriber(model_size=model, device="cpu", language=config.LANGUAGE)
    if not transcriber.load_model():
        raise SystemExit(f"could not load model {model}")

    variant = ""
    if hotwords_file:
        # Measure-before-building: inject faster-whisper's `hotwords` into the
        # loaded model's own transcribe() rather than threading a new option
        # through core/transcriber.py, so every other decode setting is
        # production's, untouched.
        import functools

        from core.hebrew_corrections import TermList

        hotwords = ", ".join(TermList.load(hotwords_file).terms)
        transcriber.model.transcribe = functools.partial(  # type: ignore[method-assign]
            transcriber.model.transcribe, hotwords=hotwords
        )
        variant = "hotwords"
        print(f"hotwords: {hotwords}")

    for name, audio, _reference in FIXTURES:
        if only and name not in only:
            continue
        out = _cache_path(name, model, variant)
        if os.path.exists(out):
            print(f"{name}: cached at {out}, skipping")
            continue
        print(f"{name}: transcribing {audio}", flush=True)

        channels, two_party = audio_source.load(audio)
        duration = len(channels[0]) / 16000 if channels else 0.0
        if two_party and channels:
            segments = _transcribe_per_channel(transcriber, channels, duration)
        else:
            mono = audio_source.to_mono(channels) if channels else None
            segments = transcriber.transcribe(
                mono if mono is not None else audio, total_duration_seconds=duration
            )
        if not segments:
            raise SystemExit(f"{name}: transcription produced nothing")

        # Per-channel output is channel 0 then channel 1; the reference is
        # chronological, and so is what the app renders.
        segments.sort(key=lambda s: s.start)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "audio": audio,
                    "model": model,
                    "two_party": two_party,
                    "segments": [asdict(s) for s in segments],
                },
                handle,
                ensure_ascii=False,
            )
        print(f"{name}: {len(segments)} segments -> {out}", flush=True)


# --- score --------------------------------------------------------------------


def _load_segments(name: str, model: str, variant: str = ""):
    from core.segments import Segment, Word

    with open(_cache_path(name, model, variant), encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        Segment(
            start=s["start"],
            end=s["end"],
            text=s["text"],
            speaker=s.get("speaker"),
            words=[Word(**w) for w in s["words"]],
        )
        for s in data["segments"]
    ]


def _token_stream(segments) -> tuple[list[str], list[tuple[int, int]]]:
    """Normalised hypothesis tokens, each tagged with (segment, word) index."""
    stream: list[str] = []
    owner: list[tuple[int, int]] = []
    for si, segment in enumerate(segments):
        for wi, word in enumerate(segment.words):
            for token in tokens(word.text):
                stream.append(token)
                owner.append((si, wi))
    return stream, owner


def _aligned_reference(ref: list[str], hyp: list[str]) -> list[str | None]:
    """For each hypothesis token, the reference token it aligns to (or None)."""
    aligned: list[str | None] = [None] * len(hyp)
    matcher = difflib.SequenceMatcher(a=hyp, b=ref, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                aligned[i1 + k] = ref[j1 + k]
    return aligned


def _verdicts(ref_tokens, before, after) -> list[dict]:
    hyp_before, owner_before = _token_stream(before)
    hyp_after, owner_after = _token_stream(after)
    ref_for_before = dict(zip(owner_before, _aligned_reference(ref_tokens, hyp_before)))
    ref_for_after = dict(zip(owner_after, _aligned_reference(ref_tokens, hyp_after)))

    results = []
    for si, (seg_b, seg_a) in enumerate(zip(before, after)):
        for wi, (w_b, w_a) in enumerate(zip(seg_b.words, seg_a.words)):
            if w_b.text == w_a.text:
                continue
            old = " ".join(tokens(w_b.text))
            new = " ".join(tokens(w_a.text))
            ref_new = ref_for_after.get((si, wi))
            ref_old = ref_for_before.get((si, wi))
            if ref_new is not None and ref_new == new:
                verdict = "fixed"
            elif ref_old is not None and ref_old == old:
                verdict = "broke"
            else:
                verdict = "neither"
            results.append(
                {
                    "time": round(w_b.start, 1),
                    "before": w_b.text.strip(),
                    "after": w_a.text.strip(),
                    "confidence": round(w_b.probability, 2),
                    "reference": ref_new or ref_old,
                    "verdict": verdict,
                }
            )
    return results


def _term_hits(terms: list[str], text: str) -> int:
    """How many times any term's normalised word sequence occurs in text."""
    words = tokens(text)
    joined = " " + " ".join(words) + " "
    hits = 0
    for term in terms:
        needle = " ".join(tokens(term))
        if not needle:
            continue
        # A term can carry clitics in running text (בקיסריה), so match it as a
        # word suffix after up to three prefix letters, not only as a whole word.
        for prefix in ("", "ו", "ב", "כ", "ל", "מ", "ש", "ה", "וב", "וה", "של", "מה", "שה", "וש"):
            hits += joined.count(" " + prefix + needle + " ")
    return hits


def score(
    model: str,
    terms_file: str,
    only: list[str] | None,
    out: str | None,
    threshold: float | None = None,
    variant: str = "",
) -> None:
    from core import hebrew_corrections
    from core.segments import plain_text

    terms = hebrew_corrections.TermList.load(terms_file)
    gate = hebrew_corrections.CONFIDENCE_THRESHOLD if threshold is None else threshold
    print(f"corrector: {os.path.abspath(hebrew_corrections.__file__)}")
    print(f"terms: {len(terms)} from {terms_file}")
    print(f"confidence gate: {gate}\n")

    report = {"corrector": hebrew_corrections.__file__, "terms": list(terms.terms), "files": {}}
    totals = {"fixed": 0, "broke": 0, "neither": 0}
    for name, _audio, reference in FIXTURES:
        if only and name not in only:
            continue
        if not os.path.exists(_cache_path(name, model, variant)):
            print(f"{name}: no cached transcription - run `transcribe` first")
            continue
        ref_text = _reference_text(reference)
        before = _load_segments(name, model, variant)
        after = copy.deepcopy(before)
        hebrew_corrections.correct(after, terms, gate)

        hyp_before, hyp_after = plain_text(before), plain_text(after)
        changes = _verdicts(tokens(ref_text), before, after)
        counts = {v: sum(c["verdict"] == v for c in changes) for v in totals}
        for v in totals:
            totals[v] += counts[v]

        row = {
            "wer_before": word_error_rate(ref_text, hyp_before),
            "wer_after": word_error_rate(ref_text, hyp_after),
            "cer_before": character_error_rate(ref_text, hyp_before),
            "cer_after": character_error_rate(ref_text, hyp_after),
            "term_hits_reference": _term_hits(list(terms.terms), ref_text),
            "term_hits_before": _term_hits(list(terms.terms), hyp_before),
            "term_hits_after": _term_hits(list(terms.terms), hyp_after),
            "changes": changes,
            **counts,
        }
        report["files"][name] = row

        print(f"== {name}")
        print(
            f"   WER {row['wer_before']:.4f} -> {row['wer_after']:.4f}   "
            f"CER {row['cer_before']:.4f} -> {row['cer_after']:.4f}"
        )
        print(
            f"   term occurrences: reference {row['term_hits_reference']}, "
            f"before {row['term_hits_before']}, after {row['term_hits_after']}"
        )
        print(
            f"   changes: {len(changes)}  fixed {counts['fixed']}  broke {counts['broke']}  "
            f"neither {counts['neither']}"
        )
        for c in changes:
            print(
                f"     {c['time']:>7}s  {c['before']!r} -> {c['after']!r}  "
                f"(p={c['confidence']}, ref={c['reference']!r})  {c['verdict']}"
            )
        print()

    print(f"TOTAL fixed {totals['fixed']}  broke {totals['broke']}  neither {totals['neither']}")
    report["totals"] = totals
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=1)
        print(f"wrote {out}")


def main(argv=None) -> int:
    import config

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("transcribe", "score"):
        p = sub.add_parser(command)
        p.add_argument("--model", default=config.DEFAULT_MODEL)
        p.add_argument("--only", nargs="*", help="fixture names to run")
        if command == "transcribe":
            p.add_argument(
                "--hotwords", help="term list file to pass to faster-whisper as hotwords"
            )
        else:
            p.add_argument(
                "--variant", default="", help='cached transcription to score, e.g. "hotwords"'
            )
        if command == "score":
            p.add_argument("--terms", required=True, help="term list file")
            p.add_argument("--out", help="also write the full report as JSON")
            p.add_argument(
                "--threshold",
                type=float,
                help="override the confidence gate, to measure what it costs",
            )
    args = parser.parse_args(argv)

    if args.command == "transcribe":
        transcribe(args.model, args.only, args.hotwords)
    else:
        score(args.model, args.terms, args.only, args.out, args.threshold, args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
