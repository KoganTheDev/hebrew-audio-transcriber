"""
Tests for transcriber module.
"""

from unittest.mock import MagicMock, patch

from speech_to_text.core import progress_scale as ps
from speech_to_text.core.hebrew_text import PDI, RLI
from speech_to_text.core.segments import plain_text
from speech_to_text.core.transcriber import Transcriber


def fake_segment(text, start=0.0, end=1.0, words=None):
    """
    Build a stand-in for a faster-whisper segment.

    MagicMock(text=...) alone is not enough any more: Transcriber now reads
    start/end/words off each segment, and a bare MagicMock returns child
    mocks for those, not numbers. Setting them explicitly keeps these tests
    testing our conversion logic rather than mock behaviour.
    """
    segment = MagicMock()
    segment.text = text
    segment.start = start
    segment.end = end
    segment.words = words
    return segment


class TestTranscriber:
    """Test transcriber functionality."""

    def test_transcriber_initialization(self):
        """Test transcriber initialization."""
        transcriber = Transcriber(model_size="small", device="cpu", language="he")

        assert transcriber.model_size == "small"
        assert transcriber.device == "cpu"
        assert transcriber.language == "he"
        assert transcriber.model is None

    def test_the_default_callback_accepts_the_key_and_params_shape_the_app_emits(self):
        """
        The default callback has to swallow what the real call sites pass.

        Every production call passes a (key, params) tuple - see transcriber's
        own progress_callback(("w_starting", {}), ...) and worker.py's
        emit_progress - because the worker process cannot render translated
        text itself and hands the key across the process boundary instead.
        This test used to pass a bare string, a shape nothing produces.
        """
        transcriber = Transcriber()
        # Should not raise.
        transcriber.progress_callback(("w_starting", {}), 50)

    def test_transcriber_custom_callback(self):
        """Test custom progress callback."""
        callback = MagicMock()
        transcriber = Transcriber(progress_callback=callback)

        transcriber.progress_callback("Test message", 50)
        callback.assert_called_once_with("Test message", 50)

    def test_model_repo_resolves_config_key_to_upstream_id(self):
        """A config.MODELS key is our name for a model, not its address."""
        assert (
            Transcriber(model_size="ivrit-turbo").model_repo
            == "ivrit-ai/whisper-large-v3-turbo-ct2"
        )
        assert Transcriber(model_size="large").model_repo == "large-v3"

    def test_model_repo_passes_through_unknown_names(self):
        """
        Lets the evaluation harness benchmark models that have no GUI card by
        naming a raw Whisper size or repo id directly.
        """
        assert Transcriber(model_size="distil-large-v3").model_repo == "distil-large-v3"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_uses_repo_not_key(self, mock_whisper_model_class):
        """
        The repo id, not our key, must reach faster-whisper - passing
        "ivrit-turbo" would just 404.
        """
        transcriber = Transcriber(model_size="ivrit-turbo")
        transcriber.load_model()

        assert mock_whisper_model_class.call_args.args[0] == "ivrit-ai/whisper-large-v3-turbo-ct2"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_success(self, mock_whisper_model_class):
        """Test successful model loading."""
        mock_model = MagicMock()
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        result = transcriber.load_model()

        assert result is True
        assert transcriber.model is not None
        mock_whisper_model_class.assert_called_once()

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_defaults_to_cpu_compute_type_unset(self, mock_whisper_model_class):
        """
        No cpu_threads/num_workers override given -> neither kwarg reaches
        WhisperModel at all, so ctranslate2 picks its own thread count
        exactly as it always did (see _load_on's docstring for why
        production leaves these alone).
        """
        Transcriber(device="cpu").load_model()

        kwargs = mock_whisper_model_class.call_args.kwargs
        assert kwargs["compute_type"] == "int8"
        assert "cpu_threads" not in kwargs
        assert "num_workers" not in kwargs

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_forwards_explicit_axes_to_whispermodel(self, mock_whisper_model_class):
        """
        The knobs tests/eval/compare_models.py sweeps (Phase B) must actually
        reach WhisperModel, not just live on the Transcriber instance.
        """
        Transcriber(
            compute_type="float32",
            beam_size=1,
            cpu_threads=4,
            num_workers=2,
        ).load_model()

        kwargs = mock_whisper_model_class.call_args.kwargs
        assert kwargs["compute_type"] == "float32"
        assert kwargs["cpu_threads"] == 4
        assert kwargs["num_workers"] == 2

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_uses_cuda_compute_type_on_cuda(self, mock_whisper_model_class):
        """
        config.compute_type_for_device is device-conditional (float16 on
        CUDA, int8 on CPU) - a single global COMPUTE_TYPE used to apply
        regardless of device. Untested on real GPU hardware; see
        load_model()'s docstring.
        """
        Transcriber(device="cuda").load_model()

        assert mock_whisper_model_class.call_args.kwargs["compute_type"] == "float16"
        assert mock_whisper_model_class.call_args.kwargs["device"] == "cuda"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_falls_back_to_cpu_when_cuda_init_fails(self, mock_whisper_model_class):
        """
        A CUDA device_recommendation is only a guess from nvidia-smi output -
        it does not prove the ctranslate2/CUDA runtime actually initialises.
        A driver/CUDA-version mismatch is a real, live failure mode (see
        load_model()'s docstring) and must not fail the whole transcription
        when CPU would have worked fine. Simulated here since this
        development machine has no NVIDIA GPU to fail on for real.
        """
        mock_model = MagicMock()
        mock_whisper_model_class.side_effect = [
            RuntimeError("simulated CUDA init failure"),
            mock_model,
        ]

        transcriber = Transcriber(device="cuda")
        result = transcriber.load_model()

        assert result is True
        assert transcriber.device == "cpu"
        assert transcriber.model is mock_model
        assert mock_whisper_model_class.call_count == 2
        first_call, second_call = mock_whisper_model_class.call_args_list
        assert first_call.kwargs["device"] == "cuda"
        assert second_call.kwargs["device"] == "cpu"
        assert second_call.kwargs["compute_type"] == "int8"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_reports_failure_when_both_cuda_and_the_cpu_fallback_fail(
        self, mock_whisper_model_class
    ):
        """A machine with no working backend at all must still fail cleanly."""
        mock_whisper_model_class.side_effect = RuntimeError("nothing works")

        transcriber = Transcriber(device="cuda")
        result = transcriber.load_model()

        assert result is False
        assert transcriber.model is None

    def test_load_model_whisper_not_installed(self):
        """Test model loading when WhisperModel is not available."""
        with patch("speech_to_text.core.transcriber.WhisperModel", None):
            transcriber = Transcriber()
            result = transcriber.load_model()
            assert result is False

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_failure(self, mock_whisper_model_class):
        """Test model loading failure."""
        mock_whisper_model_class.side_effect = Exception("Model loading failed")

        transcriber = Transcriber()
        result = transcriber.load_model()

        assert result is False
        assert transcriber.model is None

    def test_transcribe_without_model(self):
        """Test transcription without loading model."""
        transcriber = Transcriber()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert result is None

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_success(self, mock_whisper_model_class):
        """Test successful transcription."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello "), fake_segment("World")],
            MagicMock(),
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert result is not None
        text = plain_text(result)
        assert "Hello" in text
        assert "World" in text

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_uses_config_beam_size_by_default(self, mock_whisper_model_class):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["beam_size"] == 5

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_forwards_explicit_beam_size(self, mock_whisper_model_class):
        """The Phase B sweep axis - must actually reach model.transcribe()."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber(beam_size=1)
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["beam_size"] == 1

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_requests_word_timestamps(self, mock_whisper_model_class):
        """
        Word timings must be requested, or segment.words comes back None and
        both diarization and confidence-gated correction silently lose the
        data they depend on.
        """
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["word_timestamps"] is True

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_captures_timings_and_words(self, mock_whisper_model_class):
        """Timings and per-word confidences survive into our Segment type."""
        word = MagicMock()
        word.word = "שלום"
        word.start = 1.5
        word.end = 2.0
        word.probability = 0.42

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("שלום", start=1.5, end=2.0, words=[word])],
            MagicMock(),
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert len(result) == 1
        assert result[0].start == 1.5
        assert result[0].end == 2.0
        assert result[0].speaker is None
        assert len(result[0].words) == 1
        assert result[0].words[0].text == "שלום"
        assert result[0].words[0].probability == 0.42

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_tolerates_missing_word_data(self, mock_whisper_model_class):
        """words=None (word_timestamps off, or an older faster-whisper) must not raise."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello", words=None)], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert len(result) == 1
        assert result[0].words == []

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_adds_spaces_between_segments(self, mock_whisper_model_class):
        """Test that spaces are added between segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello"), fake_segment("World")],
            MagicMock(),
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert plain_text(result) == "Hello World"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_transcribe_empty_segments(self, mock_whisper_model_class):
        """Test transcription with empty segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello"), fake_segment(""), fake_segment("World")],
            MagicMock(),
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        # Should skip empty segment
        assert len(result) == 2
        assert plain_text(result) == "Hello World"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_segment_debug_log_isolates_hebrew_preview(self, mock_whisper_model_class, caplog):
        """
        The reported bug: a Hebrew segment preview logged into the
        otherwise-LTR DEBUG line must be wrapped in an RTL isolate so a
        trailing neutral character (here, the comma) can't reorder to the
        wrong side. See core/hebrew_text.isolate_rtl.
        """
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment(" סניף כשר למהדרין,")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        with caplog.at_level("DEBUG", logger="speech_to_text.core.transcriber"):
            transcriber.transcribe("dummy_audio.mp3")

        debug_lines = [r.message for r in caplog.records if r.message.startswith("Segment ")]
        assert len(debug_lines) == 1
        assert debug_lines[0] == f"Segment 1: {RLI} סניף כשר למהדרין,{PDI}"

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_segment_debug_log_does_not_isolate_ascii_preview(
        self, mock_whisper_model_class, caplog
    ):
        """An ASCII-only preview has no bidi problem, so no isolate noise."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello World")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        with caplog.at_level("DEBUG", logger="speech_to_text.core.transcriber"):
            transcriber.transcribe("dummy_audio.mp3")

        debug_lines = [r.message for r in caplog.records if r.message.startswith("Segment ")]
        assert debug_lines == ["Segment 1: Hello World"]


