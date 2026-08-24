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
import itertools
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
            # Was formatting.render(result["_segments"]) - that function was
            # removed from core/formatting (which now only exposes
            # render_html, for the full transcript page) in a refactor that
            # never updated this harness. Pre-existing breakage, unrelated to
            # Stage 2 - fixed opportunistically here because it blocked
            # verifying the sweep end-to-end. result["text"] (plain_text of
            # the same segments, already computed in transcribe_once) is a
            # reasonable equivalent for a side-by-side reading comparison.
            handle.write(result["text"])
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


# =============================================================================
# Phase B: compute-settings sweep (compute_type / beam_size / cpu_threads /
# num_workers / device), on top of transcribe_once's single-shot model
# comparison above.
#
# Why this needed to exist and transcribe_once() didn't already cover it:
# transcribe_once() runs each MODEL once with no warm-up and reports one
# time.time() delta - fine for "is ivrit-turbo better than medium", useless
# for "does cpu_threads=4 actually help", because a single untimed-warm-up
# run on this machine is dominated by noise (OS scheduling, thermal/turbo
# ramp, page faults on first touch of the model's weights) that swamps a
# threading tweak's real effect. Phase B needs a repeatable number: a
# discarded warm-up run to get past first-call effects, N genuinely timed
# repeats of the SAME config, and the median (robust to a single outlier
# run) plus the spread (max-min, so "no measurable difference" can actually
# be said instead of eyeballed) - never a lone elapsed time presented as if
# it were reproducible.
# =============================================================================

def build_configs(
    models: List[str],
    compute_types: List[Optional[str]],
    beam_sizes: List[Optional[int]],
    cpu_threads_list: List[Optional[int]],
    num_workers_list: List[Optional[int]],
    devices: List[str],
) -> List[Dict]:
    """
    Cartesian product of every axis, once per model.

    Axis values of None mean "don't override - let Transcriber resolve its
    own default", which is exactly what Transcriber's own constructor already
    does for compute_type/beam_size/cpu_threads/num_workers (see
    core/transcriber.py's __init__). That symmetry is deliberate: the harness
    does not need a second copy of "what's the production default" - it just
    forwards None through unchanged, only device_needs a real string since
    Transcriber's device parameter isn't Optional.
    """
    configs = []
    for model in models:
        for compute_type, beam_size, cpu_threads, num_workers, device in itertools.product(
            compute_types, beam_sizes, cpu_threads_list, num_workers_list, devices
        ):
            configs.append({
                "model": model,
                "compute_type": compute_type,
                "beam_size": beam_size,
                "cpu_threads": cpu_threads,
                "num_workers": num_workers,
                "device": device,
            })
    return configs


def _config_label(cfg: Dict) -> str:
    parts = [cfg["model"], cfg["device"]]
    if cfg["compute_type"] is not None:
        parts.append(cfg["compute_type"])
    if cfg["beam_size"] is not None:
        parts.append(f"beam{cfg['beam_size']}")
    if cfg["cpu_threads"] is not None:
        parts.append(f"threads{cfg['cpu_threads']}")
    if cfg["num_workers"] is not None:
        parts.append(f"workers{cfg['num_workers']}")
    return "/".join(parts)


def run_config(cfg: Dict, samples, duration: float, warmup: bool, repeats: int) -> Dict:
    """
    Load once, optionally warm up once (untimed, discarded), then time
    `repeats` transcribe() calls of the SAME loaded model over the SAME
    samples. Returns median_seconds/spread_seconds alongside every individual
    run's time in "runs", so a caller can see the raw numbers behind the
    summary rather than trusting it blindly.
    """
    from speech_to_text.core.transcriber import Transcriber

    label = _config_label(cfg)
    print(f"\n=== {label} ===", flush=True)

    transcriber = Transcriber(
        model_size=cfg["model"],
        device=cfg["device"],
        compute_type=cfg["compute_type"],
        beam_size=cfg["beam_size"],
        cpu_threads=cfg["cpu_threads"],
        num_workers=cfg["num_workers"],
    )

    load_start = time.time()
    if not transcriber.load_model():
        return {**cfg, "label": label, "error": "model failed to load"}
    load_seconds = time.time() - load_start
    print(f"  loaded in {load_seconds:.1f}s (device={transcriber.device})", flush=True)

    if warmup:
        warmup_start = time.time()
        transcriber.transcribe(samples, total_duration_seconds=duration)
        print(f"  warm-up run: {time.time() - warmup_start:.1f}s (discarded)", flush=True)

    runs = []
    for i in range(max(repeats, 1)):
        start = time.time()
        segments = transcriber.transcribe(samples, total_duration_seconds=duration)
        elapsed = time.time() - start
        if segments is None:
            return {**cfg, "label": label, "error": "transcription failed"}
        runs.append(elapsed)
        print(f"  run {i + 1}/{repeats}: {elapsed:.1f}s", flush=True)

    median_seconds = statistics.median(runs)
    spread_seconds = (max(runs) - min(runs)) if len(runs) > 1 else 0.0
    result = {
        **cfg,
        "label": label,
        "load_seconds": round(load_seconds, 1),
        "runs": [round(r, 2) for r in runs],
        "median_seconds": round(median_seconds, 2),
        "spread_seconds": round(spread_seconds, 2),
        "median_realtime_factor": round(median_seconds / duration, 3) if duration else None,
    }
    print(
        f"  median {median_seconds:.1f}s (spread {spread_seconds:.1f}s over {len(runs)} runs)",
        flush=True,
    )
    return result


