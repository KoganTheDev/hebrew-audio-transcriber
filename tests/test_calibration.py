"""
Tests for core/calibration.py.

The timed benchmark itself needs a real model on real hardware, so what is
covered here is everything around it: the cache's validity rules, the
silence WAV the benchmark measures against, the relative-cost table that
turns one measured model into five predicted ones, and the subprocess entry
point's two-outcome contract.

CALIBRATION_CACHE_PATH is a repo-relative path, so every test that touches
the cache repoints it into tmp_path first - otherwise the suite would write
into whisper_models/ in the working directory.
"""

import json
import wave

import pytest

from speech_to_text.core import calibration


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "whisper_models" / ".calibration.json"
    monkeypatch.setattr(calibration, "CALIBRATION_CACHE_PATH", str(path))
    return path


class TestCache:
    def test_no_cache_file_yet_reads_as_no_measurement(self, cache_path):
        assert calibration.load_cached_tiny_rtf(4) is None

    def test_a_saved_measurement_reads_back_for_the_same_core_count(self, cache_path):
        calibration.save_calibration(4, 0.25)
        assert calibration.load_cached_tiny_rtf(4) == 0.25

    def test_a_measurement_taken_on_a_different_core_count_is_ignored(self, cache_path):
        """
        The number is seconds of processing per second of audio on THIS
        machine's CPU. Reusing it across a different core count would
        silently predict times for hardware that was never measured.
        """
        calibration.save_calibration(4, 0.25)
        assert calibration.load_cached_tiny_rtf(8) is None

    def test_a_corrupt_cache_file_reads_as_no_measurement_rather_than_raising(self, cache_path):
        """
        A truncated or hand-edited cache must cost a re-benchmark, never the
        run that was about to start.
        """
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not json", encoding="utf-8")
        assert calibration.load_cached_tiny_rtf(4) is None

    def test_a_cache_missing_the_measurement_itself_is_not_trusted(self, cache_path):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"cpu_cores": 4}), encoding="utf-8")
        assert calibration.load_cached_tiny_rtf(4) is None

    def test_an_unwritable_cache_location_is_logged_not_raised(self, monkeypatch):
        """
        Saving is a convenience: failing to cache costs one more benchmark
        next launch, and must not surface to the caller as an exception.
        """

        def refuse(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(calibration.os, "makedirs", refuse)
        calibration.save_calibration(4, 0.25)


class TestSilenceWav:
    def test_the_benchmark_audio_is_a_mono_16_bit_clip_of_the_expected_length(self, tmp_path):
        """
        Whisper processes audio in fixed 30-second windows regardless of
        input length, so the clip has to be long enough (two full windows)
        for elapsed/duration to mean anything.
        """
        path = str(tmp_path / "calibration.wav")
        calibration._generate_silence_wav(path, 60, 16000)

        with wave.open(path) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 60 * 16000

    def test_the_clip_is_actually_silent(self, tmp_path):
        """
        Silence keeps the benchmark reproducible; noise makes the decoder's
        token count unpredictable and the timing with it.
        """
        path = str(tmp_path / "calibration.wav")
        calibration._generate_silence_wav(path, 1, 16000)
        with wave.open(path) as wf:
            assert set(wf.readframes(wf.getnframes())) == {0}


class TestRelativeComputeCost:
    def test_tiny_is_the_unit_every_other_model_is_measured_against(self):
        """The benchmark only ever times tiny; every other entry is a prediction."""
        assert calibration.RELATIVE_COMPUTE_COST["tiny"] == 1.0

    def test_cost_rises_with_model_size(self):
        sizes = ["tiny", "base", "small", "medium", "large"]
        costs = [calibration.RELATIVE_COMPUTE_COST[size] for size in sizes]
        assert costs == sorted(costs)

    def test_a_fine_tune_costs_the_same_as_the_architecture_it_was_tuned_from(self):
        """ivrit-large is large-v3: a fine-tune changes weights, not shape."""
        assert (
            calibration.RELATIVE_COMPUTE_COST["ivrit-large"]
            == (calibration.RELATIVE_COMPUTE_COST["large"])
        )

    def test_turbo_is_predicted_cheaper_than_medium(self):
        """
        The parameter-count proxy breaks down for turbo: it keeps large-v3's
        encoder but cuts the decoder from 32 layers to 4, and autoregressive
        decoding dominates wall clock. Costing it by parameters alone put it
        just above medium, which had the recommender skipping past it to a
        model both slower in practice and worse at Hebrew.
        """
        assert (
            calibration.RELATIVE_COMPUTE_COST["ivrit-turbo"]
            < calibration.RELATIVE_COMPUTE_COST["medium"]
        )


class TestSubprocessEntryPoint:
    def test_a_successful_benchmark_is_reported_as_ok_with_the_measurement(self, monkeypatch):
        monkeypatch.setattr(calibration, "_run_calibration", lambda cores: 0.42)
        result_queue = []

        class Queue:
            put = staticmethod(result_queue.append)

        calibration.run_calibration_process(4, Queue())
        assert result_queue == [("ok", 0.42)]

    def test_a_failed_benchmark_is_reported_rather_than_crashing_the_child(self, monkeypatch):
        """
        The GUI is waiting on this queue. A child that died silently would
        leave it waiting forever instead of falling back to an estimate.
        """

        def boom(cores):
            raise RuntimeError("Failed to load calibration model")

        monkeypatch.setattr(calibration, "_run_calibration", boom)
        result_queue = []

        class Queue:
            put = staticmethod(result_queue.append)

        calibration.run_calibration_process(4, Queue())
        assert result_queue == [("error", "Failed to load calibration model")]
