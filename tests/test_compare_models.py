"""
Tests for the Phase B sweep machinery in tests/eval/compare_models.py.

The harness itself is dev-only by design (see its own module docstring) -
it needs real audio and a real model, minutes to hours of wall-clock time,
neither of which belongs in this suite. What IS testable without either:
argument plumbing (do the CLI axes actually reach Transcriber?), the
median/spread arithmetic, and that the pre-Stage-2 CLI still takes its old
path when none of the new flags are passed. Transcriber itself is mocked
throughout - nothing here loads a real model or touches real audio.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.eval import compare_models


class TestBuildConfigs:
    def test_cartesian_product_across_every_axis_per_model(self):
        configs = compare_models.build_configs(
            models=["tiny", "base"],
            compute_types=["int8", "float32"],
            beam_sizes=[5],
            cpu_threads_list=[None],
            num_workers_list=[None],
            devices=["cpu"],
        )
        # 2 models * 2 compute_types * 1 beam_size * 1 cpu_threads * 1
        # num_workers * 1 device = 4 configs.
        assert len(configs) == 4
        assert {c["model"] for c in configs} == {"tiny", "base"}
        assert {c["compute_type"] for c in configs} == {"int8", "float32"}

    def test_none_axis_values_pass_through_unchanged(self):
        """
        None means "don't override" - the harness must not invent its own
        default, since Transcriber already resolves None to its own
        production default (see core/transcriber.py). A second copy of that
        default here would be a second place for the two to drift apart.
        """
        configs = compare_models.build_configs(
            models=["tiny"], compute_types=[None], beam_sizes=[None],
            cpu_threads_list=[None], num_workers_list=[None], devices=["cpu"],
        )
        assert len(configs) == 1
        assert configs[0]["compute_type"] is None
        assert configs[0]["beam_size"] is None
        assert configs[0]["cpu_threads"] is None
        assert configs[0]["num_workers"] is None


class TestConfigLabel:
    def test_label_omits_unset_axes(self):
        cfg = {
            "model": "tiny", "device": "cpu", "compute_type": None,
            "beam_size": None, "cpu_threads": None, "num_workers": None,
        }
        assert compare_models._config_label(cfg) == "tiny/cpu"

    def test_label_includes_every_set_axis(self):
        cfg = {
            "model": "tiny", "device": "cpu", "compute_type": "float32",
            "beam_size": 1, "cpu_threads": 4, "num_workers": 2,
        }
        label = compare_models._config_label(cfg)
        assert label == "tiny/cpu/float32/beam1/threads4/workers2"


class TestRunConfig:
    """
    run_config() is the piece that actually calls Transcriber - mocked here,
    so these tests are about run_config's own timing/median/spread logic and
    argument forwarding, not about faster-whisper.
    """

    def _cfg(self, **overrides):
        cfg = {
            "model": "tiny", "device": "cpu", "compute_type": None,
            "beam_size": None, "cpu_threads": None, "num_workers": None,
        }
        cfg.update(overrides)
        return cfg

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_forwards_every_axis_to_transcriber(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        cfg = self._cfg(compute_type="float32", beam_size=1, cpu_threads=4, num_workers=2)
        compare_models.run_config(
            cfg, samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=1, language="en",
        )

        mock_transcriber_class.assert_called_once_with(
            model_size="tiny", device="cpu", language="en", compute_type="float32",
            beam_size=1, cpu_threads=4, num_workers=2,
        )

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_language_defaults_to_config_language_not_none(self, mock_transcriber_class):
        """
        The bug this guards against: run_config used to never pass a
        language at all, so Transcriber silently fell back to config.LANGUAGE
        ("he") even when benchmarking non-Hebrew audio - corrupting the
        TIMING being measured (temperature fallback ladder re-decoding with
        sampling), not just the transcript text. See run_config's docstring.
        """
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=1,
        )

        assert mock_transcriber_class.call_args.kwargs["language"] == compare_models.config.LANGUAGE

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_warmup_run_is_not_counted_in_the_timed_repeats(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        result = compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=True, repeats=3,
        )

        # 1 warm-up + 3 timed repeats = 4 calls total, but only 3 in "runs".
        assert mock_transcriber.transcribe.call_count == 4
        assert len(result["runs"]) == 3

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_median_and_spread_are_computed_from_the_timed_runs(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        # One (start, end) pair for load_model, then one per timed repeat:
        # run 1 = 1.0s, run 2 = 0.0s, run 3 = 5.0s.
        fake_times = iter([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 6.0])

        with patch("tests.eval.compare_models.time.time", lambda: next(fake_times)):
            result = compare_models.run_config(
                self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=3,
            )

        assert result["runs"] == [1.0, 0.0, 5.0]
        assert result["median_seconds"] == 1.0
        assert result["spread_seconds"] == 5.0

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_a_single_repeat_has_zero_spread_not_an_error(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        result = compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=1,
        )
        assert result["spread_seconds"] == 0.0
        assert result["cv"] == 0.0
        assert result["iqr_seconds"] is None

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_iqr_only_reported_with_at_least_four_repeats(self, mock_transcriber_class):
        """
        A 2-3 repeat IQR is just min-max wearing a different name - not a
        second, independent view of the spread. Withheld below 4 repeats
        rather than reported as if it were meaningful.
        """
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        result = compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=3,
        )
        assert result["iqr_seconds"] is None

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_cv_flags_a_noisy_config(self, mock_transcriber_class, capsys):
        """
        This is the exact noise this harness is meant to catch: the smoke
        test that triggered the coordinator's stop-the-sweep instruction saw
        two runs of one config at 114.75s and 78.38s - a coefficient of
        variation far above NOISE_CV_THRESHOLD. run_config must flag that
        loudly, not fold it quietly into a median as if it were a result.
        """
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock()]
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        # (start, end) pairs: load 0-0, then runs of 114.75s and 78.38s -
        # the actual noisy smoke-test numbers.
        fake_times = iter([0.0, 0.0, 0.0, 114.75, 114.75, 193.13])

        with patch("tests.eval.compare_models.time.time", lambda: next(fake_times)):
            result = compare_models.run_config(
                self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=2,
            )

        assert result["cv"] > compare_models.NOISE_CV_THRESHOLD
        assert "NOISE WARNING" in capsys.readouterr().out

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_model_load_failure_is_reported_not_raised(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = False
        mock_transcriber_class.return_value = mock_transcriber

        result = compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=1,
        )
        assert result["error"] == "model failed to load"

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_transcription_failure_is_reported_not_raised(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = None
        mock_transcriber.device = "cpu"
        mock_transcriber_class.return_value = mock_transcriber

        result = compare_models.run_config(
            self._cfg(), samples=[0.0] * 16000, duration=1.0, warmup=False, repeats=1,
        )
        assert result["error"] == "transcription failed"


class TestSweepRequested:
    """
    Whether main() takes the new sweep path or the original transcribe_once
    path - the switch that keeps the pre-Stage-2 CLI producing exactly its
    old output when none of the new flags are passed.
    """

    def _args(self, **overrides):
        args = MagicMock()
        args.compute_types = None
        args.beam_sizes = None
        args.cpu_threads = None
        args.num_workers = None
        args.devices = None
        args.repeats = None
        args.warmup = False
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_no_new_flags_means_no_sweep(self):
        assert compare_models._sweep_requested(self._args()) is False

    @pytest.mark.parametrize("field,value", [
        ("compute_types", ["int8"]),
        ("beam_sizes", [1]),
        ("cpu_threads", [4]),
        ("num_workers", [2]),
        ("devices", ["cuda"]),
        ("repeats", 3),
        ("warmup", True),
    ])
    def test_any_single_phase_b_flag_triggers_the_sweep(self, field, value):
        assert compare_models._sweep_requested(self._args(**{field: value})) is True


class TestPrintSweepTable:
    def test_handles_an_all_error_sweep_without_raising(self, capsys):
        compare_models.print_sweep_table([{"model": "tiny", "error": "boom"}])
        assert "No config produced a transcript." in capsys.readouterr().out

    def test_prints_a_row_per_successful_config(self, capsys):
        compare_models.print_sweep_table([
            {
                "label": "tiny/cpu", "median_seconds": 1.23, "spread_seconds": 0.1,
                "median_realtime_factor": 0.5, "load_seconds": 2.0,
            },
        ])
        out = capsys.readouterr().out
        assert "tiny/cpu" in out
        assert "1.23" in out


class TestNoiseHint:
    """
    _noise_hint() is the one extra sentence the coordinator asked for: a
    high cv or an unexpectedly bad realtime factor both point at the same
    likely cause on this harness's own history (see run_config's docstring),
    so it gets named explicitly rather than left for a future reader to
    rediscover via a multi-hour hung run - which is what actually happened.
    """

    def test_no_hint_when_everything_looks_normal(self):
        assert compare_models._noise_hint(cv=0.05, realtime_factor=0.3) is None

    def test_hint_on_high_cv_alone(self):
        hint = compare_models._noise_hint(cv=0.9, realtime_factor=0.3)
        assert hint is not None
        assert "--language" in hint

    def test_hint_on_bad_realtime_factor_alone(self):
        """
        This is exactly the language-mismatch signature: low noise (a
        consistently-wrong-language run can be quite repeatable) but a
        realtime factor far worse than the config should ever produce.
        """
        hint = compare_models._noise_hint(cv=0.05, realtime_factor=5.3)
        assert hint is not None
        assert "--language" in hint

    def test_no_hint_when_realtime_factor_is_unknown(self):
        """duration=0 (no audio length known) leaves median_realtime_factor
        as None - must not crash comparing None > REALTIME_SANITY_FACTOR."""
        assert compare_models._noise_hint(cv=0.05, realtime_factor=None) is None


class TestLanguageFlag:
    """
    The bug this whole flag exists to fix: compare_models never set a
    language, so Transcriber fell back to config.LANGUAGE ("he") even when
    benchmarking the English AMI fixture - corrupting the TIMING being
    measured via faster-whisper's temperature fallback ladder, not just the
    transcript text. A whole Phase B sweep was run and discarded because of
    this before --language existed.
    """

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_transcribe_once_forwards_the_language(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock(text="hi", words=[])]
        mock_transcriber.model_repo = "tiny"
        mock_transcriber.language = "en"
        mock_transcriber_class.return_value = mock_transcriber

        compare_models.transcribe_once("tiny", samples=[0.0] * 16000, duration=1.0, language="en")

        assert mock_transcriber_class.call_args.kwargs["language"] == "en"

    @patch("speech_to_text.core.transcriber.Transcriber")
    def test_transcribe_once_defaults_to_config_language(self, mock_transcriber_class):
        mock_transcriber = MagicMock()
        mock_transcriber.load_model.return_value = True
        mock_transcriber.transcribe.return_value = [MagicMock(text="hi", words=[])]
        mock_transcriber.model_repo = "tiny"
        mock_transcriber.language = compare_models.config.LANGUAGE
        mock_transcriber_class.return_value = mock_transcriber

        compare_models.transcribe_once("tiny", samples=[0.0] * 16000, duration=1.0)

        assert mock_transcriber_class.call_args.kwargs["language"] == compare_models.config.LANGUAGE
