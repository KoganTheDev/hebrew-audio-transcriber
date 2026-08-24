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

    # Timing sweep (Phase B). --language MUST match the audio - see
    # run_config()'s docstring for why a mismatch corrupts the TIMING, not
    # just the text, and cost a whole discarded sweep before this flag
    # existed:
    py -3.11 -m tests.eval.compare_models fixture.wav --language en \
        --cpu-threads 1 4 --repeats 5 --warmup
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

from speech_to_text import config

logger = logging.getLogger(__name__)

LOW_CONFIDENCE = 0.55  # matches core.hebrew_correct's gate
DEFAULT_MODELS = ["medium", "ivrit-turbo"]
OUTPUT_DIR = "eval_output"


def transcribe_once(model_size: str, samples, duration: float, language: Optional[str] = None) -> Dict:
    """
    Run one model over the audio and collect metrics alongside the text.

    language defaults to None here, which Transcriber resolves to
    config.LANGUAGE ("he") - the app's own default, so a bare invocation
    still benchmarks what the app actually does. Pass --language explicitly
    for audio that isn't Hebrew (see main()'s --language flag): decoding
    English audio as Hebrew doesn't just mistranscribe it, it changes the
    TIMING - see run_config()'s docstring for the mechanism and the 5.3x
    measured cost. This bit a real benchmark run before the flag existed.
    """
    from speech_to_text.core.segments import plain_text
    from speech_to_text.core.transcriber import Transcriber

    print(f"\n=== {model_size} ===", flush=True)
    transcriber = Transcriber(model_size=model_size, language=language or config.LANGUAGE)
    print(f"  repo: {transcriber.model_repo}, language: {transcriber.language}", flush=True)

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


# A config's own run-to-run noise, expressed as coefficient of variation
# (stdev / median) - unitless, so it's comparable across configs whose
# absolute times differ wildly (a 5s beam_size=1 run and a 100s float32 run
# can both legitimately have a 2s stdev; only the ratio says which one that
# actually threatens). Above this, print a loud warning rather than a
# quietly-wrong number: this threshold was set empirically on a CONTENDED
# machine (another process running the full pytest + jsdom suite
# concurrently) where two back-to-back runs of the identical config came
# back at 114.75s and 78.38s - a 46% spread on nothing but scheduler noise,
# an order of magnitude above what any of these axes could plausibly move
# the needle by. 0.15 is deliberately strict: it is meant to catch exactly
# that kind of contention, not to tolerate it.
NOISE_CV_THRESHOLD = 0.15

# Below this many timed repeats, spread/median are barely more than a guess -
# two samples can't distinguish real variance from a single unlucky run.
# _sweep_requested()'s caller prints a warning (not a hard error - a quick
# repeats=1 smoke test to check a config doesn't crash is still legitimate)
# when this isn't met.
MIN_TRUSTWORTHY_REPEATS = 5

# A realtime factor above this is not "a slow config", it's a sign something
# is actually wrong - the worst legitimate case measured on this machine
# (float32 on the CPU) is a fraction of this. The concrete failure mode this
# exists to catch: language mismatch (see run_config's docstring) measured
# at 5.3x slower AND noisier than the correct language on identical audio -
# a whole Phase B sweep was run and discarded because of it before this
# constant and --language existed. 1.0 is a loose tripwire on purpose - it
# only needs to catch "wildly worse than expected", not flag every merely
# slow config.
REALTIME_SANITY_FACTOR = 1.0


def _noise_hint(cv: float, realtime_factor: Optional[float]) -> Optional[str]:
    """
    One extra sentence for the NOISE WARNING machinery: a high cv or an
    unexpectedly bad realtime factor both have the same likely explanation
    on this harness's history (see run_config's docstring for the language-
    mismatch story), so name it explicitly rather than making a future
    reader rediscover it via a killed 2-hour run.
    """
    if cv > NOISE_CV_THRESHOLD or (realtime_factor is not None and realtime_factor > REALTIME_SANITY_FACTOR):
        return (
            "If this doesn't clear up with more repeats on a quiet machine, "
            "check --language: transcribing audio in the wrong language is a "
            "known cause of both bad speed AND noise (the temperature "
            "fallback ladder re-decodes with sampling), not just bad text."
        )
    return None


