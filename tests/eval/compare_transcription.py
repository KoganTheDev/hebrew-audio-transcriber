"""
Sweep faster-whisper decode knobs that transcriber.py never exposes, and
measure what each one costs or buys on real Hebrew audio.

Dev-only, deliberately outside the pytest suite, mirroring
tests.eval.compare_diarization and tests.eval.compare_models: this needs real
audio and can run for tens of minutes per config, neither of which belongs in
a unit test run.

Why this owns its own model.transcribe() call
------------------------------------------------
core/transcriber.py:Transcriber.transcribe() hard-codes every decode option at
its one call site (currently transcriber.py:208-221) - beam_size, VAD
settings, word_timestamps - and none of the knobs this harness exists to
measure (compression_ratio_threshold, no_repeat_ngram_size,
condition_on_previous_text, batching, compute_type, thread count) are
threaded through as constructor arguments the way beam_size/compute_type/
cpu_threads/num_workers already are. Rather than growing Transcriber's
constructor for a one-off measurement, this script constructs
faster_whisper.WhisperModel (and, for the batched_* configs,
faster_whisper.BatchedInferencePipeline) directly and calls transcribe() with
production's own defaults plus exactly one override at a time.

PRODUCTION_DEFAULTS below is a hand-copied mirror of transcriber.py:208-221
and config.py's LANGUAGE/BEAM_SIZE/VAD_FILTER/COMPUTE_TYPE. It is NOT
imported or derived from those files - faster-whisper's own library defaults
for compression_ratio_threshold (2.4), no_repeat_ngram_size (0) and
condition_on_previous_text (True) are also never passed by transcriber.py,
so "baseline" here means "every knob transcriber.py passes explicitly, set to
what it passes; every knob it doesn't touch, left at faster-whisper's own
default" - which IS production behaviour today, but only because nothing
enforces the two staying in sync. If transcriber.py:208-221 or config.py's
BEAM_SIZE/LANGUAGE/VAD_FILTER/COMPUTE_TYPE change, PRODUCTION_DEFAULTS below
must be updated by hand, or every number this script reports is a comparison
against a fiction.

What proxies can and cannot tell you (podcast vs tesr1)
------------------------------------------------------------
mp3_test/podcast_transcript_test/podcast.mp4 ships with a hand-correctable
reference transcript (transcript.txt), so real WER/CER are reported for it.

mp3_test/tesr1.wav has no reference transcript at all - nobody has ever
hand-corrected it. Any "wer"/"cer" field on this file would necessarily be
fabricated, so this script never emits one for it: only speed and label-free
proxies (mean/median word confidence, low-confidence share, repeated
segments, retry counts) are reported, and a line is printed making the
absence explicit rather than silently omitting the field. What tesr1.wav is
for is real faster-whisper temperature-fallback events on real audio, which
the podcast fixture does not produce at all (it decodes with zero retries).
tesr1.wav yields 6 of them, consistently, at both 360s and the full 900s.

Treat the "05:05-05:29 retry cluster" framing in the defaults below with
care: it came from the app's own log, where a whole-log total of 113 retries
spanning several days and several FILES was misattributed to one run of this
file. That run actually had 4. A clip starting mid-file at 240s draws ZERO
retries even though it covers those timestamps, because the retry depends on
the condition_on_previous_text chain built from the start of the file rather
than on the local audio. So retries here are reproducible from offset 0 and
are NOT a property of any particular region. Each config's DIVERGENCE from the production-baseline
config's own decode on the same clip is also reported (divergence_wer,
via hebrew_metrics.word_error_rate with the baseline text as reference) -
this measures how much the text CHANGED, not whether it improved. A config
that halves the retry count while producing a wildly different transcript is
not obviously a win; one with near-zero divergence and fewer retries is the
one worth trusting most.

Where the numbers this validates against came from
--------------------------------------------------
An ad-hoc, never-committed script once produced
mp3_test/podcast_transcript_test/beam_compare_results.json, comparing
beam_size 5 vs 1 on the full podcast. That JSON's field names (transcribe_
seconds, realtime_factor, segments, words, mean_word_confidence,
low_confidence_share, repeated_segments, temperature_fallback_events, wer,
cer) are this script's schema's starting point, and its beam_size=5 row is
what --config baseline on the podcast is validated against - see this
script's own validation run, not repeated automatically here.

Retry instrumentation
----------------------
faster-whisper logs each internal decode retry (at DEBUG, on its own
"faster_whisper" logger) as it falls back through progressively higher
sampling temperatures - see core/worker.py's _RETRY_LOG_PATTERNS and
_RetryStatusLogHandler, which this script imports and attaches to in exactly
the same way (a logging.Handler on the "faster_whisper" logger at DEBUG).
_RETRY_LOG_PATTERNS classifies a retry line as a compression-ratio failure or
a log-probability failure and captures the retry temperature, but was built
for a live progress message and was never asked to capture the OBSERVED
compression ratio itself - the number in
"...not met with temperature 0.0 (2.431507 > 2.400000)". This script adds one
extra regex, _COMPRESSION_RATIO_DETAIL, purely to pull that ratio (and the
threshold it was checked against) out of the same line _RETRY_LOG_PATTERNS
already matched - it does not reimplement classification, only extracts one
more number from a line already known to be a compression-ratio retry.

Usage:
    py -3.11 -m tests.eval.compare_transcription --which podcast --config baseline
    py -3.11 -m tests.eval.compare_transcription --which tesr1 --config baseline
    py -3.11 -m tests.eval.compare_transcription --which both --config baseline crt_2.6 crt_off
    py -3.11 -m tests.eval.compare_transcription --which podcast --config baseline --seconds 300
    py -3.11 -m tests.eval.compare_transcription --which tesr1 --config baseline crt_2.8 --repeat 2 --cooldown 180

Why every config used to run inside ONE process, and why that made the
numbers meaningless
------------------------------------------------------------------------
Before this section existed, a sweep of N configs called run_config() N
times in a for-loop inside the same Python process, back to back, no gap.
On a real laptop chip (this machine: i7-1165G7, 4 cores, 28W TDP, Tiger
Lake) that is not a neutral choice - it is a confound, and it was caught
empirically, not in review:

  Full 900s tesr1.wav, "baseline" run FIRST in the sweep:   780s (0.87x
  realtime), 6 temperature-fallback retries.
  SAME file, "crt_2.8" run SECOND, right after baseline:   2763s (3.07x
  realtime), 0 retries.
  SAME file, "no_condition" run THIRD, hottest of all:       708s (0.79x
  realtime), 6 retries.

crt_2.8 removed every retry (strictly less decode work) and came out 3.5x
SLOWER, while no_condition ran LAST and came out FASTEST of the three. That
rules out a monotonic heat effect: if the chip were simply heat-soaking
across the sweep, the third run could not be the quickest. The 2763s is a
transient, not drift.

The cause was found in the Windows event log, not in the timings:

  28/08 16:02:21  "The system is exiting Modern Standby"
  28/08 16:23:25  "The system is exiting Modern Standby"

crt_2.8 ran 15:45-16:31, straddling both. This machine enters Modern
Standby (S0ix) during long unattended runs. Unlike real sleep it does not
stop the process: the Desktop Activity Moderator throttles the CPU hard and
suspends background work while time.perf_counter() keeps counting. Every
stage slows uniformly, the OUTPUT is byte-identical, and the wall clock
detaches from actual compute. Confirmed independently afterwards - a
"sequential" run left running overnight reported ten hours of wall time
against 1235 seconds of process CPU time.

The same event log explains the measurement that started this entire
investigation. A production run of tesr1.wav logged transcribe 6000s and
diarize 818s; the identical configuration measured here reports 1003s and
214s, with the SAME 133 spans and 214 segments coming out the other end.
The event log has an "exiting Modern Standby" at 27/08 13:34, immediately
after that run finished. The app was never 6x slower - the machine was
asleep underneath it.

A warning about the clock counter, since this harness reports it:
`% Processor Performance` was at first read as evidence of thermal
throttling (75-86%, below the 2803MHz base clock). That reading was WRONG.
The same counter reads 53-91% on this chip AT IDLE, because idle P-state
scaling drops the clock as well. A low reading is not by itself evidence of
throttling, and no thermal explanation for anything in this file was ever
confirmed. The counter is still worth recording - a run whose clock
collapsed is worth knowing about - but it must not be read as a thermometer.

On a separate 360s sweep the order effect ran the OTHER direction: the FIRST
config was the slowest, consistent with cold model cache and allocator
warm-up. So run order is confounded with the config effect in both
directions depending on run length, for at least two unrelated reasons.
Every number this harness produced before this section existed is suspect,
and the one config result that was reported as clean (crt_2.8, "26% faster
at 360s") is among the casualties

The fix, mitigation by mitigation
----------------------------------
1. One config per process (--single-config, spawned via subprocess). A
   sweep no longer loops calls inside one interpreter; the parent process
   spawns one fresh `py -3.11 -m tests.eval.compare_transcription
   --single-config <name> ...` child per config, each of which loads its
   own WhisperModel from cold and writes one JSON fragment the parent reads
   back and merges. This does not fix thermal throttling (that is a
   hardware property of the machine, not the process model) but it removes
   two OTHER confounds that live inside a single interpreter: allocator/
   arena state built up by a previous config's decode, and any warm Python-
   level caches faster-whisper or ctranslate2 keep alive between calls.
   Model-load time is still reported separately from transcribe time, same
   as before - subprocessing doesn't change that split, it just means
   load_seconds now includes a colder start every single time, for every
   config, uniformly (see PRODUCTION_DEFAULTS - production always pays this
   same cold load anyway, so this is more representative, not less).

2. Thermal cooldown between configs (--cooldown SECONDS, default 120,
   cooldown_wait()). A fixed sleep would either waste time on a machine
   that already recovered, or under-wait one that hasn't - so this polls
   `% Processor Performance` every few seconds and returns as soon as it
   reads back at or above COOLDOWN_RECOVERY_THRESHOLD, OR when the cap is
   hit, whichever comes first. Every run's result records whether its
   cooldown actually recovered (cooldown_recovered) versus hit the cap
   still cold (or hot) - a False here means "trust this run's comparison
   to its neighbors less", and print_table surfaces it as an explicit note
   rather than a number silently sitting in the JSON.

3. CPU performance-state sampling during every transcribe phase
   (_CpuSampler, a daemon thread polling `Get-Counter '\Processor
   Information(_Total)\% Processor Performance'` every CPU_SAMPLE_INTERVAL
   seconds for the duration of model.transcribe()). Note honestly that
   this sampling did NOT explain the 780s vs 2763s result - the Windows
   event log did, and the counter actively misled the first reading of it
   (see above). It is recorded because a run whose clock collapsed is worth
   knowing about, and because a timing with no clock state beside it cannot
   be argued about at all. Sampling degrades to None on any failure
   (non-Windows, PowerShell missing, permission denied, WMI hiccup) rather
   than raising - a broken thermal sample must never take down a
   transcription run. mean/min/final % are reported in the JSON AND in
   print_table's columns, deliberately not JSON-only: a timing number
   without its clock state next to it is not interpretable on this class of
   machine, and burying it one level down in the JSON is how the original
   confound went unnoticed for as long as it did.

4. A-B-A ordering (--repeat N, default 1). With baseline in --config, the
   sweep runs baseline first (as before, for divergence_wer), then every
   other requested config once, then baseline again N-1 more times at the
   end. compute_baseline_drift() diffs the first and last baseline
   transcribe_seconds/realtime_factor and reports both a "_baseline_drift"
   record in the JSON and, if either delta exceeds
   BASELINE_DRIFT_WARN_THRESHOLD, a loud banner in the printed table. If
   baseline itself drifted meaningfully across the sweep, no delta between
   any two OTHER configs in that same sweep can be trusted either - they
   were measured on a chip whose clock state was moving under them. This is
   the single most important number this harness now produces: it is the
   difference between "here is what the knob did" and "here is what the
   knob did, maybe, we cannot tell."

5. Clock-normalized wall time (transcribe_seconds_normalized =
   transcribe_seconds * cpu_pct_mean / 100, compute_normalized_seconds()).
   % Processor Performance is relative to the chip's BASE clock (100% =
   base, ~170% = this chip's cool boost ceiling), so scaling elapsed time by
   the mean reading estimates "how long this would have taken if the chip
   had run flat at 100% the whole time" - shorter when the run happened to
   throttle below 100%, longer when it happened to run boosted above it.
   This is explicitly an ESTIMATE built from a coarse periodic sample of a
   noisy hardware counter, not a measurement - raw transcribe_seconds stays
   the primary number everywhere (tables, config summaries, retry counts);
   the normalized figure exists only to make cross-run comparisons less
   misleading when cooldown didn't fully recover or --repeat shows drift.

None of this makes the underlying constraint go away. The dominant one on
this machine turned out not to be heat at all but Modern Standby, which no
cooldown or process model can prevent from outside - it needs a power
request held by whatever is doing the work (see worker.py). The drift check
exists to catch and announce a confounded sweep, not to pretend the
environment can be engineered away from inside a benchmark script.

Anyone re-running a long sweep here should check the event log afterwards:

  Get-WinEvent -FilterHashtable @{LogName='System';
    ProviderName='Microsoft-Windows-Kernel-Power'; Id=42,107,507}

An "exiting Modern Standby" timestamped inside a run invalidates that run.
"""

