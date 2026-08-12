"""
Tests for audio decoding and true-stereo classification.

The classifier is the piece most likely to be wrong in the field, and its two
failure modes are asymmetric. A false negative costs a little time (the file
falls through to diarization, which handles it correctly). A false positive
transcribes the same speech twice and invents a second speaker. The synthetic
cases below cover both directions.
"""

import numpy as np
import pytest

from speech_to_text.core.audio_source import (
    SAMPLE_RATE, is_true_stereo, to_mono,
)

rng = np.random.default_rng(1234)


def speech_like(seconds):
    """Noise shaped into syllable-ish bursts - enough structure for energy tests."""
    n = int(SAMPLE_RATE * seconds)
    signal = rng.normal(0, 0.3, n).astype(np.float32)
    envelope = (np.sin(np.linspace(0, seconds * 2 * np.pi * 3, n)) > 0).astype(np.float32)
    return signal * envelope


def silence(seconds):
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def two_party_call(turns=6, turn_seconds=1.0):
    """Alternating speech: each party silent while the other talks."""
    left, right = [], []
    for i in range(turns):
        talk = speech_like(turn_seconds)
        quiet = silence(turn_seconds)
        left.append(talk if i % 2 == 0 else quiet)
        right.append(quiet if i % 2 == 0 else talk)
    return [np.concatenate(left), np.concatenate(right)]


class TestTrueStereoDetection:

    def test_alternating_two_party_call_is_detected(self):
        assert is_true_stereo(two_party_call()) is True

    def test_duplicated_mono_is_rejected(self):
        """The common case: stereo container, identical channels."""
        mono = speech_like(6)
        assert is_true_stereo([mono, mono.copy()]) is False

    def test_near_duplicate_mono_is_rejected(self):
        """Slight channel differences from encoding must not read as two people."""
        mono = speech_like(6)
        jitter = rng.normal(0, 0.01, len(mono)).astype(np.float32)
        assert is_true_stereo([mono, mono + jitter]) is False

    def test_uncorrelated_but_simultaneous_audio_is_rejected(self):
        """
        Uncorrelated does not mean conversational - a stereo music mix is
        uncorrelated too. This is why correlation alone is insufficient.
        """
        both_always_talking = [speech_like(6), speech_like(6)]
        assert is_true_stereo(both_always_talking) is False

    def test_mono_input_is_rejected(self):
        assert is_true_stereo([speech_like(6)]) is False

    def test_silent_channel_is_rejected(self):
        """One-sided recording is still a single speaker, not two."""
        assert is_true_stereo([speech_like(6), silence(6)]) is False

    def test_too_short_to_judge_is_rejected(self):
        assert is_true_stereo([speech_like(0.2), silence(0.2)]) is False

    def test_all_silence_is_rejected(self):
        assert is_true_stereo([silence(6), silence(6)]) is False


class TestToMono:

    def test_mono_passthrough_is_unchanged(self):
        channel = speech_like(1)
        assert to_mono([channel]) is channel

    def test_channels_are_averaged(self):
        a = np.ones(100, dtype=np.float32)
        b = np.full(100, 3.0, dtype=np.float32)
        assert np.allclose(to_mono([a, b]), 2.0)

    def test_ragged_channels_are_truncated_not_crashed(self):
        a = np.ones(100, dtype=np.float32)
        b = np.ones(90, dtype=np.float32)
        assert len(to_mono([a, b])) == 90

    def test_result_is_float32_for_whisper(self):
        result = to_mono([speech_like(1), speech_like(1)])
        assert result.dtype == np.float32
