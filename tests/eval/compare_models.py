"""
Compare transcription models on real audio.

Dev-only, deliberately outside the pytest suite: it needs real recordings and
takes minutes to hours, neither of which belongs in a unit test run.

What this can and cannot tell you
---------------------------------
Without a reference transcript there is no such thing as an accuracy
percentage, and anything claiming otherwise would be invented. So this reports
two different kinds of thing, kept clearly apart:

  * Proxies (always available). Mean word confidence, share of low-confidence
    words, compression ratio, repeated-segment count, speed. These correlate
    with quality but do not measure it - a confidently wrong model scores well.
  * True error rates (only with --reference). Real WER/CER against a
    hand-corrected transcript, with Hebrew-appropriate normalisation.

The side-by-side transcripts it writes are the actual deliverable for a
question like "is the Hebrew model better", because that judgement needs a
Hebrew speaker reading them.

Usage:
    py -3.11 -m tests.eval.compare_models mp4a_test/test.m4a
    py -3.11 -m tests.eval.compare_models mp4a_test/test.m4a --models medium ivrit-turbo
    py -3.11 -m tests.eval.compare_models mp4a_test/test.m4a --seconds 300
    py -3.11 -m tests.eval.compare_models mp4a_test/test.m4a --reference ref.txt
"""

import argparse
import json
import logging
import os
import statistics
import sys
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LOW_CONFIDENCE = 0.55  # matches core.hebrew_correct's gate
DEFAULT_MODELS = ["medium", "ivrit-turbo"]
OUTPUT_DIR = "eval_output"


def transcribe_once(model_size: str, samples, duration: float) -> Dict:
    """Run one model over the audio and collect metrics alongside the text."""
    from speech_to_text.core.segments import plain_text
    from speech_to_text.core.transcriber import Transcriber

    print(f"\n=== {model_size} ===", flush=True)
    transcriber = Transcriber(model_size=model_size)
    print(f"  repo: {transcriber.model_repo}", flush=True)

    load_start = time.time()
    if not transcriber.load_model():
        return {"model": model_size, "error": "model failed to load"}
    load_seconds = time.time() - load_start
    print(f"  loaded in {load_seconds:.1f}s", flush=True)

    start = time.time()
    segments = transcriber.transcribe(samples, total_duration_seconds=duration)
    elapsed = time.time() - start

    if segments is None:
        return {"model": model_size, "error": "transcription failed"}

    probabilities = [w.probability for s in segments for w in s.words]
    texts = [s.text.strip() for s in segments]
    repeats = sum(1 for a, b in zip(texts, texts[1:]) if a and a == b)

    text = plain_text(segments)
    result = {
        "model": model_size,
        "repo": transcriber.model_repo,
        "load_seconds": round(load_seconds, 1),
        "transcribe_seconds": round(elapsed, 1),
        "realtime_factor": round(elapsed / duration, 3) if duration else None,
        "segments": len(segments),
        "words": len(probabilities),
        "characters": len(text),
        "mean_word_confidence": (
            round(statistics.fmean(probabilities), 4) if probabilities else None
        ),
        "median_word_confidence": (
            round(statistics.median(probabilities), 4) if probabilities else None
        ),
        "low_confidence_share": (
            round(sum(1 for p in probabilities if p < LOW_CONFIDENCE) / len(probabilities), 4)
            if probabilities else None
        ),
        "repeated_segments": repeats,
        "text": text,
        "_segments": segments,
    }
    print(
        f"  {elapsed:.0f}s ({result['realtime_factor']}x realtime), "
        f"{len(segments)} segments, mean confidence {result['mean_word_confidence']}",
        flush=True,
    )
    return result


