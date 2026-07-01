"""
Hardware-specific transcription-speed calibration.

Replaces guessed "speed factor" constants with a number grounded in an
actual measurement: this module runs a short real transcription with the
tiny model, times how long it actually takes on this machine, and derives
seconds-of-processing-per-second-of-audio from that. Other model sizes are
then estimated by scaling that single measurement by each model's relative
parameter count — real math instead of made-up multipliers, without having
to benchmark every model size separately.

Must run in a separate OS process (see speech_to_text.core.worker for why:
faster-whisper/ctranslate2 and PyQt5 each bundle a conflicting copy of
MSVCP140.dll on Windows, and loading both in one process causes an
intermittent native crash).
"""

import json
import logging
import multiprocessing
import os
import struct
import tempfile
import time
import wave
from typing import Optional

logger = logging.getLogger(__name__)

# Whisper always processes audio in fixed internal 30-second windows,
# regardless of input length — a clip shorter than 30s still costs almost as
# much compute as a full window, which massively inflates a naive
# elapsed/duration ratio. 60s (two full windows) gives a stable average
# without a long one-time wait.
CALIBRATION_AUDIO_SECONDS = 60
CALIBRATION_SAMPLE_RATE = 16000
CALIBRATION_CACHE_PATH = os.path.join("whisper_models", ".calibration.json")

# Relative inference cost of each model size vs. "tiny", derived from each
# model's parameter count (tiny=39M, base=74M, small=244M, medium=769M,
# large=1550M params). Whisper's encoder/decoder compute scales with model
# width, so parameter-count ratios are a reasonable real-world proxy for
# relative runtime — this is what lets one measured benchmark (tiny) predict
# the other four sizes' time on the same hardware.
_TINY_PARAMS = 39
RELATIVE_COMPUTE_COST = {
    "tiny": 39 / _TINY_PARAMS,
    "base": 74 / _TINY_PARAMS,
    "small": 244 / _TINY_PARAMS,
    "medium": 769 / _TINY_PARAMS,
    "large": 1550 / _TINY_PARAMS,
}


def load_cached_tiny_rtf(cpu_cores: int) -> Optional[float]:
    """Return the cached seconds-per-audio-second factor, if valid for this CPU core count."""
    if not os.path.exists(CALIBRATION_CACHE_PATH):
        return None
    try:
        with open(CALIBRATION_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("cpu_cores") == cpu_cores and "tiny_seconds_per_audio_second" in data:
            return float(data["tiny_seconds_per_audio_second"])
    except Exception as e:
        logger.debug(f"Could not read calibration cache: {e}")
    return None


def save_calibration(cpu_cores: int, tiny_seconds_per_audio_second: float) -> None:
    try:
        os.makedirs(os.path.dirname(CALIBRATION_CACHE_PATH) or ".", exist_ok=True)
        with open(CALIBRATION_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "cpu_cores": cpu_cores,
                "tiny_seconds_per_audio_second": tiny_seconds_per_audio_second,
            }, f)
    except Exception as e:
        logger.warning(f"Could not save calibration cache: {e}")


def _generate_silence_wav(path: str, seconds: int, sample_rate: int) -> None:
    """
    Write a short silent mono WAV using only the stdlib.

    Calibration explicitly disables VAD (see _run_calibration), so silence
    is not skipped — the encoder still runs its full fixed-size window
    regardless of content. Silence keeps the benchmark deterministic;
    random noise was tried and measured no more realistically, just less
    reproducibly (decoder token count for noise is unpredictable).
    """
    n_frames = seconds * sample_rate
    silence_frame = struct.pack("<h", 0)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframesraw(silence_frame * n_frames)


def _run_calibration(cpu_cores: int) -> float:
    """Run the actual timed benchmark. Must only be called inside the worker process."""
    from speech_to_text.core.transcriber import Transcriber

    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = os.path.join(tmp_dir, "calibration.wav")
        _generate_silence_wav(wav_path, CALIBRATION_AUDIO_SECONDS, CALIBRATION_SAMPLE_RATE)

        transcriber = Transcriber(model_size="tiny", device="cpu")
        if not transcriber.load_model():
            raise RuntimeError("Failed to load calibration model")

        start = time.time()
        # Call the model directly (not Transcriber.transcribe) so VAD stays
        # off — we want the true per-second processing cost regardless of
        # audio content, since we can't know in advance how much of a real
        # file will be silence.
        segments, _ = transcriber.model.transcribe(
            wav_path, language="he", beam_size=5, vad_filter=False,
        )
        list(segments)  # faster-whisper returns a lazy generator; force full processing
        elapsed = time.time() - start

    seconds_per_audio_second = max(elapsed / CALIBRATION_AUDIO_SECONDS, 0.01)
    save_calibration(cpu_cores, seconds_per_audio_second)
    logger.info(
        f"Calibration complete: {seconds_per_audio_second:.4f}s processing "
        f"per second of audio (tiny model, {cpu_cores} CPU cores)"
    )
    return seconds_per_audio_second


def run_calibration_process(cpu_cores: int, result_queue: "multiprocessing.Queue") -> None:
    """
    Entry point for the calibration subprocess.

    Puts ("ok", seconds_per_audio_second) or ("error", message) on
    result_queue before exiting. Import-light at module level (no PyQt5) —
    see module docstring.
    """
    try:
        result_queue.put(("ok", _run_calibration(cpu_cores)))
    except Exception as e:
        logger.error(f"Calibration worker process error: {e}", exc_info=True)
        result_queue.put(("error", str(e)))
