"""
Tests for configuration module.
"""

import os

from speech_to_text import config
from speech_to_text.config import paths


class TestConfig:
    """Test configuration module."""

    def test_models_configuration(self):
        """Test that all models are configured correctly."""
        assert len(config.MODELS) == 7
        for name in ("tiny", "base", "small", "medium", "large", "ivrit-turbo", "ivrit-large"):
            assert name in config.MODELS

    def test_model_has_required_keys(self):
        """Test that all models have required keys."""
        required_keys = {
            "repo",
            "name",
            "description",
            "pros",
            "cons",
            "time_estimate",
            "ram_required",
            "accuracy_score",
            "best_for",
            "recommended",
        }

        for model_name, model_info in config.MODELS.items():
            assert set(model_info.keys()) >= required_keys, f"Model {model_name} missing keys"

    def test_large_is_pinned_to_an_explicit_version(self):
        """
        The bare "large" alias has pointed at different Whisper versions across
        faster-whisper releases, which silently changed which model ran.
        """
        assert config.MODELS["large"]["repo"] == "large-v3"

    def test_hebrew_models_point_at_ivrit_repos(self):
        assert config.MODELS["ivrit-turbo"]["repo"] == "ivrit-ai/whisper-large-v3-turbo-ct2"
        assert config.MODELS["ivrit-large"]["repo"] == "ivrit-ai/whisper-large-v3-ct2"

    def test_default_model_is_hebrew_tuned(self):
        """A Hebrew transcription app should not default to a general model."""
        assert config.DEFAULT_MODEL.startswith("ivrit-")

    def test_default_model_exists(self):
        """Test that default model is configured."""
        assert config.DEFAULT_MODEL in config.MODELS

    def test_only_one_recommended_model(self):
        """Test that exactly one model is marked as recommended."""
        recommended = [m for m in config.MODELS.values() if m["recommended"]]
        assert len(recommended) == 1

    def test_app_configuration(self):
        """Test application configuration."""
        assert config.APP_NAME == "Hebrew Audio Transcriber"
        assert config.APP_VERSION == "2.0.0"
        assert config.WINDOW_WIDTH > 0
        assert config.WINDOW_HEIGHT > 0

    def test_supported_formats(self):
        """Test that supported audio formats are defined."""
        assert isinstance(config.SUPPORTED_FORMATS, tuple)
        assert len(config.SUPPORTED_FORMATS) > 0
        assert all(fmt.startswith("*.") for fmt in config.SUPPORTED_FORMATS)

    def test_required_packages_covers_every_import_the_app_cannot_start_without(self):
        """
        The list has to be complete, or the startup check is worse than absent.

        It used to hold only PyQt5 and tqdm, on the reasoning that
        faster_whisper was "lazy-loaded". It is not lazy: main.py imports it
        during startup, before PyQt5, to fix a DLL load order. So the check
        passed on an interpreter with no faster-whisper and the app died
        moments later on the import, having first pip-installed PyQt5 into
        whatever Python it happened to be running on.

        Nothing here is imported to check it - see
        core/dependencies.ensure_dependencies, which uses find_spec precisely
        so that this list cannot dictate the DLL load order.
        """
        required = config.REQUIRED_PACKAGES
        for name in ("PyQt5", "faster_whisper", "sherpa_onnx", "av", "psutil", "tqdm"):
            assert name in required, f"{name} is imported at startup but not checked for"

    def test_transcription_settings(self):
        """Test transcription configuration."""
        assert config.LANGUAGE == "he"
        assert config.BEAM_SIZE > 0
        assert config.COMPUTE_TYPE in ["int8", "int16", "float16", "float32"]
        assert isinstance(config.VAD_FILTER, bool)
        assert isinstance(config.FORMAT_OUTPUT, bool)

    def test_model_accuracy_progression(self):
        """Test that accuracy scores increase with model size."""
        models = list(config.MODELS.keys())
        scores = [config.MODELS[m]["accuracy_score"] for m in models]

        # Check that scores are in increasing order
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"Accuracy should increase: {models[i]}/{scores[i]} -> {models[i + 1]}/{scores[i + 1]}"
            )


