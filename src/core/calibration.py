"""Hardware-specific transcription-speed calibration.

Times a short real transcription with the tiny model on this machine, and
scales that one measurement by each model's relative cost, instead of guessed
speed factors. Runs in its own process (see core/__init__.py).
"""

import json
import logging
import multiprocessing
import os
import struct
import tempfile
import time
import wave

import config

logger = logging.getLogger(__name__)

# Whisper always processes audio in fixed internal 30-second windows,
# regardless of input length - a clip shorter than 30s still costs almost as
# much compute as a full window, which massively inflates a naive
# elapsed/duration ratio. 60s (two full windows) gives a stable average
# without a long one-time wait.
CALIBRATION_AUDIO_SECONDS = 60
CALIBRATION_SAMPLE_RATE = 16000
# In the absolute model root, so it is found from any working directory
# (see config/paths.py).
CALIBRATION_CACHE_PATH = os.path.join(config.MODEL_DOWNLOAD_ROOT, ".calibration.json")

# Inference cost relative to "tiny" (the benchmark), from parameter counts
# (tiny 39M, large-v3 1550M): Whisper's compute scales with model width.
_TINY_PARAMS = 39
RELATIVE_COMPUTE_COST = {
    "tiny": 39 / _TINY_PARAMS,
    # Fine-tunes cost what their base architecture costs: ivrit-large is
    # large-v3. Turbo overrides the parameter proxy: it cuts large-v3's
    # decoder from 32 layers to 4, and the sequential decoder dominates
    # runtime far beyond its share of parameters. _TURBO_SPEEDUP comes from
    # published large-v3-vs-turbo throughput (~5-6x), not from parameters.
    "ivrit-turbo": (1550 / _TINY_PARAMS) / 5.5,
    "ivrit-large": 1550 / _TINY_PARAMS,
}


def load_cached_tiny_rtf(cpu_cores: int, device: str) -> float | None:
    """The cached seconds-per-audio-second factor, if measured on this core
    count and device - a GPU number reused on a CPU would make the ETA wildly
    wrong.
    """
    if not os.path.exists(CALIBRATION_CACHE_PATH):
        return None
    try:
        with open(CALIBRATION_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if (
            data.get("cpu_cores") == cpu_cores
            and data.get("device") == device
            and "tiny_seconds_per_audio_second" in data
        ):
            return float(data["tiny_seconds_per_audio_second"])
    except Exception as e:
        logger.debug(f"Could not read calibration cache: {e}")
    return None


def save_calibration(cpu_cores: int, device: str, tiny_seconds_per_audio_second: float) -> None:
    try:
        os.makedirs(os.path.dirname(CALIBRATION_CACHE_PATH) or ".", exist_ok=True)
        with open(CALIBRATION_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cpu_cores": cpu_cores,
                    "device": device,
                    "tiny_seconds_per_audio_second": tiny_seconds_per_audio_second,
                },
                f,
            )
    except Exception as e:
        logger.warning(f"Could not save calibration cache: {e}")


def _generate_silence_wav(path: str, seconds: int, sample_rate: int) -> None:
    """Write a short silent mono WAV with the stdlib.

    With VAD off the encoder runs its full window over silence too, and silence
    is deterministic; noise measured no more realistically, only less
    reproducibly.
    """
    n_frames = seconds * sample_rate
    silence_frame = struct.pack("<h", 0)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframesraw(silence_frame * n_frames)


def _run_calibration(cpu_cores: int, device: str) -> float:
    """Run the actual timed benchmark. Must only be called inside the worker process."""
    from core.transcriber import Transcriber

    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = os.path.join(tmp_dir, "calibration.wav")
        _generate_silence_wav(wav_path, CALIBRATION_AUDIO_SECONDS, CALIBRATION_SAMPLE_RATE)

        transcriber = Transcriber(model_size="tiny", device=device)
        if not transcriber.load_model():
            raise RuntimeError("Failed to load calibration model")
        # load_model() may have fallen back to CPU (e.g. cuda requested but
        # unavailable) - cache under the device that actually ran, not the
        # one requested, so load_cached_tiny_rtf's lookup stays honest.
        effective_device = transcriber.device

        start = time.time()
        # Call the model directly (not Transcriber.transcribe) so VAD stays
        # off - we want the true per-second processing cost regardless of
        # audio content, since we can't know in advance how much of a real
        # file will be silence.
        segments, _ = transcriber.model.transcribe(
            wav_path,
            language="he",
            beam_size=5,
            vad_filter=False,
        )
        list(segments)  # faster-whisper returns a lazy generator; force full processing
        elapsed = time.time() - start

    seconds_per_audio_second = max(elapsed / CALIBRATION_AUDIO_SECONDS, 0.01)
    save_calibration(cpu_cores, effective_device, seconds_per_audio_second)
    logger.info(
        f"Calibration complete: {seconds_per_audio_second:.4f}s processing "
        f"per second of audio (tiny model, {cpu_cores} CPU cores, device={effective_device})"
    )
    return seconds_per_audio_second


def run_calibration_process(
    cpu_cores: int, device: str, result_queue: "multiprocessing.Queue"
) -> None:
    """Calibration subprocess entry point: puts ("ok", seconds_per_audio_second)
    or ("error", message) on result_queue.
    """
    try:
        result_queue.put(("ok", _run_calibration(cpu_cores, device)))
    except Exception as e:
        logger.error(f"Calibration worker process error: {e}", exc_info=True)
        result_queue.put(("error", str(e)))