def run_config(
    cfg: Dict, samples, duration: float, warmup: bool, repeats: int,
    language: Optional[str] = None,
) -> Dict:
    """
    Load once, optionally warm up once (untimed, discarded), then time
    `repeats` transcribe() calls of the SAME loaded model over the SAME
    samples. Returns median_seconds/spread_seconds (min-max) and, once there
    are enough samples to make it meaningful, iqr_seconds (a spread measure
    robust to a single outlier run, which min-max is not) and cv (coefficient
    of variation - see NOISE_CV_THRESHOLD above) alongside every individual
    run's time in "runs", so a caller can see the raw numbers behind the
    summary rather than trusting it blindly.

    language defaults to None, resolved to config.LANGUAGE ("he") exactly
    like transcribe_once() - see that function's docstring. This matters a
    LOT more here than it does there: a language mismatch doesn't just
    mistranscribe, it changes the TIMING being measured. faster-whisper's
    compression-ratio and logprob thresholds reject garbage output and
    trigger the temperature fallback ladder (0.0, 0.2, 0.4, 0.6, 0.8, 1.0 -
    see core/worker.py:49-57, which already names this "the stretch users
    see as a frozen progress bar"), which re-decodes with SAMPLING. That's
    stochastic, so it shows up as run-to-run VARIANCE - exactly what this
    function's cv/spread reporting is supposed to catch - and it makes cost
    superlinear in clip length, since a longer clip has more windows that
    can fail. Measured on this machine: transcribing the (English) AMI
    fixture as language="he" cost 5.3x the wall-clock of language="en" on
    the identical audio, model and settings, and was more than twice as
    noisy (cv 9% vs 4%, 3 repeats). A whole Phase B sweep was run and
    discarded because of exactly this - don't remove this parameter's
    default-to-explicit plumbing without knowing that history.
    """
    from speech_to_text.core.transcriber import Transcriber

    label = _config_label(cfg)
    print(f"\n=== {label} ===", flush=True)

    transcriber = Transcriber(
        model_size=cfg["model"],
        device=cfg["device"],
        language=language or config.LANGUAGE,
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
    stdev_seconds = statistics.stdev(runs) if len(runs) > 1 else 0.0
    cv = (stdev_seconds / median_seconds) if median_seconds else 0.0
    # quantiles() needs at least 2 points and is only a meaningful "middle
    # 50%" with several - restricted to len>=4 rather than reusing the
    # min-max threshold above so a 2-3 repeat run doesn't get a fake IQR
    # that's actually just min-max again wearing a different name.
    iqr_seconds = None
    if len(runs) >= 4:
        q1, _, q3 = statistics.quantiles(runs, n=4)
        iqr_seconds = q3 - q1

    median_realtime_factor = round(median_seconds / duration, 3) if duration else None
    result = {
        **cfg,
        "label": label,
        "load_seconds": round(load_seconds, 1),
        "runs": [round(r, 2) for r in runs],
        "median_seconds": round(median_seconds, 2),
        "spread_seconds": round(spread_seconds, 2),
        "iqr_seconds": round(iqr_seconds, 2) if iqr_seconds is not None else None,
        "cv": round(cv, 3),
        "median_realtime_factor": median_realtime_factor,
    }
    print(
        f"  median {median_seconds:.1f}s (spread {spread_seconds:.1f}s, "
        f"cv {cv:.0%} over {len(runs)} runs)",
        flush=True,
    )
    if cv > NOISE_CV_THRESHOLD:
        print(
            f"  NOISE WARNING: cv={cv:.0%} exceeds {NOISE_CV_THRESHOLD:.0%} - this "
            f"config's own run-to-run spread is too large to trust as a result. "
            f"Re-run on a quiet machine or with more repeats before comparing it "
            f"to anything.",
            flush=True,
        )
    hint = _noise_hint(cv, median_realtime_factor)
    if hint:
        print(f"  {hint}", flush=True)
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
        ("iqr_seconds", "IQR s", ""),
        ("cv", "cv", ""),
        ("median_realtime_factor", "xRT", ""),
        ("load_seconds", "load s", ""),
    ]
    header = "  ".join(f"{label:>16}" for _, label, _ in columns)
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(f"{str(row.get(key, '')) + unit:>16}" for key, _, unit in columns))

    noisy = [r["label"] for r in rows if r.get("cv", 0) > NOISE_CV_THRESHOLD]
    if noisy:
        print(
            f"\nNOISE WARNING: {len(noisy)} config(s) exceeded a {NOISE_CV_THRESHOLD:.0%} "
            f"coefficient of variation - their own run-to-run spread is too large to "
            f"treat as a result: {', '.join(noisy)}"
        )

    any_hint = any(
        _noise_hint(r.get("cv", 0), r.get("median_realtime_factor")) for r in rows
    )
    if any_hint:
        print(
            "If this doesn't clear up with more repeats on a quiet machine, check "
            "--language: transcribing audio in the wrong language is a known cause "
            "of both bad speed AND noise, not just bad text (see run_config's "
            "docstring - it cost a whole discarded sweep before this flag existed)."
        )

    print("\nA difference smaller than either config's own spread is noise, not")
    print("a result - re-run before trusting it.")


