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

import pytest

import speech_to_text
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.gui.presenters import (
    TimeEstimator,
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


class FakeClock:
    """A monotonic clock the test drives by hand.

    TimeEstimator takes `now` on every call rather than reading a clock, so a
    forty-minute run is exercised in microseconds and the assertions are about
    arithmetic instead of about timing.
    """

    def __init__(self, now: float = 1000.0):
        self.now = now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class TestTimeEstimatorHasNothingToSayYet:
    """
    Every case where the honest answer is "not known", and why each is real.

    The formula this replaces had no such answer: elapsed * (100 - pct) / pct
    always produced a number, including through the 67s at a fixed 5% that a
    measured run actually contains.
    """

    def test_before_anything_is_decoded(self):
        """The model is still loading. Nothing has been measured at all."""
        estimator = TimeEstimator()
        assert estimator.remaining(1000.0) is None

    def test_while_too_little_is_decoded_to_mean_anything(self):
        """
        faster-whisper releases its first segments in a burst when the first
        30s window completes, so a rate taken from them reflects the burst
        rather than the pace. One report of 10s of audio is not a measurement.
        """
        clock = FakeClock()
        estimator = TimeEstimator()
        estimator.note_work(10.0, 900.0, clock.now)
        clock.advance(12.0)

        assert estimator.rate(clock.now) is None
        assert estimator.remaining(clock.now) is None

    def test_during_a_first_tail_of_unknown_length(self):
        """
        Diarization's leftover after transcription reports no progress of its
        own, so its length is not knowable until it ends. With nothing measured
        to predict it from, a number would be an invention - and a number that
        then sat at zero is the exact behaviour being removed.
        """
        clock = FakeClock()
        estimator = TimeEstimator()
        estimator.note_file_started(1)
        # The batch starts working, THEN audio comes in - the real order, and
        # the one that leaves a measured interval to divide by.
        estimator.note_work_started(clock.now)
        clock.advance(900.0)
        estimator.note_work(900.0, 900.0, clock.now)
        assert estimator.remaining(clock.now) is not None

        estimator.note_wait_started(clock.now)
        assert estimator.remaining(clock.now) is None


class TestTimeEstimatorMeasures:
    def test_the_rate_is_wall_clock_over_audio(self):
        clock = FakeClock()
        estimator = TimeEstimator()
        estimator.note_work(100.0, 900.0, clock.now)
        clock.advance(120.0)
        estimator.note_work(200.0, 900.0, clock.now)

        # 120s of wall clock bought 200s of audio, counted from the first
        # report - so 0.6s per audio-second, and 700s of audio left.
        assert estimator.rate(clock.now) == pytest.approx(0.6)
        assert estimator.remaining(clock.now) == pytest.approx(420.0)

    def test_model_loading_is_not_folded_into_the_rate(self):
        """
        A first-run model download is tens of minutes; a warm cache is
        seconds. Either way it happens once, before any audio is decoded, so
        charging it against audio-seconds would poison every number derived
        from the rate - badly on the first file, and for the whole run.
        """
        clock = FakeClock()
        estimator = TimeEstimator()
        clock.advance(1200.0)  # twenty minutes of downloading

        estimator.note_work(100.0, 200.0, clock.now)
        clock.advance(100.0)
        estimator.note_work(200.0, 200.0, clock.now)

        assert estimator.rate(clock.now) == pytest.approx(0.5)

    def test_it_converges_as_the_run_goes_on(self):
        """
        The property that matters in practice. Per-file throughput really does
        vary - measured at 1.19x realtime on one file and 0.96x on the next in
        the same batch - so the estimate must settle toward the truth rather
        than lock in whatever the first minute suggested.
        """
        clock = FakeClock()
        estimator = TimeEstimator()
        total = 1000.0
        true_rate = 0.8

        estimator.note_work(0.0, total, clock.now)
        errors = []
        for audio in range(100, 901, 100):
            clock.advance(100 * true_rate)
            estimator.note_work(float(audio), total, clock.now)
            remaining = estimator.remaining(clock.now)
            truth = (total - audio) * true_rate
            errors.append(abs(remaining - truth))

        assert errors[-1] <= errors[0]
        assert errors[-1] == pytest.approx(0.0, abs=1.0)

    def test_a_position_that_arrives_out_of_order_does_not_move_it_backwards(self):
        """
        Positions cross a process boundary. The worker sends them in order,
        but an estimate that DEPENDS on that would turn one stray message
        into a rate that jumps rather than settles.
        """
        clock = FakeClock()
        estimator = TimeEstimator()
        estimator.note_work(100.0, 900.0, clock.now)
        clock.advance(100.0)
        estimator.note_work(300.0, 900.0, clock.now)
        estimator.note_work(200.0, 900.0, clock.now)

        assert estimator.audio_done == 300.0


class TestTimeEstimatorAccountsForTheTail:
    """
    Whatever diarization has left once transcription has finished.

    On this hardware that is nothing - diarization hides completely underneath
    transcription - so these drive the estimator directly rather than through
    a real run. Future files' tails need no term of their own: the rate is
    wall clock over audio, so a completed file's tail is already amortised
    into it. Only the tail being waited out right now sits outside, because
    that file's audio has already been counted as done.
    """

    @staticmethod
    def _after_one_measured_tail(clock):
        """One 900s file transcribed at 1.0x, followed by a 90s tail."""
        estimator = TimeEstimator()
        estimator.note_file_started(1)
        estimator.note_work(0.0, 1800.0, clock.now)
        clock.advance(900.0)
        estimator.note_work(900.0, 1800.0, clock.now)

        estimator.note_wait_started(clock.now)
        clock.advance(90.0)
        estimator.note_wait_finished(90.0)
        return estimator

    def test_a_measured_tail_predicts_the_next_one_before_it_starts(self):
        """
        The tail is charged while the file is still decoding, not once the
        wait begins. A file owes its tail at the end of its own decoding, so
        charging it only at the boundary makes the readout fall to zero as the
        last segments arrive and then jump back up - which is how this was
        written first, and what replaying a real run's timings caught.
        """
        clock = FakeClock()
        estimator = self._after_one_measured_tail(clock)

        estimator.note_file_started(2)
        clock.advance(900.0)
        estimator.note_work(1800.0, 1800.0, clock.now)
        before = estimator.remaining(clock.now)

        estimator.note_wait_started(clock.now)
        after = estimator.remaining(clock.now)

        # 900s of audio bought a 90s tail, so 0.1s of tail per audio-second;
        # file 2 is 900s too, so it owes about 90s - and crossing into the
        # wait must not change the number.
        assert before == pytest.approx(90.0, abs=1.0)
        assert after == pytest.approx(before, abs=1.0)

    def test_a_paid_tail_is_not_charged_again(self):
        """
        Once a file has been waited out, its audio owes nothing more. Left
        uncorrected this reads as a run that is finished still claiming
        minutes to go, which the replay of a real batch showed as 231s
        remaining at the moment the last file was written out.
        """
        clock = FakeClock()
        estimator = self._after_one_measured_tail(clock)

        estimator.note_file_started(2)
        clock.advance(900.0)
        estimator.note_work(1800.0, 1800.0, clock.now)
        estimator.note_wait_started(clock.now)
        clock.advance(90.0)
        estimator.note_wait_finished(90.0)

        assert estimator.remaining(clock.now) == pytest.approx(0.0, abs=1.0)

    def test_the_predicted_tail_counts_down_while_it_is_waited_out(self):
        clock = FakeClock()
        estimator = self._after_one_measured_tail(clock)

        estimator.note_file_started(2)
        clock.advance(900.0)
        estimator.note_work(1800.0, 1800.0, clock.now)
        estimator.note_wait_started(clock.now)

        first = estimator.remaining(clock.now)
        clock.advance(30.0)
        second = estimator.remaining(clock.now)

        assert second < first
        assert second == pytest.approx(first - 30.0, abs=1.0)

    def test_a_tail_that_runs_long_never_counts_below_zero(self):
        """
        The prediction is a measurement from another file, so it can be short.
        A negative remainder would print as a countdown running backwards past
        zero; the run simply finishes when it finishes.
        """
        clock = FakeClock()
        estimator = self._after_one_measured_tail(clock)

        estimator.note_file_started(2)
        clock.advance(900.0)
        estimator.note_work(1800.0, 1800.0, clock.now)
        estimator.note_wait_started(clock.now)
        clock.advance(600.0)

        assert estimator.remaining(clock.now) >= 0.0

    def test_a_tail_is_charged_against_the_audio_of_the_file_it_followed(self):
        """
        Per audio-second, not per file: a batch of one short and one long
        recording would otherwise predict the same tail for both, and the tail
        scales with how much audio diarization had to get through.
        """
        clock = FakeClock()
        estimator = self._after_one_measured_tail(clock)

        # 90s of tail after 900s of audio.
        assert estimator._waits.rate == pytest.approx(0.1)


class TestAgainstARealRun:
    """
    The estimator replayed against timings taken from an actual batch.

    Every number below is read out of speech_to_text.log for the run of
    2026-08-22: two files of 900.0s and 765.5s, ivrit-turbo, speaker
    identification on, four cores. The run took 38m 43s end to end and the
    model-select screen had predicted 1h 6m.

    The unit tests above each pin one rule. This pins the thing that actually
    matters and that no single rule guarantees: that on real timings the
    estimate closes on the truth instead of drifting away from it. Both flaws
    the first version of this code shipped with - a tail charged twice, and a
    readout that fell to zero before the last wait - were found by running
    exactly this and looking at the error column, not by reasoning about it.
    """

    # (audio seconds, transcribe start, transcribe end, wait end), seconds
    # from the moment the run began.
    FILES = [
        (900.0, 8.5, 1084.1, 1363.8),
        (765.5, 1365.9, 2099.4, 2321.7),
    ]
    RUN_END = 2322.3
    SEGMENTS_PER_FILE = 215

    def _replay(self):
        """Yield (error, truth) at intervals through the whole run."""
        estimator = TimeEstimator()
        batch_audio = sum(audio for audio, *_rest in self.FILES)
        samples = []

        def sample(now):
            estimate = estimator.remaining(now)
            if estimate is not None:
                samples.append((estimate - (self.RUN_END - now), self.RUN_END - now))

        for index, (audio, start, end, wait_end) in enumerate(self.FILES, start=1):
            estimator.note_file_started(index)
            done_before = sum(f[0] for f in self.FILES[: index - 1])
            # faster-whisper's VAD pass and first window, before segment one.
            first_segment_at = start + 25.0

            for i in range(1, self.SEGMENTS_PER_FILE + 1):
                fraction = i / self.SEGMENTS_PER_FILE
                now = first_segment_at + (end - first_segment_at) * fraction
                estimator.note_work(done_before + audio * fraction, batch_audio, now)
                if i % 43 == 0:
                    sample(now)

            estimator.note_wait_started(end)
            sample((end + wait_end) / 2)
            estimator.note_wait_finished(wait_end - end)
            sample(wait_end)

        return samples

    def test_the_estimate_closes_on_the_truth(self):
        samples = self._replay()
        assert len(samples) > 8

        # The last third of the run, by which point both files' behaviour has
        # been measured, must be closer than the first third was.
        third = len(samples) // 3
        early = max(abs(error) for error, _truth in samples[:third])
        late = max(abs(error) for error, _truth in samples[-third:])
        assert late < early

    def test_it_is_within_a_minute_by_the_end(self):
        """
        The number a user reads in the last stretch, when it matters most and
        when the old formula was at its worst: replaying the same timings
        through elapsed * (100 - percent) / percent leaves it 47s out at the
        moment the run has actually finished, and 180s out shortly before.
        """
        final_error, final_truth = self._replay()[-1]

        assert final_truth < 5.0, "the last sample should be at the end of the run"
        assert abs(final_error) < 60.0

    def test_it_never_claims_a_finished_run_still_has_minutes_to_go(self):
        for error, truth in self._replay():
            assert error + truth >= 0.0, "the estimate went negative"
            if truth < 10.0:
                assert error < 60.0


class TestSegmentsArriveInBursts:
    """
    faster-whisper decodes a whole 30s window and then yields every segment in
    it at once, so audio_done jumps and then sits still for seconds at a time.

    Both of the defects pinned here were invisible in the unit tests and in the
    replay of logged timings, and showed up the first time the real pipeline
    was run end to end: the replay interpolates segment arrivals evenly, which
    is exactly the assumption that hides them.
    """

    @staticmethod
    def _mid_run(clock):
        """Anchored, with one burst of 60s of audio 30s ago, 240s still to go."""
        estimator = TimeEstimator()
        estimator.note_file_started(1)
        estimator.note_work_started(clock.now)
        clock.advance(30.0)
        estimator.note_work(60.0, 300.0, clock.now)
        return estimator

    def test_the_rate_does_not_drift_between_bursts(self):
        """
        Measured against "now" the rate climbs through every gap and drops
        back on each burst, because the clock moves while audio_done does not.
        Seen live, the readout counted UP from 1:43 to 2:00 and then fell to
        0:52 on the next burst. A rate is a measurement over completed work,
        so the window ends where the work ended.
        """
        clock = FakeClock()
        estimator = self._mid_run(clock)

        first = estimator.rate(clock.now)
        clock.advance(10.0)
        assert estimator.rate(clock.now) == first
        clock.advance(10.0)
        assert estimator.rate(clock.now) == first

    def test_the_readout_still_counts_down_inside_a_gap(self):
        """
        A rate that ignores the gap must not leave the number frozen between
        bursts - it would step every 10 or 15 seconds and look stuck in
        between. Time already spent on the chunk being decoded is time served
        against it, so it comes off the estimate second by second.
        """
        clock = FakeClock()
        estimator = self._mid_run(clock)

        first = estimator.remaining(clock.now)
        clock.advance(10.0)
        second = estimator.remaining(clock.now)

        assert second == pytest.approx(first - 10.0, abs=0.01)

    def test_a_tail_inside_the_gap_is_not_mistaken_for_decoding(self):
        """
        A file's tail falls between its last work report and the next file's
        first one, so it lands squarely in that gap. Counted as time served,
        a diarization wait knocks its whole length off the estimate the instant
        it ends - the estimate falls by minutes for work that had not
        happened.
        """
        clock = FakeClock()
        estimator = self._mid_run(clock)
        before = estimator.remaining(clock.now)

        estimator.note_wait_started(clock.now)
        clock.advance(280.0)
        estimator.note_wait_finished(280.0)

        after = estimator.remaining(clock.now)
        # The decode half of the estimate is untouched by the wait; only the
        # tail term, now measured, is added to it.
        assert after >= before


class TestItWaitsForEnoughWorkToBeRepresentative:
    """
    Honest arithmetic over unrepresentative data is its own kind of wrong.

    Early decoding is genuinely slower than late decoding: diarization runs on
    a thread alongside transcription and competes for the same cores until it
    finishes, so the opening of the first file is the least representative
    stretch of a run. Measured on a real 1665s batch, the rate read 1.838
    after 85s of audio and 1.056 by the end - and projecting from the 85s
    reading put the first number the user saw at 48:13 against a true 26:26.

    Nothing about that number was miscalculated. There was simply not yet
    enough of the batch behind it to project from, which is a thing the
    estimator can check.
    """

    @staticmethod
    def _decoded(audio_total, audio_done, clock):
        estimator = TimeEstimator()
        estimator.note_file_started(1)
        estimator.note_work_started(clock.now)
        clock.advance(audio_done)
        estimator.note_work(audio_done, audio_total, clock.now)
        return estimator

    def test_a_sliver_of_a_long_batch_is_not_enough(self):
        clock = FakeClock()
        # 85s of a 1665s batch: the reading that produced 48:13.
        estimator = self._decoded(1665.0, 85.0, clock)

        assert estimator.rate(clock.now) is None
        assert estimator.remaining(clock.now) is None

    def test_a_tenth_of_the_batch_is(self):
        clock = FakeClock()
        estimator = self._decoded(1665.0, 200.0, clock)

        assert estimator.remaining(clock.now) is not None

    def test_a_short_batch_is_held_to_the_floor_not_the_share(self):
        """
        A tenth of a four-minute batch is 24 seconds, which is less than one
        of faster-whisper's 30s windows - the burst problem the floor exists
        for. The floor wins whenever it is the larger of the two.
        """
        clock = FakeClock()
        assert self._decoded(270.0, 40.0, clock).remaining(clock.now) is None

        clock = FakeClock()
        assert self._decoded(270.0, 70.0, clock).remaining(clock.now) is not None

    def test_a_very_long_batch_does_not_stay_silent_for_an_hour(self):
        """
        A tenth of ten hours of audio is an hour, and an hour of "calculating"
        would be worse than an imperfect number. The share is capped.
        """
        clock = FakeClock()
        estimator = self._decoded(36000.0, 310.0, clock)

        assert estimator.remaining(clock.now) is not None