import argparse
import json
import logging
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional

from speech_to_text import config as app_config
from speech_to_text.core.worker import _RETRY_LOG_PATTERNS

logger = logging.getLogger(__name__)

OUTPUT_DIR = "eval_output"

PODCAST_AUDIO = os.path.join("mp3_test", "podcast_transcript_test", "podcast.mp4")
PODCAST_REFERENCE = os.path.join("mp3_test", "podcast_transcript_test", "transcript.txt")
TESR1_AUDIO = os.path.join("mp3_test", "tesr1.wav")

# Start from 0: retries depend on the condition_on_previous_text chain, so a
# mid-file clip covering the same timestamps draws none (see the module
# docstring). A plain 300s prefix (--start 0) contains none of it and would
# measure nothing about retries; starting at 0 with 360s comfortably covers
# the cluster with margin on both sides, without transcribing the whole file.
DEFAULT_START_TESR1 = 0
DEFAULT_SECONDS_TESR1 = 360

LOW_CONFIDENCE = 0.55  # matches core.hebrew_correct's gate and compare_models.py

# =============================================================================
# Thermal / process-isolation controls - see the module docstring's "Why
# every config used to run inside ONE process" section for what these exist
# to fix and the two measured runs that proved it was necessary.
# =============================================================================
DEFAULT_COOLDOWN = 120  # seconds; cap for cooldown_wait() between subprocess configs
COOLDOWN_RECOVERY_THRESHOLD = 95.0  # % Processor Performance considered "recovered"
COOLDOWN_POLL_INTERVAL = 5.0  # seconds between cooldown_wait() samples
CPU_SAMPLE_INTERVAL = 3.0  # seconds between _CpuSampler samples during transcribe
# Relative change (fraction, e.g. 0.15 = 15%) in baseline transcribe_seconds
# or realtime_factor between the first and last --repeat run above which the
# sweep is declared thermally confounded. 15% is deliberately conservative -
# the measured confound above was a 250%+ swing, so this threshold is meant
# to catch drift long before it gets anywhere near that bad.
BASELINE_DRIFT_WARN_THRESHOLD = 0.15