class TestOutputPathFor:
    """
    output_path_for() replaced the fixed OUTPUT_FILENAME so batches of
    different recordings stop colliding on one transcription.txt - see
    config.OUTPUT_FILENAME_TEMPLATE.
    """

    def test_single_file_is_named_after_its_own_stem(self):
        path = config.output_path_for([os.path.join("dir", "meeting.wav")])
        assert os.path.dirname(path) == "dir"
        assert os.path.basename(path) == "meeting_transcription.html"

    def test_multiple_files_are_named_after_the_shared_folder(self):
        path = config.output_path_for(
            [
                os.path.join("recordings", "a.wav"),
                os.path.join("recordings", "b.wav"),
            ]
        )
        assert os.path.dirname(path) == "recordings"
        assert os.path.basename(path) == "recordings_transcription.html"

    def test_a_dotted_filename_keeps_its_whole_stem(self):
        """splitext splits on the LAST dot - "a.b.wav" must not lose "b"."""
        path = config.output_path_for([os.path.join("dir", "a.b.wav")])
        assert os.path.basename(path) == "a.b_transcription.html"

    def test_different_inputs_give_different_paths(self):
        one = config.output_path_for([os.path.join("dir", "meeting.wav")])
        two = config.output_path_for([os.path.join("dir", "other.wav")])
        assert one != two

        single = config.output_path_for([os.path.join("dir", "a.wav")])
        batch = config.output_path_for(
            [
                os.path.join("dir", "a.wav"),
                os.path.join("dir", "b.wav"),
            ]
        )
        assert single != batch

    def test_output_is_written_beside_the_first_input(self):
        path = config.output_path_for(
            [
                os.path.join("here", "a.wav"),
                os.path.join("here", "b.wav"),
            ]
        )
        assert os.path.dirname(path) == "here"