def _sweep_requested(args) -> bool:
    """Any Phase B flag given at all -> take the sweep path instead of the
    original transcribe_once path. Keeps the pre-Stage-2 CLI producing
    exactly its old output when none of these are passed. args.repeats is
    None (not 1) when the user never passed --repeats - see main()'s
    argparse setup - specifically so a bare `--repeats` default cannot, on
    its own, flip an old-style invocation onto the sweep path."""
    return bool(
        args.compute_types or args.beam_sizes or args.cpu_threads
        or args.num_workers or args.devices or args.repeats is not None or args.warmup
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
    # Defaults to None -> config.LANGUAGE ("he"), the app's own default, so a
    # bare invocation still benchmarks what the app actually does. MUST be
    # passed explicitly for non-Hebrew audio (e.g. --language en for the AMI
    # fixture): decoding audio in the wrong language doesn't just produce bad
    # text, it changes the TIMING being measured - see run_config()'s
    # docstring for the mechanism and the 5.3x measured cost. A whole Phase B
    # sweep was run and discarded because of exactly this before this flag
    # existed - do not remove it or let it silently default to the wrong
    # language for a non-Hebrew fixture.
    parser.add_argument("--language", default=None,
                        help="faster-whisper language code (default: config.LANGUAGE, i.e. 'he'). "
                             "Wrong language = wrong TIMING, not just wrong text - see run_config().")
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
    parser.add_argument("--repeats", type=int, default=None,
                        help=f"Timed runs per config (default: {MIN_TRUSTWORTHY_REPEATS} once the sweep "
                             f"path is taken at all - see MIN_TRUSTWORTHY_REPEATS). Fewer than "
                             f"{MIN_TRUSTWORTHY_REPEATS}, spread/cv are barely more than a guess.")
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
        # Default to MIN_TRUSTWORTHY_REPEATS once the sweep path is taken at
        # all, rather than argparse's own default=None - a bare `--warmup`
        # or `--cpu-threads 4` with no explicit --repeats should still get a
        # trustworthy number of samples, not a single untimed-adjacent run.
        # An explicit --repeats below that is still honoured (a quick "does
        # this config even run" smoke test is legitimate) but warned about.
        repeats = args.repeats if args.repeats is not None else MIN_TRUSTWORTHY_REPEATS
        if repeats < MIN_TRUSTWORTHY_REPEATS:
            print(
                f"\nWARNING: --repeats {repeats} is below the "
                f"{MIN_TRUSTWORTHY_REPEATS} this harness considers trustworthy - "
                f"fine for a quick smoke test, but don't compare configs on the "
                f"result. Use --repeats {MIN_TRUSTWORTHY_REPEATS} or more.",
                flush=True,
            )
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
                results.append(run_config(cfg, samples, duration, args.warmup, repeats, args.language))
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
            result = transcribe_once(model, samples, duration, args.language)
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