# =============================================================================
# PRODUCTION_DEFAULTS - hand-mirrored from transcriber.py:208-221 and
# config.py. See the module docstring's warning: this is a COPY, not an
# import, and it rots silently if either source changes without this being
# updated too.
# =============================================================================
PRODUCTION_DEFAULTS = {
    # Model-load kwargs (Transcriber._load_on, transcriber.py:145-171)
    "repo": app_config.MODELS["ivrit-turbo"]["repo"],  # ivrit-ai/whisper-large-v3-turbo-ct2
    "device": "cpu",
    # Documents the CPU value only - actually resolved at build time via
    # config.compute_type_for_device(device), exactly like transcriber.py's
    # _load_on (see _build_model below), so a device override still gets the
    # right production default instead of a stale hardcoded "int8".
    "compute_type": app_config.COMPUTE_TYPE,  # "int8" on cpu
    "download_root": "./whisper_models",
    "cpu_threads": None,  # unset -> ctranslate2 picks its own thread count
    "num_workers": None,  # unset -> ctranslate2 picks its own thread count
    # transcribe() kwargs (Transcriber.transcribe, transcriber.py:208-221)
    "language": app_config.LANGUAGE,  # "he"
    "beam_size": app_config.BEAM_SIZE,  # 5
    "word_timestamps": True,
    "vad_filter": app_config.VAD_FILTER,  # True
    "vad_parameters": dict(min_silence_duration_ms=500),
    # NOT passed by transcriber.py at all - faster-whisper's own library
    # defaults apply silently in production. Named here (matching
    # WhisperModel.transcribe's own defaults) so a sweep entry that overrides
    # one of these can be diffed against an explicit, honest baseline value
    # rather than an implicit "whatever faster-whisper happens to default to".
    "compression_ratio_threshold": 2.4,
    "no_repeat_ngram_size": 0,
    "condition_on_previous_text": True,
}

# Keys that belong to WhisperModel's constructor (load time) vs
# model.transcribe()'s call (decode time). batch_size is neither - it only
# applies when routed through BatchedInferencePipeline.transcribe().
_LOAD_KEYS = ("device", "compute_type", "download_root", "cpu_threads", "num_workers")
_TRANSCRIBE_KEYS = (
    "language", "beam_size", "word_timestamps", "vad_filter", "vad_parameters",
    "compression_ratio_threshold", "no_repeat_ngram_size", "condition_on_previous_text",
)

