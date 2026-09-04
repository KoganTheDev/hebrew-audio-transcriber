"""
Compare diarization accuracy (DER) on real audio with ground truth, in two
different modes that score two different stages of the pipeline.

Dev-only, deliberately outside the pytest suite, mirroring
tests.eval.compare_models: this needs real audio and a real reference
transcript and can take minutes, neither of which belongs in a unit test run.

Two modes, because one number cannot answer both questions
-------------------------------------------------------------
--mode span (the default): scores sherpa-onnx's raw speaker spans against the
  reference RTTM. This is the segmentation + clustering stage only - it knows
  nothing about Whisper segments or words, so it CANNOT see whether
  core.diarization.assign_speakers' word-boundary splitting helped. What it
  can measure is core/diarization.py's min_duration_on/min_duration_off
  change (see "before/after" below).

--mode e2e: scores what a user actually sees - transcript segments with a
  speaker label attached. This transcribes the fixture audio with the real
  Transcriber, runs diarize() once to get spans, then produces two
  hypotheses from those same segments and spans:
    - "before": a frozen local copy of the old whole-segment majority-vote
      assign_speakers (one label per transcribed segment, never split).
    - "after": the real, current core.diarization.assign_speakers (splits a
      segment at the word boundary where the speaker changes).
  This is the only mode that can show the splitting change moving DER, since
  that change only affects how a Whisper segment's words get labelled, not
  what spans sherpa-onnx emits.

--mode both runs both.

"before" and "after" in --mode span specifically
--------------------------------------------------
core/diarization.py:diarize() used to build its sherpa-onnx config without
ever passing min_duration_on / min_duration_off, so sherpa-onnx's own library
defaults (0.3s / 0.5s) applied silently. The fix in this same change makes
those two knobs named constants in config.py and passes them explicitly -
and, per the plan this was built from, keeps them equal to sherpa-onnx's
existing defaults so that change alone is behaviour-neutral. "Before" is a
small local re-implementation of the pre-change call (no min_duration_on/off
passed at all); "after" is the real, current diarization.diarize(). Both
should therefore score identically today - this mode exists to demonstrate
that empirically, AND to give any future change to those two constants (e.g.
tuning min_duration_on down to recover very short utterances) a real
before/after number to be judged by.

English audio, on purpose
--------------------------
AMI is English, and DER (in --mode span) scores the segmentation and
clustering stages, which are language-independent - the embedding model in
use is VoxCeleb-trained regardless of what language is spoken (see
core/diarization.py's module docstring). --mode e2e additionally runs real
transcription, and for that stage the language is NOT language-independent:
config.LANGUAGE defaults to Hebrew, and a Hebrew-tuned model (the app's own
default, ivrit-turbo) forcing Hebrew decoding onto English speech would
produce garbage word boundaries, which would make the word-level splitting
measurement meaningless rather than merely noisy. --mode e2e therefore
defaults --language to "en" and --model to "medium" (a general multilingual
model, not the Hebrew-tuned default) for this fixture specifically. Neither
default changes anywhere else in the app - config.LANGUAGE and
config.DEFAULT_MODEL are untouched.

What --mode span does NOT measure
------------------------------------
The Hebrew-specific half of this change - splitting a Whisper segment at a
word boundary where the speaker changes (core.diarization.assign_speakers) -
is not exercised by --mode span at all, for the reason above. It is exercised
by --mode e2e, and is also covered by unit tests on hand-built Segment/Word
objects in tests/test_diarization.py, exactly as tests/eval/hebrew_metrics.py's
normalisation is unit tested rather than scored against this fixture.

Fixture layout this script expects
-----------------------------------
Neither file is downloaded by this script or anywhere else in this project -
both must be placed by hand (or by a separate, explicitly-approved step; see
the plan this was built from, section 1.6, for the two source URLs). Expected
paths, relative to the repo root:

    tests/eval/fixtures/diarization/ES2004a.Mix-Headset.wav
    tests/eval/fixtures/diarization/ES2004a.rttm

Both --audio and --rttm can override these. When either file is missing,
this script prints exactly which path it looked for and exits 0 (a skip, not
a failure) - the same shape as a missing optional fixture anywhere else in
this project.

Usage:
    py -3.11 -m tests.eval.compare_diarization
    py -3.11 -m tests.eval.compare_diarization --mode e2e
    py -3.11 -m tests.eval.compare_diarization --mode both --seconds 300
    py -3.11 -m tests.eval.compare_diarization --audio path.wav --rttm path.rttm
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import List, Tuple

logger = logging.getLogger(__name__)

FIXTURE_DIR = os.path.join("tests", "eval", "fixtures", "diarization")
DEFAULT_AUDIO = os.path.join(FIXTURE_DIR, "ES2004a.Mix-Headset.wav")
DEFAULT_RTTM = os.path.join(FIXTURE_DIR, "ES2004a.rttm")
OUTPUT_DIR = "eval_output"

# AMI's ES2004a is a 4-person meeting. -1 would ask sherpa-onnx to infer the
# count instead, which is a strictly harder problem and not what this
# script is trying to measure (see the module docstring: min_duration_on/off
# and word-boundary splitting are the things under test, not
# clustering-without-a-known-count).
DEFAULT_NUM_SPEAKERS = 4

# See "English audio, on purpose" in the module docstring: AMI is English,
# and the app's own default model/language pair (ivrit-turbo, Hebrew) is
# actively wrong for it. These are eval-only defaults - nothing in
# config.py changes.
DEFAULT_E2E_MODEL = "medium"
DEFAULT_E2E_LANGUAGE = "en"


def _spans_to_turns(spans) -> List[Tuple[float, float, str]]:
    """core.diarization.SpeakerSpan list -> diarization_metrics.Turn list."""
    return [(span.start, span.end, str(span.speaker)) for span in spans]


def _segments_to_turns(segments) -> List[Tuple[float, float, str]]:
    """
    core.segments.Segment list -> diarization_metrics.Turn list.

    A segment assign_speakers left unattributed (speaker is None) is
    correctly absent from the hypothesis, not scored as speaker "None" -
    that time simply contributes to missed_speech instead, the same as if
    diarization had said nothing about it at all.
    """
    return [(s.start, s.end, str(s.speaker)) for s in segments if s.speaker is not None]


def _diarize_before(samples, sample_rate: int, num_speakers: int):
    """
    The pre-change diarize() call: no min_duration_on/off passed, so
    sherpa-onnx's own defaults silently applied. Kept here, not in
    core/diarization.py, purely so --mode span has something to diff the
    current behaviour against - see the module docstring for why that
    comparison is expected to be a no-op today.
    """
    import sherpa_onnx

    from speech_to_text.core import diarization

    # Named diar_config, not config, on principle - see core/diarization.py's
    # own comment on this exact naming trap: this file has no module-level
    # `config` import to collide with, but a local named `config` inside a
    # function that also touches sherpa-onnx config objects is precisely the
    # shape that bug had, and matching diarize()'s naming here means a copy
    # into core/ later (if this ever needs to move) can't reintroduce it.
    diar_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=diarization._SEGMENTATION_MODEL
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=diarization._EMBEDDING_MODEL),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers if num_speakers and num_speakers > 0 else -1,
            threshold=0.5,
        ),
        # Deliberately NOT passed - reproducing the exact pre-change call.
    )
    if not diar_config.validate():
        raise diarization.DiarizationUnavailable("Invalid diarization configuration")

    engine = sherpa_onnx.OfflineSpeakerDiarization(diar_config)
    if sample_rate != engine.sample_rate:
        raise diarization.DiarizationUnavailable(
            f"Diarization needs {engine.sample_rate} Hz audio, got {sample_rate}"
        )

    result = engine.process(samples)
    return [
        diarization.SpeakerSpan(start=s.start, end=s.end, speaker=s.speaker)
        for s in result.sort_by_start_time()
    ]


def _assign_speakers_before_e2e(segments, spans) -> List[Tuple[float, float, str]]:
    """
    Frozen copy of the PRE-CHANGE assign_speakers: one label per whole
    segment, decided by majority vote of its words' best-overlap speaker.
    Never splits a segment, unlike the current core.diarization.assign_speakers.

    Deliberately reimplemented here rather than imported: the real function
    in core/diarization.py has already been replaced by the splitting
    version, so this is the only place this behaviour still exists, and it
    exists ONLY to give --mode e2e something to compare the new behaviour
    against. It must never be reintroduced into core/ - see this change's
    plan (goofy-jumping-pine.md, section 1.5) for why splitting replaced it.
    """
    from speech_to_text.core.diarization import _best_speaker

    turns: List[Tuple[float, float, str]] = []
    for segment in segments:
        votes = {}
        for word in segment.words:
            speaker = _best_speaker(spans, word.start, word.end)
            if speaker is not None:
                votes[speaker] = votes.get(speaker, 0) + 1

        if votes:
            speaker = max(votes.items(), key=lambda kv: kv[1])[0]
        else:
            speaker = _best_speaker(spans, segment.start, segment.end)

        if speaker is not None:
            turns.append((segment.start, segment.end, str(speaker)))
    return turns


def _report_der(label: str, result, prefix: str = "  ") -> dict:
    print(f"{prefix}{label}: {result}", flush=True)
    return {
        "label": label,
        "der": round(result.der, 4),
        "missed_speech": round(result.missed_speech, 2),
        "false_alarm": round(result.false_alarm, 2),
        "confusion": round(result.confusion, 2),
        "total_ref_speech": round(result.total_ref_speech, 2),
    }


def run_span_mode(samples, sample_rate: int, num_speakers: int, reference) -> dict:
    """Score sherpa-onnx's raw spans against the reference - see the module docstring."""
    from speech_to_text.core import diarization
    from tests.eval.diarization_metrics import compute_der

    print("\n=== span-level: before (sherpa-onnx defaults, not passed explicitly) ===", flush=True)
    start = time.time()
    before_spans = _diarize_before(samples, sample_rate, num_speakers)
    before_elapsed = time.time() - start
    print(f"  {len(before_spans)} span(s) in {before_elapsed:.1f}s", flush=True)
    before_result = compute_der(reference, _spans_to_turns(before_spans))
    before_report = _report_der("before", before_result)
    before_report["spans"] = len(before_spans)
    before_report["diarize_seconds"] = round(before_elapsed, 1)

    print(
        "\n=== span-level: after (config.DIARIZATION_MIN_DURATION_ON/OFF, explicit) ===", flush=True
    )
    start = time.time()
    after_spans = diarization.diarize(samples, sample_rate=sample_rate, num_speakers=num_speakers)
    after_elapsed = time.time() - start
    print(f"  {len(after_spans)} span(s) in {after_elapsed:.1f}s", flush=True)
    after_result = compute_der(reference, _spans_to_turns(after_spans))
    after_report = _report_der("after", after_result)
    after_report["spans"] = len(after_spans)
    after_report["diarize_seconds"] = round(after_elapsed, 1)

    before_der, after_der = before_report["der"], after_report["der"]
    print(f"\nspan-level DER before: {before_der}")
    print(f"span-level DER after:  {after_der}")
    if before_der == after_der:
        print("Identical, as expected - config.py's values were deliberately kept equal to")
        print("sherpa-onnx's own defaults, so this change alone is behaviour-neutral.")

    return {"mode": "span", "before": before_report, "after": after_report}