def write_side_by_side(results: List[Dict], path: str) -> None:
    """
    Write the transcripts one after another for manual reading.

    Sequential rather than column-aligned on purpose: Hebrew is right-to-left,
    and forcing RTL text into fixed-width side-by-side columns in a text file
    produces something less readable than just reading each in turn.
    """
    from speech_to_text.core import formatting

    with open(path, "w", encoding="utf-8") as handle:
        for result in results:
            if "error" in result:
                handle.write(f"### {result['model']}: {result['error']}\n\n")
                continue
            handle.write(f"{'=' * 70}\n")
            handle.write(f"### {result['model']}  ({result['repo']})\n")
            handle.write(
                f"### {result['transcribe_seconds']}s, "
                f"{result['realtime_factor']}x realtime, "
                f"mean confidence {result['mean_word_confidence']}\n"
            )
            handle.write(f"{'=' * 70}\n\n")
            handle.write(formatting.render(result["_segments"]))
            handle.write("\n\n\n")


def print_table(results: List[Dict], reference: Optional[str]) -> None:
    rows = [r for r in results if "error" not in r]
    if not rows:
        print("\nNo model produced a transcript.")
        return

    columns = [
        ("model", "model", ""),
        ("transcribe_seconds", "time", "s"),
        ("realtime_factor", "xRT", ""),
        ("segments", "segs", ""),
        ("words", "words", ""),
        ("mean_word_confidence", "conf", ""),
        ("low_confidence_share", "low", ""),
        ("repeated_segments", "repeat", ""),
    ]
    if reference is not None:
        columns += [("wer", "WER", ""), ("cer", "CER", "")]

    header = "  ".join(f"{label:>12}" for _, label, _ in columns)
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(f"{str(row.get(key, '')) + unit:>12}" for key, _, unit in columns))

    print("\nProxy metrics (conf/low/repeat) correlate with quality but do not")
    print("measure it - a confidently wrong model still scores well. Read the")
    print("side-by-side transcript to judge accuracy.")
    if reference is None:
        print("Supply --reference <file> with a hand-corrected transcript for a real WER.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", help="Path to an audio file")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                        help=f"config.MODELS keys or raw repo ids (default: {DEFAULT_MODELS})")
    parser.add_argument("--seconds", type=float, default=0,
                        help="Only transcribe the first N seconds (0 = whole file)")
    parser.add_argument("--reference", help="Hand-corrected transcript, enables true WER/CER")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from speech_to_text.core import audio_source

    print(f"Decoding {args.audio} ...", flush=True)
    channels, two_party = audio_source.load(args.audio)
    if channels is None:
        print("Could not decode audio.", file=sys.stderr)
        return 1

    samples = audio_source.to_mono(channels)
    if args.seconds:
        samples = samples[: int(args.seconds * audio_source.SAMPLE_RATE)]
    duration = len(samples) / audio_source.SAMPLE_RATE
    print(f"  {duration / 60:.1f} min, {len(channels)} channel(s), "
          f"one-speaker-per-channel: {two_party}", flush=True)

    reference = None
    if args.reference:
        with open(args.reference, encoding="utf-8") as handle:
            reference = handle.read()

    results = []
    for model in args.models:
        try:
            result = transcribe_once(model, samples, duration)
        except Exception as e:
            logger.exception("Model %s failed", model)
            result = {"model": model, "error": str(e)}
        if reference is not None and "error" not in result:
            from tests.eval.hebrew_metrics import character_error_rate, word_error_rate
            result["wer"] = round(word_error_rate(reference, result["text"]), 4)
            result["cer"] = round(character_error_rate(reference, result["text"]), 4)
        results.append(result)

    os.makedirs(args.output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.audio))[0]

    comparison = os.path.join(args.output_dir, f"{stem}_comparison.txt")
    write_side_by_side(results, comparison)

    metrics_path = os.path.join(args.output_dir, f"{stem}_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as handle:
        json.dump(
            [{k: v for k, v in r.items() if not k.startswith("_") and k != "text"}
             for r in results],
            handle, ensure_ascii=False, indent=2,
        )

    print_table(results, reference)
    print(f"\nSide-by-side transcripts: {comparison}")
    print(f"Metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