# =============================================================================
# Named sweep configs. Each entry is PRODUCTION_DEFAULTS plus exactly one
# overridden knob (batch_size is the one exception - not a PRODUCTION_DEFAULTS
# key at all, since production never batches). --config selects which of
# these run, so re-measuring one knob never requires re-running the others.
#
# batched_* is NOT actually a one-variable change, despite only setting
# batch_size here: faster_whisper.BatchedInferencePipeline.transcribe's
# public signature accepts condition_on_previous_text like WhisperModel's
# does, but internally (transcribe.py, inside BatchedInferencePipeline.
# transcribe) it builds its TranscriptionOptions with
# condition_on_previous_text=False HARDCODED, ignoring whatever value the
# caller passed - confirmed by reading faster_whisper 1.2.1's own source.
# So every batched_* run below is implicitly ALSO a no_condition run: two
# knobs move together, batching and condition_on_previous_text True->False,
# and there is no way to force the batched path back to True. A result that
# differs between "baseline" and "batched_8" cannot be attributed to
# batching alone without separately comparing against "no_condition" (which
# isolates the condition_on_previous_text=False effect on the UNBATCHED
# path) - see run_config's "override" field in the output JSON for what was
# actually passed, and cross-check it against this comment, not just the
# config name.
# =============================================================================
CONFIGS: Dict[str, Dict] = {
    "baseline": {},
    "crt_2.6": {"compression_ratio_threshold": 2.6},
    "crt_2.8": {"compression_ratio_threshold": 2.8},
    "crt_3.0": {"compression_ratio_threshold": 3.0},
    "crt_off": {"compression_ratio_threshold": None},
    "ngram_3": {"no_repeat_ngram_size": 3},
    "ngram_4": {"no_repeat_ngram_size": 4},
    "batched_4": {"batch_size": 4},
    "batched_8": {"batch_size": 8},
    "batched_16": {"batch_size": 16},
    "no_condition": {"condition_on_previous_text": False},
    "threads_4": {"cpu_threads": 4},
    "int8_float32": {"compute_type": "int8_float32"},
    "float32": {"compute_type": "float32"},
    "beam_1": {"beam_size": 1},
}

# One-line "what changed" per config, used in the printed table so a reader
# doesn't have to cross-reference CONFIGS by hand.
def _override_summary(overrides: Dict) -> str:
    if not overrides:
        return "(production defaults)"
    return ", ".join(f"{k}={v}" for k, v in overrides.items())


# Extra regex on top of _RETRY_LOG_PATTERNS (imported, not reimplemented -
# see the module docstring), purely to pull the observed compression ratio
# and the threshold it was checked against out of a line already known (by
# _RETRY_LOG_PATTERNS) to be a compression-ratio retry, e.g.:
#   "Compression ratio threshold is not met with temperature 0.0 (2.431507 > 2.400000)"
_COMPRESSION_RATIO_DETAIL = re.compile(r"\(([\d.]+) > ([\d.]+)\)")