# Transcript rendering is covered in tests/test_formatting.py - it grew its own
# module once timestamps, turn merging and bidi control characters arrived.


class TestFetchWeights:
    """
    _fetch_weights runs the model download itself so it can report progress.

    Every other test in the suite has it stubbed out by the autouse
    never_download_model_weights fixture in conftest, so these opt back in and
    stub huggingface_hub instead - the point is the reporting and the
    fallbacks, not the network.
    """

    def _transcriber(self, monkeypatch, seen):
        monkeypatch.undo()
        from speech_to_text.core.transcriber import Transcriber

        return Transcriber(model_size="ivrit-turbo", progress_callback=lambda m, p: seen.append(m))

    def test_a_download_reports_progress_and_returns_the_local_path(self, monkeypatch):
        """The caller gets a path, and the user gets told what is happening."""
        seen: list = []
        transcriber = self._transcriber(monkeypatch, seen)

        def fake_snapshot_download(repo_id, cache_dir, tqdm_class):
            # huggingface_hub drives the bar; mimic two of its ticks.
            bar = tqdm_class(total=6)
            bar.update(1)
            bar.update(3)
            return r"C:\models\snapshot"

        import huggingface_hub

        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

        assert transcriber._fetch_weights() == r"C:\models\snapshot"

        updates = [params for key, params in seen if key == "w_downloading_model"]
        assert updates, "the download reported no progress at all"
        assert updates[-1]["done"] == 4
        assert updates[-1]["total"] == 6
        assert updates[-1]["size"] == "1.6 GB", "the message must say how large the download is"

    def test_the_repo_id_is_resolved_not_passed_through_raw(self, monkeypatch):
        """A bare Whisper size is not a HuggingFace address."""
        seen: list = []
        monkeypatch.undo()
        from speech_to_text.core.transcriber import Transcriber

        transcriber = Transcriber(model_size="tiny", progress_callback=lambda m, p: seen.append(m))
        captured = {}

        def fake_snapshot_download(repo_id, cache_dir, tqdm_class):
            captured["repo_id"] = repo_id
            return "/tmp/x"

        import huggingface_hub

        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
        transcriber._fetch_weights()

        assert captured["repo_id"] == "Systran/faster-whisper-tiny"

    def test_a_failed_download_falls_back_instead_of_raising(self, monkeypatch):
        """
        A network failure here must not end the run.

        Returning None puts WhisperModel back in charge of fetching, which is
        what happened before this method existed, and huggingface_hub keeps its
        partial files so a retry resumes.
        """
        seen: list = []
        transcriber = self._transcriber(monkeypatch, seen)

        def boom(repo_id, cache_dir, tqdm_class):
            raise OSError("network is down")

        import huggingface_hub

        monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)

        assert transcriber._fetch_weights() is None