def run_e2e_mode(
    samples,
    sample_rate: int,
    num_speakers: int,
    duration: float,
    model: str,
    language: str,
    reference,
    no_vad: bool = False,
) -> dict:
    """
    Score labelled transcript segments - what a user actually sees - against
    the reference. See the module docstring's "Two modes" section for why
    this is the only mode that can show the word-boundary splitting change.
    """
    # transcriber.transcribe() reads config.VAD_FILTER at call time, so a
    # module-level override here reaches it without threading a new argument
    # through production code for a dev-only measurement. Restored in the
    # finally below so a --mode both run does not leak the override into
    # anything measured after it.
    from speech_to_text import config as app_config
    from speech_to_text.core import diarization
    from speech_to_text.core.transcriber import Transcriber
    from tests.eval.diarization_metrics import compute_der

    previous_vad = app_config.VAD_FILTER
    if no_vad:
        app_config.VAD_FILTER = False

    print(
        f"\n=== end-to-end: transcribing with model={model!r} language={language!r}"
        f" vad_filter={app_config.VAD_FILTER} ===",
        flush=True,
    )
    transcriber = Transcriber(model_size=model, language=language)
    load_start = time.time()
    if not transcriber.load_model():
        raise RuntimeError(f"Model {model!r} failed to load")
    print(f"  loaded in {time.time() - load_start:.1f}s", flush=True)

    transcribe_start = time.time()
    try:
        segments = transcriber.transcribe(samples, total_duration_seconds=duration)
    finally:
        app_config.VAD_FILTER = previous_vad
    transcribe_elapsed = time.time() - transcribe_start
    if segments is None:
        raise RuntimeError("Transcription failed")
    print(f"  {len(segments)} transcribed segment(s) in {transcribe_elapsed:.1f}s", flush=True)

    print("\n=== end-to-end: diarizing (spans shared by both hypotheses) ===", flush=True)
    diarize_start = time.time()
    spans = diarization.diarize(samples, sample_rate=sample_rate, num_speakers=num_speakers)
    print(f"  {len(spans)} span(s) in {time.time() - diarize_start:.1f}s", flush=True)

    # Both hypotheses read segment.words/.start/.end only, never mutate them,
    # so the same `segments` list can feed both without cross-contamination.
    # (assign_speakers below DOES set .speaker on unsplit segments in place,
    # but that happens after _assign_speakers_before_e2e has already copied
    # out everything it needs into plain tuples.)
    print("\n=== end-to-end: before (old whole-segment majority vote) ===", flush=True)
    before_turns = _assign_speakers_before_e2e(segments, spans)
    before_result = compute_der(reference, before_turns)
    before_report = _report_der("before", before_result)
    before_report["segments"] = len(segments)

    print("\n=== end-to-end: after (word-boundary splitting) ===", flush=True)
    after_segments = diarization.assign_speakers(segments, spans)
    after_result = compute_der(reference, _segments_to_turns(after_segments))
    after_report = _report_der("after", after_result)
    after_report["segments"] = len(after_segments)

    before_der, after_der = before_report["der"], after_report["der"]
    print(f"\nend-to-end DER before: {before_der}  ({before_report['segments']} segments)")
    print(f"end-to-end DER after:  {after_der}  ({after_report['segments']} segments)")

    return {
        "mode": "e2e",
        "model": model,
        "language": language,
        "before": before_report,
        "after": after_report,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--audio", default=DEFAULT_AUDIO, help=f"Audio fixture (default: {DEFAULT_AUDIO})"
    )
    parser.add_argument(
        "--rttm", default=DEFAULT_RTTM, help=f"Reference RTTM (default: {DEFAULT_RTTM})"
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=300,
        help="Only diarize/transcribe the first N seconds (default: 300 = ~5 min, per the plan; 0 = whole file)",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=DEFAULT_NUM_SPEAKERS,
        help=f"Known speaker count, or -1 to infer (default: {DEFAULT_NUM_SPEAKERS})",
    )
    parser.add_argument(
        "--mode",
        choices=["span", "e2e", "both"],
        default="span",
        help="span: sherpa-onnx spans only (fast, default). "
        "e2e: labelled transcript segments (slow - runs real transcription). "
        "both: run both.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_E2E_MODEL,
        help=f"--mode e2e only: config.MODELS key or raw repo id (default: {DEFAULT_E2E_MODEL})",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_E2E_LANGUAGE,
        help=f"--mode e2e only: transcription language (default: {DEFAULT_E2E_LANGUAGE}, "
        f"since the AMI fixture is English - see the module docstring)",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Transcribe with config.VAD_FILTER forced off for this run. "
        "End-to-end DER is dominated by missed speech (55.6s of 155.4s on "
        "AMI ES2004a, against 16.3s at span level) - speech the diarizer "
        "found but no transcript segment covers, which no assignment logic "
        "can label. This isolates how much of that gap is the VAD dropping "
        "audio before the decoder ever sees it.",
    )
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if not os.path.exists(args.audio) or not os.path.exists(args.rttm):
        print("Diarization fixture not found - skipping.")
        print(f"  audio: {args.audio}  (exists: {os.path.exists(args.audio)})")
        print(f"  rttm:  {args.rttm}  (exists: {os.path.exists(args.rttm)})")
        print("\nExpected layout (see this script's module docstring for source URLs,")
        print("which are not fetched automatically):")
        print(f"  {DEFAULT_AUDIO}")
        print(f"  {DEFAULT_RTTM}")
        return 0

    try:
        from speech_to_text.core import diarization
    except ImportError as e:
        print(f"Diarization dependencies not available - skipping. ({e})")
        return 0

    if not diarization.models_present():
        print(
            "Diarization models not downloaded - skipping. Run diarization.ensure_models() first,"
        )
        print("or transcribe once with speaker identification on to fetch them.")
        return 0

    from speech_to_text.core import audio_source
    from tests.eval.diarization_metrics import read_rttm

    print(f"Decoding {args.audio} ...", flush=True)
    channels, _two_party = audio_source.load(args.audio)
    if channels is None:
        print("Could not decode audio.", file=sys.stderr)
        return 1

    samples = audio_source.to_mono(channels)
    if args.seconds:
        samples = samples[: int(args.seconds * audio_source.SAMPLE_RATE)]
    duration = len(samples) / audio_source.SAMPLE_RATE
    print(f"  {duration / 60:.1f} min", flush=True)

    reference = read_rttm(args.rttm)
    if args.seconds:
        # The audio was trimmed to the first N seconds; score against the
        # matching slice of reference speech only, or "before" would be
        # scored against 30 minutes of reference while only diarizing 5.
        reference = [(s, min(e, args.seconds), spk) for s, e, spk in reference if s < args.seconds]
    if not reference:
        print("Reference RTTM has no turns within the diarized window.", file=sys.stderr)
        return 1

    results = []
    if args.mode in ("span", "both"):
        results.append(
            run_span_mode(samples, audio_source.SAMPLE_RATE, args.num_speakers, reference)
        )
    if args.mode in ("e2e", "both"):
        try:
            results.append(
                run_e2e_mode(
                    samples,
                    audio_source.SAMPLE_RATE,
                    args.num_speakers,
                    duration,
                    args.model,
                    args.language,
                    reference,
                    no_vad=args.no_vad,
                )
            )
        except Exception as e:
            logger.exception("End-to-end mode failed")
            print(f"\nEnd-to-end mode failed: {e}", file=sys.stderr)
            return 1

    os.makedirs(args.output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.audio))[0]
    metrics_path = os.path.join(args.output_dir, f"{stem}_diarization_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    print(f"\nMetrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