class _RetryCollector(logging.Handler):
    """
    Attached to the "faster_whisper" logger at DEBUG for the duration of one
    config's transcribe() call, same mechanism as core/worker.py's
    _RetryStatusLogHandler. Instead of forwarding to a progress queue, it
    just accumulates every retry event so this script can report totals,
    a compression/logprob breakdown, and every observed compression ratio.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.events: List[Dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            raw = record.getMessage()
        except Exception:
            return
        for pattern, to_key_params in _RETRY_LOG_PATTERNS:
            match = pattern.match(raw)
            if not match:
                continue
            key, params = to_key_params(match)
            if key == "status_retry_compression":
                detail = _COMPRESSION_RATIO_DETAIL.search(raw)
                self.events.append({
                    "cause": "compression",
                    "temperature": float(params["temp"]),
                    "observed_ratio": float(detail.group(1)) if detail else None,
                    "threshold": float(detail.group(2)) if detail else None,
                })
            elif key == "status_retry_logprob":
                self.events.append({
                    "cause": "logprob",
                    "temperature": float(params["temp"]),
                })
            # "status_analyzing" (Processing segment at ...) is not a retry -
            # ignored here, matched only so the loop below doesn't keep
            # trying the remaining patterns against a line one already
            # consumed.
            return


def _sample_cpu_performance_once() -> Optional[float]:
    """
    One reading of `\\Processor Information(_Total)\\% Processor Performance`
    via PowerShell's Get-Counter, as a fraction-of-base-clock percentage
    (100 = running at the chip's rated base clock; this machine's Tiger Lake
    chip can boost to roughly 170% when cool). Returns None on ANY failure -
    wrong platform, PowerShell missing, permission denied, a transient WMI
    error, a malformed reading - because a broken thermal sample must never
    be allowed to break (or even slow down, beyond its own timeout) an
    actual transcription run. Every caller in this file already treats None
    as "unknown", not as zero.
    """
    try:
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-Counter '\\Processor Information(_Total)\\% Processor Performance')"
                ".CounterSamples.CookedValue",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return None
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        return float(lines[-1])
    except Exception:
        return None


class _CpuSampler(threading.Thread):
    """
    Background daemon thread started right before model.transcribe() and
    stopped right after, so the CPU performance state reported alongside a
    run's timing was actually sampled DURING that run's decode work, not
    before or after it. See the module docstring's item 3 - this is the
    instrumentation that would have made the 780s/2763s confound visible
    from the first sweep instead of requiring a follow-up investigation.
    """

    def __init__(self, interval: float = CPU_SAMPLE_INTERVAL):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()
        self.samples: List[float] = []

    def run(self) -> None:
        while not self._stop_event.is_set():
            value = _sample_cpu_performance_once()
            if value is not None:
                self.samples.append(value)
            self._stop_event.wait(self.interval)

    def stop_and_summarize(self) -> Dict[str, Optional[float]]:
        self._stop_event.set()
        # ident is None until start() has actually run - guards a caller
        # (or a unit test) that summarizes a sampler it never started.
        if self.ident is not None:
            self.join(timeout=self.interval + 5)
        if not self.samples:
            return {
                "cpu_pct_mean": None, "cpu_pct_min": None,
                "cpu_pct_final": None, "cpu_samples": 0,
            }
        return {
            "cpu_pct_mean": round(statistics.fmean(self.samples), 1),
            "cpu_pct_min": round(min(self.samples), 1),
            "cpu_pct_final": round(self.samples[-1], 1),
            "cpu_samples": len(self.samples),
        }


def compute_normalized_seconds(wall_seconds: Optional[float], mean_pct: Optional[float]) -> Optional[float]:
    """
    ESTIMATE, not a measurement - see module docstring item 5. Scales
    observed wall time by the mean clock-performance reading during that
    run, answering "how long would this have taken running flat at the
    chip's base clock the whole time", so a run that happened to throttle
    (mean_pct < 100) normalizes down and one that happened to run boosted
    (mean_pct > 100) normalizes up. Pure function - no I/O - so it's
    directly unit-testable without touching PowerShell or a model.
    """
    if wall_seconds is None or mean_pct is None or mean_pct <= 0:
        return None
    return round(wall_seconds * mean_pct / 100.0, 1)


def cooldown_wait(
    cap_seconds: float,
    recovery_threshold: float = COOLDOWN_RECOVERY_THRESHOLD,
    poll_interval: float = COOLDOWN_POLL_INTERVAL,
) -> Dict:
    """
    Idle between subprocess configs until `% Processor Performance` reads
    back at or above recovery_threshold, or cap_seconds elapses, whichever
    comes first - see module docstring item 2 for why this polls instead of
    sleeping a fixed amount. cap_seconds <= 0 (e.g. --cooldown 0) skips
    waiting entirely and reports cooldown_recovered=None, meaning "not
    checked", distinct from False ("checked and did not recover in time").
    """
    if cap_seconds <= 0:
        return {"cooldown_seconds_used": 0.0, "cooldown_recovered": None, "cooldown_final_pct": None}

    print(
        f"  cooling down (cap {cap_seconds:.0f}s, target >= {recovery_threshold:.0f}% "
        f"processor performance)...",
        flush=True,
    )
    start = time.time()
    last_pct = None
    while True:
        elapsed = time.time() - start
        last_pct = _sample_cpu_performance_once()
        if last_pct is not None and last_pct >= recovery_threshold:
            print(f"  recovered to {last_pct:.0f}% after {elapsed:.0f}s", flush=True)
            return {
                "cooldown_seconds_used": round(elapsed, 1),
                "cooldown_recovered": True,
                "cooldown_final_pct": last_pct,
            }
        if elapsed >= cap_seconds:
            reading = f"{last_pct:.0f}%" if last_pct is not None else "no CPU readings available"
            print(f"  cooldown cap reached ({cap_seconds:.0f}s) without recovering ({reading})", flush=True)
            return {
                "cooldown_seconds_used": round(elapsed, 1),
                "cooldown_recovered": False,
                "cooldown_final_pct": last_pct,
            }
        time.sleep(min(poll_interval, max(0.0, cap_seconds - elapsed)))


def compute_baseline_drift(
    first: Dict, last: Dict, threshold: float = BASELINE_DRIFT_WARN_THRESHOLD,
) -> Dict:
    """
    Diffs the FIRST and LAST baseline run of an A-B-A sweep (--repeat > 1)
    and flags the sweep as thermally confounded if either the raw time or
    the realtime factor moved by more than `threshold` (fraction, e.g. 0.15
    = 15%). See module docstring item 4: if baseline itself isn't stable
    across the sweep, no other config's delta from baseline in that same
    sweep means anything either - the clock state moved under all of them.
    Pure function over two already-computed result dicts, so it's directly
    unit-testable without spawning a subprocess or a model.
    """
    def pct_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if not a or b is None:
            return None
        return round((b - a) / a * 100.0, 1)

    t_delta = pct_delta(first.get("transcribe_seconds"), last.get("transcribe_seconds"))
    r_delta = pct_delta(first.get("realtime_factor"), last.get("realtime_factor"))
    threshold_pct = threshold * 100.0
    confounded = any(d is not None and abs(d) >= threshold_pct for d in (t_delta, r_delta))
    return {
        "config_name": "_baseline_drift",
        "meta_type": "baseline_drift",
        "baseline_first_transcribe_seconds": first.get("transcribe_seconds"),
        "baseline_last_transcribe_seconds": last.get("transcribe_seconds"),
        "baseline_first_realtime_factor": first.get("realtime_factor"),
        "baseline_last_realtime_factor": last.get("realtime_factor"),
        "transcribe_seconds_delta_pct": t_delta,
        "realtime_factor_delta_pct": r_delta,
        "confounded": confounded,
        "threshold_pct": round(threshold_pct, 1),
    }


def _build_model(overrides: Dict):
    """
    Construct WhisperModel per PRODUCTION_DEFAULTS + overrides, wrapped in a
    BatchedInferencePipeline when overrides carries batch_size.

    Returns (model_or_pipeline, batch_size_or_None).
    """
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    device = overrides.get("device", PRODUCTION_DEFAULTS["device"])
    # Mirrors Transcriber._load_on exactly (transcriber.py:160): an explicit
    # override wins, otherwise resolve via config.compute_type_for_device(device)
    # rather than a flat "int8" constant - the two only coincide today because
    # this harness never sweeps device, but a hardcoded value here would be a
    # silent divergence from production the moment that changes.
    compute_type = overrides.get("compute_type") or app_config.compute_type_for_device(device)
    kwargs = dict(
        device=device,
        compute_type=compute_type,
        download_root=overrides.get("download_root", PRODUCTION_DEFAULTS["download_root"]),
    )
    cpu_threads = overrides.get("cpu_threads", PRODUCTION_DEFAULTS["cpu_threads"])
    num_workers = overrides.get("num_workers", PRODUCTION_DEFAULTS["num_workers"])
    if cpu_threads is not None:
        kwargs["cpu_threads"] = cpu_threads
    if num_workers is not None:
        kwargs["num_workers"] = num_workers

    model = WhisperModel(PRODUCTION_DEFAULTS["repo"], **kwargs)

    batch_size = overrides.get("batch_size")
    if batch_size is not None:
        model = BatchedInferencePipeline(model=model)
    return model, batch_size


def _build_transcribe_kwargs(overrides: Dict) -> Dict:
    kwargs = {}
    for key in _TRANSCRIBE_KEYS:
        kwargs[key] = overrides.get(key, PRODUCTION_DEFAULTS[key])
    return kwargs


def run_config(
    name: str,
    overrides: Dict,
    samples,
    duration: float,
    reference: Optional[str],
    baseline_text: Optional[str],
) -> Dict:
    """
    Run one named config over `samples` and collect every metric this
    harness's per-config schema promises. `reference` is the real WER/CER
    reference (podcast only; None for tesr1). `baseline_text` is the
    production-baseline config's own decoded text on this SAME clip, used
    only for divergence_wer - never as an accuracy reference.
    """
    print(f"\n=== {name}: {_override_summary(overrides)} ===", flush=True)

    load_start = time.time()
    model, batch_size = _build_model(overrides)
    load_seconds = time.time() - load_start
    print(f"  loaded in {load_seconds:.1f}s", flush=True)

    transcribe_kwargs = _build_transcribe_kwargs(overrides)

    # Same mechanism as core/worker.py's _RetryStatusLogHandler: DEBUG is
    # required for faster-whisper to even emit "Processing segment at ..."
    # (gated by an isEnabledFor check internally); the retry-threshold lines
    # are unconditional but only reach a handler once the logger itself is
    # listening at this level.
    fw_logger = logging.getLogger("faster_whisper")
    previous_level = fw_logger.level
    fw_logger.setLevel(logging.DEBUG)
    collector = _RetryCollector()
    fw_logger.addHandler(collector)

    # Started right before the timed decode and stopped right after, so the
    # clock-state readings attached to this run's timing were sampled DURING
    # the actual transcribe work - see module docstring item 3 and
    # _CpuSampler's own docstring.
    cpu_sampler = _CpuSampler()
    cpu_sampler.start()
    transcribe_start = time.time()
    try:
        if batch_size is not None:
            raw_segments, info = model.transcribe(samples, batch_size=batch_size, **transcribe_kwargs)
        else:
            raw_segments, info = model.transcribe(samples, **transcribe_kwargs)
        # Materialize now (inside the timed+handler-attached block) - the
        # generator does the actual decoding lazily as it's iterated, and
        # every retry log line fires during that iteration.
        segments = list(raw_segments)
    finally:
        fw_logger.removeHandler(collector)
        fw_logger.setLevel(previous_level)
    transcribe_elapsed = time.time() - transcribe_start
    cpu_summary = cpu_sampler.stop_and_summarize()

    probabilities = [w.probability for s in segments for w in (s.words or [])]
    texts = [s.text.strip() for s in segments]
    repeats = sum(1 for a, b in zip(texts, texts[1:]) if a and a == b)
    text = "".join(s.text for s in segments)

    compression_events = [e for e in collector.events if e["cause"] == "compression"]
    logprob_events = [e for e in collector.events if e["cause"] == "logprob"]
    observed_ratios = [e["observed_ratio"] for e in compression_events if e["observed_ratio"] is not None]

    result = {
        "config_name": name,
        "override": overrides if overrides else None,
        "load_seconds": round(load_seconds, 1),
        "transcribe_seconds": round(transcribe_elapsed, 1),
        "realtime_factor": round(transcribe_elapsed / duration, 3) if duration else None,
        "cpu_pct_mean": cpu_summary["cpu_pct_mean"],
        "cpu_pct_min": cpu_summary["cpu_pct_min"],
        "cpu_pct_final": cpu_summary["cpu_pct_final"],
        "cpu_samples": cpu_summary["cpu_samples"],
        "transcribe_seconds_normalized": compute_normalized_seconds(transcribe_elapsed, cpu_summary["cpu_pct_mean"]),
        "duration_after_vad": round(info.duration_after_vad, 1) if getattr(info, "duration_after_vad", None) is not None else None,
        "segments": len(segments),
        "words": len(probabilities),
        "characters": len(text),
        "mean_word_confidence": round(statistics.fmean(probabilities), 4) if probabilities else None,
        "median_word_confidence": round(statistics.median(probabilities), 4) if probabilities else None,
        "low_confidence_share": (
            round(sum(1 for p in probabilities if p < LOW_CONFIDENCE) / len(probabilities), 4)
            if probabilities else None
        ),
        "repeated_segments": repeats,
        "temperature_fallback_events": len(collector.events),
        "temperature_fallback_compression_events": len(compression_events),
        "temperature_fallback_logprob_events": len(logprob_events),
        "observed_compression_ratios": observed_ratios,
        "wer": None,
        "cer": None,
        "divergence_wer": None,
        "text": text,
    }

    if reference is not None:
        from tests.eval.hebrew_metrics import character_error_rate, word_error_rate
        result["wer"] = round(word_error_rate(reference, text), 4)
        result["cer"] = round(character_error_rate(reference, text), 4)

    if baseline_text is not None:
        from tests.eval.hebrew_metrics import word_error_rate
        # Divergence, NOT accuracy: baseline_text is this same clip's
        # production-baseline decode, used only as the reference sequence a
        # word-error-rate diff is computed against. A high number here means
        # "this config's text looks very different from baseline's", not
        # "this config is wrong" - see the module docstring.
        result["divergence_wer"] = round(word_error_rate(baseline_text, text), 4)

    cpu_note = (
        f"cpu% mean/min/final {cpu_summary['cpu_pct_mean']}/{cpu_summary['cpu_pct_min']}/{cpu_summary['cpu_pct_final']}"
        if cpu_summary["cpu_pct_mean"] is not None else "cpu% unavailable"
    )
    print(
        f"  {transcribe_elapsed:.0f}s ({result['realtime_factor']}x realtime), {cpu_note}, "
        f"{len(segments)} segments, mean confidence {result['mean_word_confidence']}, "
        f"retries {result['temperature_fallback_events']} "
        f"(compression {result['temperature_fallback_compression_events']}, "
        f"logprob {result['temperature_fallback_logprob_events']})",
        flush=True,
    )
    return result


def print_table(results: List[Dict], has_reference: bool) -> None:
    # "_baseline_drift" (from compute_baseline_drift) is analysis metadata,
    # not a config run - it has no transcribe_seconds/segments/etc of its own
    # and is reported separately, in its own loud banner, not as a table row.
    meta_rows = [r for r in results if r.get("meta_type") == "baseline_drift"]
    rows = [r for r in results if "error" not in r and r.get("meta_type") != "baseline_drift"]
    if not rows:
        print("\nNo config produced a transcript.")
    else:
        columns = [
            ("config_name", "config", ""),
            ("run_role", "role", ""),
            ("transcribe_seconds", "time", "s"),
            ("realtime_factor", "xRT", ""),
            ("transcribe_seconds_normalized", "time~norm", "s"),
            ("cpu_pct_mean", "cpuMean", "%"),
            ("cpu_pct_min", "cpuMin", "%"),
            ("cpu_pct_final", "cpuFinal", "%"),
            ("segments", "segs", ""),
            ("words", "words", ""),
            ("mean_word_confidence", "conf", ""),
            ("repeated_segments", "repeat", ""),
            ("temperature_fallback_events", "retries", ""),
        ]
        if has_reference:
            columns += [("wer", "WER", ""), ("cer", "CER", "")]
        else:
            columns += [("divergence_wer", "diverg", "")]

        header = "  ".join(f"{label:>12}" for _, label, _ in columns)
        print("\n" + header)
        print("-" * len(header))
        for row in rows:
            print("  ".join(f"{str(row.get(key, '')) + unit:>12}" for key, _, unit in columns))

        # cooldown_recovered is False only when cooldown_wait() hit its cap
        # without the CPU reading back at/above COOLDOWN_RECOVERY_THRESHOLD -
        # None means "not checked" (first run in a target, or --cooldown 0)
        # and is not worth a note. See module docstring item 2.
        for row in rows:
            if row.get("cooldown_recovered") is False:
                print(
                    f"  NOTE: {row.get('config_name')} ({row.get('run_role')}) started "
                    f"before the CPU recovered - cooldown cap reached at "
                    f"{row.get('cooldown_final_pct')}% (target "
                    f"{COOLDOWN_RECOVERY_THRESHOLD:.0f}%). Compare this run's numbers with that in mind."
                )

    # Loud on purpose - see module docstring item 4. This is meant to be
    # impossible to miss, not a line item in the JSON.
    for meta in meta_rows:
        if meta.get("confounded"):
            print("\n" + "!" * 78)
            print("! THERMAL CONFOUND WARNING")
            print(
                f"! baseline drifted {meta.get('transcribe_seconds_delta_pct')}% in transcribe_seconds "
                f"and {meta.get('realtime_factor_delta_pct')}% in realtime_factor"
            )
            print(f"! between its first run ({meta.get('baseline_first_transcribe_seconds')}s) "
                  f"and its last run ({meta.get('baseline_last_transcribe_seconds')}s), "
                  f"exceeding the {meta.get('threshold_pct')}% threshold.")
            print("! Every delta between configs in THIS sweep is UNRELIABLE - the chip's clock")
            print("! state moved more than the threshold across the sweep. Re-run with a longer")
            print("! --cooldown, or trust nothing here beyond which retries fired.")
            print("!" * 78 + "\n")
        else:
            print(
                f"\nBaseline drift check: {meta.get('transcribe_seconds_delta_pct')}% time / "
                f"{meta.get('realtime_factor_delta_pct')}% xRT (threshold {meta.get('threshold_pct')}%) - "
                f"not confounded."
            )


def _load_clip(audio_path: str, start: float, seconds: float):
    from speech_to_text.core import audio_source

    print(f"Decoding {audio_path} ...", flush=True)
    channels, _two_party = audio_source.load(audio_path)
    if channels is None:
        raise RuntimeError(f"Could not decode {audio_path}")

    samples = audio_source.to_mono(channels)
    start_idx = int(start * audio_source.SAMPLE_RATE)
    if seconds:
        end_idx = start_idx + int(seconds * audio_source.SAMPLE_RATE)
        samples = samples[start_idx:end_idx]
    elif start_idx:
        samples = samples[start_idx:]
    duration = len(samples) / audio_source.SAMPLE_RATE
    print(f"  {duration / 60:.1f} min (start={start}s, seconds={seconds or 'all'})", flush=True)
    return samples, duration


def run_single_config_subprocess(args: argparse.Namespace) -> int:
    """
    The child side of process isolation (module docstring item 1). Invoked
    as `--single-config <name>` by _spawn_single_config() from a fresh
    `py -3.11 -m tests.eval.compare_transcription` process - this function
    loads exactly one model, decodes exactly one clip, and writes exactly
    one JSON result dict to --result-file before exiting. It never sees any
    other config's process state, which is the entire point.
    """
    if not args.result_file:
        print("--single-config requires --result-file", file=sys.stderr)
        return 2
    if not args.audio:
        print("--single-config requires --audio", file=sys.stderr)
        return 2

    name = args.single_config
    overrides = CONFIGS[name]

    reference = None
    if args.reference and os.path.exists(args.reference):
        with open(args.reference, encoding="utf-8") as handle:
            reference = handle.read()

    baseline_text = None
    if args.baseline_text_file and os.path.exists(args.baseline_text_file):
        with open(args.baseline_text_file, encoding="utf-8") as handle:
            baseline_text = handle.read()

    start = args.start if args.start is not None else 0.0
    seconds = args.seconds if args.seconds is not None else 0.0
    samples, duration = _load_clip(args.audio, start, seconds)

    try:
        result = run_config(name, overrides, samples, duration, reference, baseline_text)
    except Exception as e:
        logger.exception("Config %s failed", name)
        result = {"config_name": name, "override": overrides if overrides else None, "error": str(e)}

    with open(args.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    return 0


def _spawn_single_config(
    name: str,
    audio_path: str,
    reference_path: Optional[str],
    start: float,
    seconds: float,
    baseline_text_file: Optional[str],
    result_file: str,
) -> None:
    """
    Launches one config as its own `py -3.11` process (module docstring item
    1). Uses sys.executable rather than re-resolving "py -3.11" from PATH -
    sys.executable is already the exact interpreter this parent process is
    running under, which the repo's launcher/CLI conventions guarantee is
    the right one, and re-deriving it here would just be one more place the
    resolution could drift from what actually launched the parent (see
    LLM_Wiki's launcher-python-resolution note on why that resolution is
    fragile in the first place).

    stdout/stderr are inherited (not captured) so run_config's own progress
    prints - "loaded in Xs", the retries line - still stream to the
    terminal exactly as they did in-process; only the structured result
    comes back via --result-file, read by the caller after this returns.
    """
    cmd = [
        sys.executable, "-m", "tests.eval.compare_transcription",
        "--single-config", name,
        "--audio", audio_path,
        "--start", str(start),
        "--seconds", str(seconds),
        "--result-file", result_file,
    ]
    if reference_path:
        cmd += ["--reference", reference_path]
    if baseline_text_file:
        cmd += ["--baseline-text-file", baseline_text_file]
    subprocess.run(cmd, check=False)


def run_target(
    label: str,
    audio_path: str,
    reference_path: Optional[str],
    config_names: List[str],
    start: float,
    seconds: float,
    output_dir: str,
    cooldown: float,
    repeat: int,
) -> List[Dict]:
    if not os.path.exists(audio_path):
        print(f"{label}: audio not found at {audio_path} - skipping.")
        return []

    if reference_path and not os.path.exists(reference_path):
        print(f"{label}: reference not found at {reference_path} - WER/CER will not be reported.")
        reference_path = None

    if reference_path is None:
        print(f"\n{label}: no reference transcript - WER not available. "
              f"Reporting speed and label-free proxies only, plus divergence "
              f"from this run's own baseline decode (see module docstring).")

    # Run plan: baseline first (if requested) so every other config can be
    # scored for divergence against it, same as before subprocessing was
    # added; then every other requested config; then, for --repeat > 1,
    # baseline again N-1 more times at the end (A-B-A, module docstring
    # item 4) so drift across the sweep can be measured, not just assumed
    # absent.
    has_baseline = "baseline" in config_names
    other_names = sorted(n for n in config_names if n != "baseline")
    run_plan: List[tuple] = []
    if has_baseline:
        run_plan.append(("baseline", "baseline_first"))
        run_plan += [(n, "other") for n in other_names]
        for _ in range(max(0, repeat - 1)):
            run_plan.append(("baseline", "baseline_last"))
    else:
        run_plan = [(n, "other") for n in sorted(config_names)]
        if repeat > 1:
            print(f"{label}: --repeat > 1 requested but 'baseline' isn't in --config; "
                  f"the A-B-A drift check needs a baseline run and will be skipped.")

    results: List[Dict] = []
    baseline_first_result: Optional[Dict] = None
    baseline_text_file: Optional[str] = None
    tmp_dir = tempfile.mkdtemp(prefix="compare_transcription_")
    try:
        for idx, (name, role) in enumerate(run_plan):
            if idx > 0:
                cooldown_info = cooldown_wait(cooldown)
            else:
                cooldown_info = {
                    "cooldown_seconds_used": 0.0, "cooldown_recovered": None, "cooldown_final_pct": None,
                }

            print(f"\n=== [{label}] {name} ({role}) - {_override_summary(CONFIGS[name])} ===", flush=True)
            result_file = os.path.join(tmp_dir, f"{label}_{idx}_{name}_{role}.json")
            _spawn_single_config(name, audio_path, reference_path, start, seconds, baseline_text_file, result_file)

            if os.path.exists(result_file):
                with open(result_file, encoding="utf-8") as handle:
                    result = json.load(handle)
            else:
                result = {
                    "config_name": name, "override": CONFIGS[name] or None,
                    "error": "subprocess produced no result file (see its stdout/stderr above)",
                }

            result["run_role"] = role
            result.update(cooldown_info)
            results.append(result)

            if role == "baseline_first" and "error" not in result:
                baseline_first_result = result
                baseline_text_file = os.path.join(tmp_dir, f"{label}_baseline_text.txt")
                with open(baseline_text_file, "w", encoding="utf-8") as handle:
                    handle.write(result.get("text", "") or "")

        baseline_last = [r for r in results if r.get("run_role") == "baseline_last" and "error" not in r]
        if baseline_first_result is not None and baseline_last:
            results.append(compute_baseline_drift(baseline_first_result, baseline_last[-1]))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    metrics_path = os.path.join(output_dir, f"{stem}_transcription_sweep.json")
    with open(metrics_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    print_table(results, has_reference=reference_path is not None)
    print(f"\n{label} metrics: {metrics_path}")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--which", choices=["podcast", "tesr1", "both"], default="both",
                         help="Which fixture(s) to run (default: both)")
    parser.add_argument("--config", nargs="+", default=["baseline"],
                         choices=list(CONFIGS.keys()),
                         help=f"Which named config(s) to run (default: baseline). "
                              f"Available: {', '.join(CONFIGS.keys())}")
    parser.add_argument("--start", type=float, default=None,
                         help="Clip start, in seconds (default: 0 for podcast; "
                              f"{DEFAULT_START_TESR1} for tesr1)")
    parser.add_argument("--seconds", type=float, default=None,
                         help="Clip length, in seconds, 0 = whole file (default: whole file "
                              f"for podcast; {DEFAULT_SECONDS_TESR1} for tesr1, since the only "
                              "retries need the context chain from offset 0 - see module docstring)")
    parser.add_argument("--audio", help="Override the podcast audio path")
    parser.add_argument("--reference", help="Override the podcast reference transcript path")
    parser.add_argument("--tesr1-audio", help="Override the tesr1 audio path")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN,
                         help=f"Max seconds to idle between subprocess configs, polling for the CPU "
                              f"to recover above {COOLDOWN_RECOVERY_THRESHOLD:.0f}%% Processor "
                              f"Performance before continuing (default: {DEFAULT_COOLDOWN}; 0 disables "
                              f"waiting). See module docstring item 2.")
    parser.add_argument("--repeat", type=int, default=1,
                         help="Re-run 'baseline' N-1 additional times at the end of the sweep (A-B-A) "
                              "to measure thermal drift across the sweep (default: 1, no extra "
                              "reruns). Requires 'baseline' in --config. See module docstring item 4.")
    # Internal child-process flags for --single-config mode (module
    # docstring item 1) - not meant to be typed by a person, only emitted by
    # _spawn_single_config(), hence SUPPRESS in --help.
    parser.add_argument("--single-config", choices=list(CONFIGS.keys()), default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--baseline-text-file", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.single_config:
        return run_single_config_subprocess(args)

    targets = []
    if args.which in ("podcast", "both"):
        podcast_start = args.start if args.start is not None else 0
        podcast_seconds = args.seconds if args.seconds is not None else 0
        targets.append((
            "podcast", args.audio or PODCAST_AUDIO, args.reference or PODCAST_REFERENCE,
            podcast_start, podcast_seconds,
        ))
    if args.which in ("tesr1", "both"):
        tesr1_start = args.start if args.start is not None else DEFAULT_START_TESR1
        tesr1_seconds = args.seconds if args.seconds is not None else DEFAULT_SECONDS_TESR1
        targets.append((
            "tesr1", args.tesr1_audio or TESR1_AUDIO, None,
            tesr1_start, tesr1_seconds,
        ))

    all_results = {}
    for label, audio_path, reference_path, start, seconds in targets:
        all_results[label] = run_target(
            label, audio_path, reference_path, args.config, start, seconds, args.output_dir,
            args.cooldown, args.repeat,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
