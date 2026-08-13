"""
Decoding audio into arrays, and deciding whether a file already separates its
speakers by channel.

This project never used to open audio at all - the file path went straight to
faster-whisper, which decodes and downmixes to mono internally. That is fine
until you want to know who is speaking: any per-channel information is gone
before this code sees it, and some of the recordings this app handles (phone
and VoIP call recorders) put each party on their own channel, which is the one
case where speaker attribution can be exact rather than inferred.

PyAV is used for decoding. It is already present as a faster-whisper
dependency, and gui/audio_utils.py already uses it to probe duration, so this
adds no new requirement.

Stdlib + numpy/av only - no PyQt5, this runs in the worker process.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Whisper's own sample rate. Decoding straight to it means faster-whisper does
# no further resampling when we hand it an array.
SAMPLE_RATE = 16000

# --- True-stereo classification thresholds ---------------------------------
# A file having two channels proves nothing: the overwhelming majority of
# stereo audio is a duplicated or near-duplicated mono mix, and treating that
# as two speakers would produce a transcript of one person talking to
# themselves. Two independent conditions have to hold.

# Above this correlation the channels are carrying substantially the same
# signal, i.e. an ordinary stereo mix rather than two separate parties.
MAX_CHANNEL_CORRELATION = 0.5

# Fraction of audible frames that must be loud on exactly one channel. Genuine
# two-party call recordings alternate; a stereo music mix does not.
MIN_EXCLUSIVE_FRAME_RATIO = 0.35

# A frame counts as "loud on one channel only" when that channel's energy
# exceeds the other's by this factor.
EXCLUSIVE_ENERGY_RATIO = 4.0

# Frame size for the energy comparison. 100ms is long enough to be robust to
# noise and short enough to catch normal conversational alternation.
FRAME_SECONDS = 0.1

# Frames quieter than this fraction of the recording's mean energy are silence
# and say nothing about who is speaking.
SILENCE_FLOOR_RATIO = 0.1


def decode_channels(path: str) -> Tuple[List[np.ndarray], int]:
    """
    Decode an audio file to a list of float32 channel arrays at 16 kHz.

    Returns ([channel0, channel1, ...], sample_rate). Mono files yield a
    single-element list.

    Raises whatever PyAV raises - callers decide whether a decode failure is
    fatal or just means falling back to letting faster-whisper open the file
    itself.
    """
    import av

    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"No audio stream in {path}")

        channels = stream.codec_context.channels or 1

        resampler = av.audio.resampler.AudioResampler(
            format="fltp",          # planar float, so channels come out separated
            layout="stereo" if channels >= 2 else "mono",
            rate=SAMPLE_RATE,
        )

        buffers: List[List[np.ndarray]] = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                planes = resampled.to_ndarray()
                # to_ndarray gives (channels, samples) for planar formats, but
                # collapses to (1, samples) or (samples,) for mono depending on
                # the version.
                if planes.ndim == 1:
                    planes = planes[np.newaxis, :]
                if not buffers:
                    buffers = [[] for _ in range(planes.shape[0])]
                for i, plane in enumerate(planes):
                    buffers[i].append(plane)

    if not buffers:
        raise ValueError(f"Decoded no audio from {path}")

    return [np.concatenate(chunks).astype(np.float32) for chunks in buffers], SAMPLE_RATE


def to_mono(channels: List[np.ndarray]) -> np.ndarray:
    """Average channels into one array, as Whisper would do internally."""
    if len(channels) == 1:
        return channels[0]
    length = min(len(c) for c in channels)
    return np.mean([c[:length] for c in channels], axis=0).astype(np.float32)


def _frame_energies(channel: np.ndarray, frame_length: int) -> np.ndarray:
    """Mean square energy per fixed-length frame."""
    usable = len(channel) - (len(channel) % frame_length)
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)
    frames = channel[:usable].reshape(-1, frame_length)
    return np.mean(np.square(frames), axis=1)


def is_true_stereo(channels: List[np.ndarray], sample_rate: int = SAMPLE_RATE) -> bool:
    """
    Decide whether this file has one speaker per channel.

    Both conditions must hold, and they catch different failure modes:

    1. Low inter-channel correlation. A duplicated mono mix correlates near
       1.0; two people on separate lines do not. This alone is not enough,
       because uncorrelated does not imply conversational - stereo music is
       uncorrelated too.
    2. Energy alternates rather than overlapping. In a real two-party
       recording a large share of audible frames are loud on exactly one
       channel. A stereo mix has both channels active nearly all the time.

    Getting this wrong is worse than not trying: misclassifying a normal stereo
    recording as two-party would transcribe the same speech twice and label two
    speakers who do not exist. The thresholds are deliberately conservative -
    an unclear file falls through to diarization, which handles it correctly
    anyway, just more slowly.
    """
    if len(channels) < 2:
        return False

    length = min(len(channels[0]), len(channels[1]))
    if length < sample_rate:  # under a second of audio: nothing to judge on
        return False

    left = channels[0][:length]
    right = channels[1][:length]

    if not np.any(left) or not np.any(right):
        logger.debug("Stereo check: a channel is entirely silent")
        return False

    correlation = float(np.corrcoef(left, right)[0, 1])
    if not np.isfinite(correlation):
        correlation = 1.0
    if abs(correlation) > MAX_CHANNEL_CORRELATION:
        logger.debug(
            f"Stereo check: channels correlate at {correlation:.2f} "
            f"(> {MAX_CHANNEL_CORRELATION}), treating as a mono mix"
        )
        return False

    frame_length = max(int(sample_rate * FRAME_SECONDS), 1)
    left_energy = _frame_energies(left, frame_length)
    right_energy = _frame_energies(right, frame_length)
    if left_energy.size == 0:
        return False

    combined = left_energy + right_energy
    floor = float(np.mean(combined)) * SILENCE_FLOOR_RATIO
    audible = combined > floor
    audible_count = int(np.count_nonzero(audible))
    if audible_count == 0:
        return False

    # +tiny epsilon so a completely silent channel doesn't divide by zero.
    eps = 1e-12
    left_dominant = left_energy > right_energy * EXCLUSIVE_ENERGY_RATIO + eps
    right_dominant = right_energy > left_energy * EXCLUSIVE_ENERGY_RATIO + eps
    exclusive = np.count_nonzero((left_dominant | right_dominant) & audible)
    ratio = exclusive / audible_count

    logger.debug(
        f"Stereo check: correlation={correlation:.2f}, "
        f"exclusive frames={ratio:.0%} of {audible_count} audible"
    )
    # bool(), not the numpy bool this comparison produces: the result gets
    # stored on options and pickled across a process boundary, and callers
    # reasonably expect the plain type the signature promises.
    return bool(ratio >= MIN_EXCLUSIVE_FRAME_RATIO)


def load(path: str) -> Tuple[Optional[List[np.ndarray]], bool]:
    """
    Decode a file and classify it, tolerating failure.

    Returns (channels, is_two_party). channels is None if decoding failed, in
    which case the caller should hand the path to faster-whisper directly and
    skip channel-based speaker separation - a decode problem here should cost
    speaker labels at worst, never the transcript itself.
    """
    try:
        channels, sample_rate = decode_channels(path)
    except Exception as e:
        logger.warning(f"Could not decode {path} for channel analysis: {e}")
        return None, False

    two_party = is_true_stereo(channels, sample_rate)
    logger.info(
        f"Audio decoded: {len(channels)} channel(s), "
        f"{len(channels[0]) / sample_rate:.1f}s, "
        f"{'one speaker per channel' if two_party else 'mixed/mono'}"
    )
    return channels, two_party
