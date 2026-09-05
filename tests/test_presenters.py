"""
Tests for gui/presenters/ - the Qt-free half of the GUI's decisions.

The reason this file exists at all is the thing its first test asserts: the
decisions that shape a transcription run used to be reachable only through
a live MainWindow, which means a QApplication, which means these were slow
integration tests pretending to be unit tests. Nothing here may construct a
QApplication or a widget, and nothing here may touch real hardware - the
device recommender is injected, so a machine with or without an NVIDIA GPU
runs the same assertions.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import speech_to_text
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.gui.presenters import (
    TranscriptionRequest,
    build_file_summary,
    build_transcription_request,
)


class FakeHardware:
    """A stand-in for HardwareDetector's one relevant method.

    The real detector probes the machine it is constructed on (nvidia-smi,
    core count, RAM), so a test using it would assert different things on
    different machines - and could never exercise the "cuda" branch at all
    on this development box.
    """

    def __init__(self, device: str = "cpu", reason: str = "stub reason"):
        self._recommendation = (device, reason)
        self.calls = 0

    def get_device_recommendation(self) -> tuple[str, str]:
        self.calls += 1
        return self._recommendation


def fake_translate(key: str, **params) -> str:
    """Renders a key/params pair visibly, so a test can assert on both."""
    rendered = ",".join(f"{name}={value}" for name, value in sorted(params.items()))
    return f"<{key}:{rendered}>"


def build(**overrides) -> TranscriptionRequest:
    """The builder with sensible defaults, so each test states only its point."""
    kwargs = {
        "files": ["C:/audio/meeting.m4a"],
        "model": "small",
        "durations": [12.5],
        "hardware": FakeHardware(),
        "identify_speakers": True,
        "num_speakers": 2,
        "translate": fake_translate,
    }
    kwargs.update(overrides)
    return build_transcription_request(**kwargs)  # type: ignore[arg-type]


def test_the_presenter_package_imports_without_pyqt5_ever_being_loaded():
    """
    The entire point of the package. Checked in a subprocess with PyQt5
    poisoned at the import hook rather than by inspecting sys.modules in
    this one, because pytest collects the rest of the suite into the same
    interpreter and PyQt5 will already be loaded by the time this runs -
    an in-process check would either be vacuous or fail for the wrong
    reason. A poisoned meta_path entry also catches an indirect pull (via
    gui.i18n, say), which a source-text grep would not.
    """
    program = textwrap.dedent(
        """
        import sys

        class Poison:
            def find_module(self, name, path=None):
                if name == "PyQt5" or name.startswith("PyQt5."):
                    raise AssertionError("presenter pulled in " + name)
                return None

            def find_spec(self, name, path=None, target=None):
                return self.find_module(name, path)

        sys.meta_path.insert(0, Poison())
        import speech_to_text.gui.presenters.transcription  # noqa: F401
        assert "PyQt5" not in sys.modules
        print("clean")
        """
    )
    # src-layout: the package is only importable because pytest.ini puts
    # src/ on the path, and a bare subprocess inherits none of that.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(speech_to_text.__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_a_single_file_is_summarised_by_its_bare_filename():
    """
    One file fits in the step 3 header, and the filename is the most useful
    thing to show - the directory it came from is not.
    """
    request = build(files=["C:/some/deep/path/meeting.m4a"])
    assert request.file_summary == "meeting.m4a"


def test_several_files_are_summarised_by_a_translated_count():
    """
    A batch's names would overflow the header, so it collapses to a count -
    and that count is a translated string, because the UI may be Hebrew.
    The key and the count are what the view's `t` will actually receive.
    """
    request = build(files=["a.m4a", "b.mp3", "c.wav"])
    assert request.file_summary == "<files_count_label:count=3>"


def test_an_empty_selection_still_summarises_as_a_count_rather_than_crashing():
    """
    The view guards against starting with nothing selected, but the builder
    is pure and should not be the thing that raises if that guard ever
    moves - zero files is the count branch, not an IndexError.
    """
    request = build(files=[])
    assert request.file_summary == "<files_count_label:count=0>"


def test_the_summary_helper_is_usable_on_its_own_without_the_full_builder():
    """build_file_summary is public because the header text is the one
    decision a caller might want without also deciding on a device."""
    assert build_file_summary(["x/y.wav"], fake_translate) == "y.wav"
    assert build_file_summary(["a", "b"], fake_translate) == "<files_count_label:count=2>"


def test_the_device_and_its_reason_come_straight_from_the_injected_detector():
    """
    Nothing here second-guesses the hardware layer: whatever
    get_device_recommendation() says is what the run uses, and the reason
    string travels along only so the view can log it.
    """
    request = build(hardware=FakeHardware("cuda", "NVIDIA GPU detected: A100"))
    assert request.device == "cuda"
    assert request.device_reason == "NVIDIA GPU detected: A100"


def test_the_detector_is_consulted_exactly_once_per_request():
    """
    The probe is not free (it can shell out to nvidia-smi on a cold
    detector), and two calls could in principle disagree - one request must
    mean one answer.
    """
    hardware = FakeHardware()
    build(hardware=hardware)
    assert hardware.calls == 1


def test_the_cpu_recommendation_is_carried_through_unchanged():
    """The overwhelmingly common path, and the one the app shipped with as a
    hardcoded literal before the recommendation was wired in."""
    request = build(hardware=FakeHardware("cpu", "Using CPU (8 cores, 32.0GB RAM)"))
    assert request.device == "cpu"
    assert request.device_reason == "Using CPU (8 cores, 32.0GB RAM)"


def test_the_speaker_settings_reach_the_options_object_intact():
    """
    identify_speakers and num_speakers are the two things the model step
    actually lets the user change, and they are the only fields the view
    used to set on TranscriptionOptions - a silent default here would mean
    diarizing a two-person interview as if the count were unknown.
    """
    request = build(identify_speakers=False, num_speakers=5)
    assert isinstance(request.options, TranscriptionOptions)
    assert request.options.identify_speakers is False
    assert request.options.num_speakers == 5


def test_an_unknown_speaker_count_is_passed_through_as_the_sentinel():
    """-1 means "infer it" downstream, so it must not be normalised away."""
    request = build(num_speakers=-1)
    assert request.options.num_speakers == -1


def test_the_options_object_leaves_every_other_field_at_its_default():
    """
    The view only ever set the two speaker fields; model, device and
    durations travel to TranscriptionThread as explicit arguments instead.
    Setting them here as well would be a behaviour change wearing a
    refactor's clothes.
    """
    request = build(model="large-v3", durations=[9.0])
    defaults = TranscriptionOptions()
    assert request.options.model_size == defaults.model_size
    assert request.options.device == defaults.device
    assert request.options.audio_durations == []


def test_every_new_request_gets_its_own_options_object():
    """Two runs in one session must not share mutable state."""
    first = build()
    second = build()
    assert first.options is not second.options


def test_the_files_and_durations_are_copied_rather_than_aliased():
    """
    The caller's lists are live widget state (FileSelectStep keeps editing
    them as the user adds and removes files). A request is a snapshot of a
    decision already taken, so a later edit must not rewrite a run that has
    already started.
    """
    files = ["a.m4a", "b.m4a"]
    durations = [1.0, 2.0]
    request = build(files=files, durations=durations)

    files.append("c.m4a")
    durations.append(3.0)

    assert request.files == ["a.m4a", "b.m4a"]
    assert request.durations == [1.0, 2.0]


def test_the_model_and_durations_are_carried_through_in_order():
    """
    durations are positional: entry n is the length of file n, and the
    worker's duration-weighted progress arithmetic depends on that pairing.
    """
    request = build(files=["a.m4a", "b.m4a"], durations=[60.0, 30.0], model="medium")
    assert request.model == "medium"
    assert request.durations == [60.0, 30.0]


def test_the_request_is_frozen_so_the_view_cannot_edit_a_decision_after_the_fact():
    """
    A request describes a run that is about to start. Mutating it would
    silently desynchronise what the header says from what the thread got.
    """
    request = build()
    try:
        request.device = "cuda"  # type: ignore[misc]
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("TranscriptionRequest should be immutable")