class TestWorkStream:
    """
    What Transcriber reports for the time estimate, as opposed to for the bar.

    The percentage it already emitted was derived from exactly these numbers
    and then rounded into a 0-100 band (see core/progress_scale.py). Turning
    that percentage back into a time was the bug; sending the numbers on
    unrounded, in audio-seconds, is the fix.
    """

    @staticmethod
    def _transcriber(mock_whisper_model_class, segments, work, phases):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (segments, MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber(
            work_callback=lambda done, total: work.append((done, total)),
            phase_callback=lambda name, seconds: phases.append((name, seconds)),
        )
        transcriber.load_model()
        return transcriber

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_each_segment_reports_where_it_ended_in_the_audio(self, mock_whisper_model_class):
        work: list = []
        phases: list = []
        segments = [
            fake_segment("one", start=0.0, end=30.0),
            fake_segment("two", start=30.0, end=95.5),
        ]
        transcriber = self._transcriber(mock_whisper_model_class, segments, work, phases)

        transcriber.transcribe("a.wav", total_duration_seconds=120.0)

        assert [done for done, _total in work][:2] == [30.0, 95.5]
        assert all(total == 120.0 for _done, total in work)

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_the_file_is_closed_out_at_its_full_length(self, mock_whisper_model_class):
        """
        VAD trims trailing silence, so a recording that ends quietly stops
        yielding segments well short of its own length - here the last segment
        ends at 95.5s of a 120s file. Without a closing report the batch's
        audio_done would never reach audio_total and the estimate would keep a
        phantom tail that never counts down.
        """
        work: list = []
        segments = [fake_segment("one", start=0.0, end=95.5)]
        transcriber = self._transcriber(mock_whisper_model_class, segments, work, [])

        transcriber.transcribe("a.wav", total_duration_seconds=120.0)

        assert work[-1] == (120.0, 120.0)

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_no_duration_means_no_work_reported(self, mock_whisper_model_class):
        """
        total_duration_seconds=0 is the "could not probe this file" case (see
        gui/audio_utils.py). There is no denominator, so there is no rate to
        measure, and reporting a position against a guess would produce a
        confidently wrong ETA rather than none at all.
        """
        work: list = []
        segments = [fake_segment("one", start=0.0, end=30.0)]
        transcriber = self._transcriber(mock_whisper_model_class, segments, work, [])

        transcriber.transcribe("a.wav", total_duration_seconds=0)

        assert work == []

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_a_segment_with_no_end_reports_no_position(self, mock_whisper_model_class):
        """
        faster-whisper's segment type has changed shape across releases. A
        missing end is already tolerated for the percentage (it falls back to a
        soft per-segment estimate); the work stream has no such fallback,
        because an invented position is worse than a stale one.
        """
        work: list = []
        segment = fake_segment("one", start=0.0)
        segment.end = None
        transcriber = self._transcriber(mock_whisper_model_class, [segment], work, [])

        transcriber.transcribe("a.wav", total_duration_seconds=120.0)

        # Only the closing report at the end, not one for the segment itself.
        assert work == [(120.0, 120.0)]

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_the_wait_before_the_first_segment_is_timed(self, mock_whisper_model_class):
        """
        model.transcribe() runs VAD over the whole file and decodes the first
        window before yielding anything. Measured at 67s on a 15-minute file -
        the longest stretch of a run with nothing to report. It is announced
        when it starts and measured when it ends, so the GUI can name it
        instead of showing a bar that has stopped.
        """
        phases: list = []
        segments = [fake_segment("one", start=0.0, end=30.0)]
        transcriber = self._transcriber(mock_whisper_model_class, segments, [], phases)

        transcriber.transcribe("a.wav", total_duration_seconds=120.0)

        prepare = [seconds for name, seconds in phases if name == ps.WORK_PHASE_PREPARE]
        assert len(prepare) == 2, "prepare should be announced once and measured once"
        assert prepare[0] is ps.WORK_PHASE_STARTED
        assert prepare[1] >= 0

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_a_caller_that_wants_none_of_this_is_unaffected(self, mock_whisper_model_class):
        """
        Both callbacks default to a no-op, so the eval harness and every other
        existing caller construct a Transcriber exactly as before.
        """
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("one")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()

        assert transcriber.transcribe("a.wav", total_duration_seconds=120.0) is not None


class TestNetworkFailureIsDistinguishable:
    """
    "no internet on a first run" and "this model is broken" both used to
    arrive as one message, which tells a user nothing about whether to check
    their connection or pick a different model.
    """

    def test_a_hub_offline_error_is_read_as_a_network_failure(self):
        from speech_to_text.core.transcriber import _is_network_failure

        class LocalEntryNotFoundError(Exception):
            pass

        assert _is_network_failure(LocalEntryNotFoundError("nothing cached"))

    def test_a_socket_failure_wrapped_by_the_hub_is_found_through_its_cause(self):
        """Hub failures usually arrive wrapped, with the real error as cause."""
        from speech_to_text.core.transcriber import _is_network_failure

        class ConnectionError_(Exception):
            pass

        ConnectionError_.__name__ = "ConnectionError"
        wrapper = RuntimeError("could not fetch")
        wrapper.__cause__ = ConnectionError_("name resolution failed")

        assert _is_network_failure(wrapper)

    def test_a_missing_repo_is_not_a_network_failure(self):
        """
        A 404 reached the network perfectly well. Telling the user to check
        their connection would send them looking in the wrong place.
        """
        from speech_to_text.core.transcriber import _is_network_failure

        class HfHubHTTPError(Exception):
            pass

        class RepositoryNotFoundError(HfHubHTTPError):
            pass

        assert not _is_network_failure(RepositoryNotFoundError("404"))

    def test_an_ordinary_failure_is_not_a_network_failure(self):
        from speech_to_text.core.transcriber import _is_network_failure

        assert not _is_network_failure(ValueError("unsupported compute type"))

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_load_model_records_which_kind_of_failure_it_was(self, mock_whisper_model_class):
        class LocalEntryNotFoundError(Exception):
            pass

        mock_whisper_model_class.side_effect = LocalEntryNotFoundError("offline")
        transcriber = Transcriber()

        assert transcriber.load_model() is False
        assert transcriber.load_failed_on_network is True

    @patch("speech_to_text.core.transcriber.WhisperModel")
    def test_a_broken_model_is_not_blamed_on_the_network(self, mock_whisper_model_class):
        mock_whisper_model_class.side_effect = ValueError("bad weights")
        transcriber = Transcriber()

        assert transcriber.load_model() is False
        assert transcriber.load_failed_on_network is False