class TestModelDownloadRoot:
    """
    config.MODEL_DOWNLOAD_ROOT / resolve_model_download_root() replaced the
    literal "./whisper_models" that used to be passed straight to
    WhisperModel(download_root=...) in core/transcriber.py. That literal was
    relative to the process's CURRENT WORKING DIRECTORY - harmless only as
    long as the app was launched from the repo root, which the installed
    `speech-to-text` console script (pyproject.toml's [project.scripts])
    does not guarantee. A launch from elsewhere couldn't find the existing
    cache and silently re-downloaded it - 5.9 GB on this machine.

    These pin the three-step resolution order (env override, then an
    existing whisper_models/ beside the package, then a per-user data
    directory) and the cwd-independence that order exists to guarantee.
    """

    def test_env_override_wins(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom_models"
        monkeypatch.setenv("SPEECH_TO_TEXT_MODEL_DIR", str(custom))

        result = config.resolve_model_download_root()

        assert os.path.abspath(result) == os.path.abspath(str(custom))
        assert os.path.isdir(result)  # created if it didn't already exist

    def test_existing_whisper_models_beside_package_beats_per_user_fallback(
        self, monkeypatch, tmp_path
    ):
        """
        This is the branch that protects the 5.9 GB already on disk: an
        existing whisper_models/ next to the package must win, not fall
        through to a fresh, empty per-user directory that would make
        gui/steps/model_select.py's _model_is_downloaded() report every
        already-cached model as "not downloaded".
        """
        monkeypatch.delenv("SPEECH_TO_TEXT_MODEL_DIR", raising=False)

        repo_root = tmp_path / "repo_root"
        package_dir = repo_root / "speech_to_text"
        package_dir.mkdir(parents=True)
        beside_package = repo_root / "whisper_models"
        beside_package.mkdir()
        # config.paths, not config: the resolution reads the __file__ of the
        # submodule the function actually lives in, and it walks up from the
        # package root - so the fake path has to sit in the config/ subpackage
        # exactly as the real one does.
        monkeypatch.setattr(paths, "__file__", str(package_dir / "config" / "paths.py"))

        # Point the per-user fallback somewhere else entirely, so a wrong
        # answer (falling through instead of finding beside_package) is
        # distinguishable from the right one rather than accidentally equal.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

        result = config.resolve_model_download_root()

        assert os.path.abspath(result) == os.path.abspath(str(beside_package))

    def test_result_is_absolute_and_stable_across_working_directory(self, monkeypatch, tmp_path):
        """
        The actual regression test for this bug: MODEL_DOWNLOAD_ROOT must
        not change with the working directory. Against the old code (the
        bare literal "./whisper_models" passed directly to WhisperModel,
        with no resolve step at all) this test fails outright - resolving
        that literal with os.path.abspath in two different working
        directories gives two different answers, exactly the bug this
        exists to pin.
        """
        monkeypatch.delenv("SPEECH_TO_TEXT_MODEL_DIR", raising=False)
        # No whisper_models/ beside this fake package, so resolution falls
        # through to the per-user branch - which must be equally stable.
        package_dir = tmp_path / "fake_pkg" / "speech_to_text"
        package_dir.mkdir(parents=True)
        # config.paths, not config: the resolution reads the __file__ of the
        # submodule the function actually lives in, and it walks up from the
        # package root - so the fake path has to sit in the config/ subpackage
        # exactly as the real one does.
        monkeypatch.setattr(paths, "__file__", str(package_dir / "config" / "paths.py"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

        cwd_a = tmp_path / "cwd_a"
        cwd_b = tmp_path / "cwd_b"
        cwd_a.mkdir()
        cwd_b.mkdir()

        monkeypatch.chdir(cwd_a)
        result_a = config.resolve_model_download_root()

        monkeypatch.chdir(cwd_b)
        result_b = config.resolve_model_download_root()

        assert os.path.isabs(result_a)
        assert os.path.isabs(result_b)
        assert result_a == result_b

    def test_module_level_constant_is_absolute(self):
        """MODEL_DOWNLOAD_ROOT (computed once at import time) must already be absolute."""
        assert os.path.isabs(config.MODEL_DOWNLOAD_ROOT)


class TestDiarizationModelsRoot:
    """
    The speaker-model cache must not depend on the working directory.

    It was a bare relative "./diarization_models", so it resolved against
    wherever the process happened to start. run.bat and run.ps1 cd to the
    project first, which hid it - but the console script declared in
    pyproject.toml does not, so `speech-to-text` launched from anywhere else
    re-downloaded 36 MB into that directory, or failed on a read-only one.
    The Whisper cache had the same bug and was fixed; this half was missed.
    """

    def test_the_root_is_absolute(self):
        assert os.path.isabs(config.DIARIZATION_MODELS_ROOT)

    def test_the_root_does_not_move_with_the_working_directory(self, tmp_path, monkeypatch):
        """The whole point: same answer from anywhere."""
        from speech_to_text.config.paths import resolve_diarization_models_root

        monkeypatch.delenv("SPEECH_TO_TEXT_DIARIZATION_DIR", raising=False)
        here = os.getcwd()
        try:
            first = resolve_diarization_models_root()
            os.chdir(tmp_path)
            second = resolve_diarization_models_root()
        finally:
            os.chdir(here)

        assert first == second, "the cache location changed with the working directory"

    def test_an_explicit_override_wins_and_is_made_absolute(self, tmp_path, monkeypatch):
        """A relative override is still the caller's mistake to be protected from."""
        from speech_to_text.config.paths import resolve_diarization_models_root

        monkeypatch.setenv("SPEECH_TO_TEXT_DIARIZATION_DIR", str(tmp_path / "elsewhere"))
        resolved = resolve_diarization_models_root()

        assert resolved == str(tmp_path / "elsewhere")
        assert os.path.isabs(resolved)

    def test_the_module_uses_the_resolved_root(self):
        """diarization.py must read the resolved value, not re-derive one."""
        from speech_to_text.core import diarization

        assert diarization.MODELS_DIR == config.DIARIZATION_MODELS_ROOT
        assert os.path.isabs(diarization._SEGMENTATION_MODEL)
        assert os.path.isabs(diarization._EMBEDDING_MODEL)

    def test_resolving_does_not_create_the_directory(self, tmp_path, monkeypatch):
        """
        Diarization is optional, so importing must not litter.

        Unlike the Whisper root, which makedirs on import because a
        transcription always needs it, ensure_models() creates this one only
        when it actually fetches something.
        """
        from speech_to_text.config.paths import resolve_diarization_models_root

        target = tmp_path / "not_yet"
        monkeypatch.setenv("SPEECH_TO_TEXT_DIARIZATION_DIR", str(target))
        resolve_diarization_models_root()

        assert not target.exists(), "resolving a path should not create it"
