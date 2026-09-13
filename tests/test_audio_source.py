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

from speech_to_text.core import audio_source
from speech_to_text.core.audio_source import (
    SAMPLE_RATE,
    is_true_stereo,
    to_mono,
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


class TestCorrelationMatchesNumpy:
    """
    _correlation replaced np.corrcoef to stop allocating several copies of a
    whole recording to produce one number. It has to give the same answer.

    np.corrcoef is the reference here rather than a hand-computed constant:
    the point is not "is this the right formula" but "is this the SAME formula
    the classification thresholds were tuned against".
    """

    @staticmethod
    def _pair(rng, n):
        return (
            rng.standard_normal(n).astype(np.float32),
            rng.standard_normal(n).astype(np.float32),
        )

    def test_independent_signals(self):
        rng = np.random.default_rng(7)
        left, right = self._pair(rng, 50_000)

        assert audio_source._correlation(left, right) == pytest.approx(
            float(np.corrcoef(left, right)[0, 1]), abs=1e-9
        )

    def test_identical_and_inverted_signals(self):
        rng = np.random.default_rng(11)
        base = rng.standard_normal(20_000).astype(np.float32)

        assert audio_source._correlation(base, base.copy()) == pytest.approx(1.0, abs=1e-9)
        assert audio_source._correlation(base, -base) == pytest.approx(-1.0, abs=1e-9)

    def test_a_signal_that_spans_several_blocks(self):
        """
        The sums are accumulated block by block, so a signal longer than one
        block is the case where that accumulation could go wrong - and every
        real recording is longer than one block.
        """
        rng = np.random.default_rng(13)
        n = audio_source._CORRELATION_BLOCK * 3 + 1234
        left, right = self._pair(rng, n)

        assert audio_source._correlation(left, right) == pytest.approx(
            float(np.corrcoef(left, right)[0, 1]), abs=1e-9
        )

    def test_a_large_dc_offset_does_not_wreck_it(self):
        """
        The computational form of the variance is the one usually warned about
        for cancellation. Audio sits around zero so it does not arise in
        practice, but the accumulation is in float64 so that it survives if it
        ever does.
        """
        rng = np.random.default_rng(17)
        left = (rng.standard_normal(30_000) + 50.0).astype(np.float32)
        right = (rng.standard_normal(30_000) + 50.0).astype(np.float32)

        assert audio_source._correlation(left, right) == pytest.approx(
            float(np.corrcoef(left, right)[0, 1]), abs=1e-6
        )

    def test_a_silent_channel_reads_as_correlated_rather_than_nan(self):
        """
        Zero variance makes the coefficient undefined. is_true_stereo treats a
        non-finite correlation as 1.0 (a mono mix) because that is the safe
        answer - see its docstring on why misclassifying is worse than not
        trying - so returning 1.0 here keeps that behaviour at the source.
        """
        silent = np.zeros(5_000, dtype=np.float32)
        noisy = np.random.default_rng(19).standard_normal(5_000).astype(np.float32)

        assert audio_source._correlation(silent, noisy) == 1.0

    def test_no_samples_at_all(self):
        empty = np.zeros(0, dtype=np.float32)

        assert audio_source._correlation(empty, empty) == 1.0


class TestFrameEnergiesMatchTheSquaredMean:
    """
    einsum replaced np.mean(np.square(...)), which materialised a second copy
    of the whole channel only to reduce it away immediately.
    """

    def test_it_agrees_with_the_obvious_implementation(self):
        rng = np.random.default_rng(23)
        channel = rng.standard_normal(16_000).astype(np.float32)
        frame_length = 1_600

        expected = np.mean(np.square(channel[:16_000].reshape(-1, frame_length)), axis=1)
        actual = audio_source._frame_energies(channel, frame_length)

        assert actual.shape == expected.shape
        assert actual == pytest.approx(expected, rel=1e-5)

    def test_a_channel_shorter_than_one_frame_has_no_frames(self):
        short = np.ones(10, dtype=np.float32)

        assert audio_source._frame_energies(short, 1_600).size == 0


class TestToMonoDoesNotStackTheWholeFile:
    """
    np.mean over a list of channels stacks them into one array first, so
    mixing a stereo file allocated two full copies of it plus a third for the
    astype - four times the result, to produce the result.
    """

    def test_the_mix_is_unchanged(self):
        rng = np.random.default_rng(29)
        left = rng.standard_normal(5_000).astype(np.float32)
        right = rng.standard_normal(5_000).astype(np.float32)

        expected = np.mean([left, right], axis=0).astype(np.float32)

        assert audio_source.to_mono([left, right]) == pytest.approx(expected, abs=1e-6)

    def test_uneven_channels_are_cut_to_the_shorter_one(self):
        left = np.ones(100, dtype=np.float32)
        right = np.ones(60, dtype=np.float32)

        assert audio_source.to_mono([left, right]).shape == (60,)

    def test_the_inputs_are_not_modified(self):
        """The accumulator is a copy: += on channels[0] itself would corrupt
        the caller's audio, and the two-party path still reads those arrays."""
        left = np.ones(100, dtype=np.float32)
        right = np.full(100, 3.0, dtype=np.float32)

        audio_source.to_mono([left, right])

        assert np.all(left == 1.0)
        assert np.all(right == 3.0)

    def test_a_mono_file_is_handed_straight_back(self):
        only = np.ones(100, dtype=np.float32)

        assert audio_source.to_mono([only]) is only

    def test_the_result_is_float32(self):
        left = np.ones(10, dtype=np.float32)
        right = np.zeros(10, dtype=np.float32)

        assert audio_source.to_mono([left, right]).dtype == np.float32