def print_sweep_table(results: List[Dict]) -> None:
    rows = [r for r in results if "error" not in r]
    if not rows:
        print("\nNo config produced a transcript.")
        return

    columns = [
        ("label", "config", ""),
        ("median_seconds", "median s", ""),
        ("spread_seconds", "spread s", ""),
        ("median_realtime_factor", "xRT", ""),
        ("load_seconds", "load s", ""),
    ]
    header = "  ".join(f"{label:>16}" for _, label, _ in columns)
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(f"{str(row.get(key, '')) + unit:>16}" for key, _, unit in columns))

    print("\nA difference smaller than either config's own spread is noise, not")
    print("a result - re-run before trusting it.")


def _sweep_requested(args) -> bool:
    """Any Phase B flag given at all -> take the sweep path instead of the
    original transcribe_once path. Keeps the pre-Stage-2 CLI producing
    exactly its old output when none of these are passed."""
    return bool(
        args.compute_types or args.beam_sizes or args.cpu_threads
        or args.num_workers or args.devices or args.repeats != 1 or args.warmup
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", help="Path to an audio file")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                        help=f"config.MODELS keys or raw repo ids (default: {DEFAULT_MODELS})")
    parser.add_argument("--seconds", type=float, default=0,
                        help="Only transcribe the first N seconds (0 = whole file)")
    parser.add_argument("--reference", help="Hand-corrected transcript, enables true WER/CER")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    # --- Phase B: compute-settings sweep. Any of these being passed switches
    # main() from the original one-run-per-model path to run_config()'s
    # warm-up + N-repeats + median/spread path - see _sweep_requested(). Left
    # unset, every one of these axes defaults to None ("don't override" -
    # Transcriber resolves its own production default), so passing none of
    # them changes nothing about the original --models behaviour.
    parser.add_argument("--compute-types", nargs="+", default=None,
                        help="e.g. int8 int8_float32 float32 (default: Transcriber's own default)")
    parser.add_argument("--beam-sizes", nargs="+", type=int, default=None,
                        help="e.g. 5 1 (default: config.BEAM_SIZE)")
    parser.add_argument("--cpu-threads", nargs="+", type=int, default=None,
                        help="e.g. 1 4 (default: ctranslate2's own choice)")
    parser.add_argument("--num-workers", nargs="+", type=int, default=None,
                        help="e.g. 1 2 (default: ctranslate2's own choice)")
    parser.add_argument("--devices", nargs="+", default=None,
                        help="e.g. cpu cuda (default: cpu)")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Timed runs per config; median+spread reported when > 1 (default: 1)")
    parser.add_argument("--warmup", action="store_true",
                        help="Run one untimed transcribe before timing, to exclude first-call effects")
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

    if _sweep_requested(args):
        configs = build_configs(
            models=args.models,
            compute_types=args.compute_types or [None],
            beam_sizes=args.beam_sizes or [None],
            cpu_threads_list=args.cpu_threads or [None],
            num_workers_list=args.num_workers or [None],
            devices=args.devices or ["cpu"],
        )
        results = []
        for cfg in configs:
            try:
                results.append(run_config(cfg, samples, duration, args.warmup, args.repeats))
            except Exception:
                logger.exception("Config %s failed", _config_label(cfg))
                results.append({**cfg, "label": _config_label(cfg), "error": "raised an exception"})

        os.makedirs(args.output_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.audio))[0]
        metrics_path = os.path.join(args.output_dir, f"{stem}_sweep.json")
        with open(metrics_path, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)

        print_sweep_table(results)
        print(f"\nSweep metrics: {metrics_path}")
        return 0

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
