"""How long is left, computed from what this run has actually done.

The estimate this replaces was one line in gui/steps/transcription.py:

    remaining = elapsed * (100 - percentage) / percentage

which projects time from a position on the progress bar. That is only valid
if every percent of the bar costs the same wall clock, and the bands do not
come close to that. Measured on a 4-core machine, one 15-minute recording
spent 67s at a fixed 5% (faster-whisper's VAD pass, before any segment
exists) and 280s at a fixed 98% (waiting for diarization to finish). During
both, the formula above is being fed a percentage that has stopped moving,
so it either freezes or - worse - keeps projecting from a pace that is no
longer happening. A two-file batch measured a pre-run estimate of 1h 6m
against an actual 38m 43s.

What is used instead is two rates over work the run has genuinely done:

    decode rate = time spent decoding / audio-seconds decoded
    tail rate   = leftover diarization / audio-seconds it followed
    remaining   = audio left * decode rate + audio owing a tail * tail rate

Audio-seconds are the unit because they are what the pipeline is actually
charged for, they are known exactly (a PyAV container probe, not an
estimate - see gui/audio_utils.py), and they add up across a batch without
needing a scale. The decode rate is otherwise an all-in average: everything
between one segment and the next is inside it - VAD retries, diarization
running underneath, the checkpoint write - so per-file overhead is absorbed
by measurement rather than predicted by a constant.

The two rates are kept apart for one reason: a tail is owed per file, at the
END of that file, while the decode rate is a per-audio-second average over
the whole run. Rolling tails into the single average was tried against a
real run's timings and is worse in both directions - it over-predicts right
after a tail finishes (the tail just measured is charged again to every file
still to come) and under-predicts as a file's decoding ends (the tail that
file is about to owe has not been charged at all, so the readout falls to
zero and then jumps back up when the wait begins).

Nothing here guesses. A quantity that has not been measured yet is reported
as unknown, and the caller says so, because "calculating" is worth more to
someone watching a progress screen than a number that is confidently wrong.

No Qt, on purpose: this is the package's rule (see its __init__), and it is
what lets the arithmetic be tested against a fake clock in milliseconds
rather than through a live window.
"""

from dataclasses import dataclass, field

# Below this much decoded audio a rate is noise rather than a measurement:
# faster-whisper emits its first segments in a burst once the first 30s
# window finishes, so a rate taken from the very first report reflects the
# burst, not the pace. Two windows is the same threshold core/calibration.py
# settled on, for the same reason.
MIN_AUDIO_FOR_A_RATE = 60.0


@dataclass
class _WaitMeasurement:
    """How much of diarization was left over after transcription finished.

    Diarization runs on a thread alongside transcription and usually hides
    underneath it, costing nothing. When it does not - a heavier model leaves
    fewer cores for it - what is left over is a stretch at the very end of a
    file with no progress of any kind, measured here at 280s and 222s on the
    two files of one batch. It is charged per audio-second of the file it
    followed, so a later, longer file is predicted to owe proportionally more.
    """

    seconds: float = 0.0
    audio: float = 0.0

    @property
    def rate(self) -> float | None:
        """Leftover seconds per audio-second, or None until something is measured."""
        if self.audio <= 0:
            return None
        return self.seconds / self.audio


@dataclass
class TimeEstimator:
    """Accumulates one run's measurements and answers "how much longer?".

    Fed from the worker's work stream (see core/progress_scale.py). Stateful
    rather than a pure function because the answer depends on the whole run so
    far, not on the latest message - which is exactly what the old formula got
    wrong by recomputing from a single percentage every second.
    """

    audio_total: float = 0.0
    audio_done: float = 0.0

    # Monotonic reading at the first work report. Not the run's start: model
    # loading sits before it and can be twenty minutes on a first download or
    # two seconds on a warm cache, so folding it into a per-audio-second rate
    # would poison every number derived from it.
    _decoding_started_at: float | None = None

    # Audio position when the current file began, so the file's own length is
    # known while its tail is being waited out. Taken from the work stream
    # rather than the durations list the GUI already holds, so there is one
    # source for what counts as done and it cannot disagree with itself.
    _current_file_audio_start: float = 0.0
    _current_file_index: int | None = None

    _waits: _WaitMeasurement = field(default_factory=_WaitMeasurement)
    # (started_at, audio position when it started) while a tail is being
    # waited out, None otherwise.
    _active_wait: tuple[float, float] | None = None

    def _audio_owing_a_tail(self) -> float:
        """Audio whose file has not yet paid its diarization tail.

        The batch minus whatever has already been waited out. Note this is
        NOT "audio still to decode": a file owes its tail at the END of its
        own decoding, so the file being decoded right now still owes one in
        full even when it is nearly finished. That is what stops the readout
        from falling to zero as a file's last segments arrive and then jumping
        back up the moment the wait begins.
        """
        return max(self.audio_total - self._waits.audio, 0.0)

    def note_work(self, audio_done: float, audio_total: float, now: float) -> None:
        """Record an audio position reported by the worker."""
        if self._decoding_started_at is None:
            self._decoding_started_at = now
        # max(), not plain assignment: messages cross a process boundary and a
        # position that went backwards would make the rate jump rather than
        # settle. The worker guarantees monotonicity; this makes the estimate
        # not depend on that guarantee holding.
        self.audio_done = max(self.audio_done, audio_done)
        self.audio_total = max(self.audio_total, audio_total)

    def note_file_started(self, index: int) -> None:
        """Record that file `index` (1-based) is now the one running."""
        if index == self._current_file_index:
            return
        self._current_file_index = index
        self._current_file_audio_start = self.audio_done

    def note_wait_started(self, now: float) -> None:
        """A phase with no progress of its own has begun (the diarization join)."""
        self._active_wait = (now, self.audio_done)

    def note_wait_finished(self, seconds: float) -> None:
        """That phase has ended, having taken `seconds`."""
        started = self._active_wait
        self._active_wait = None
        if started is None:
            return
        _started_at, audio_at_start = started
        file_audio = max(audio_at_start - self._current_file_audio_start, 0.0)
        if file_audio <= 0:
            return
        self._waits.seconds += seconds
        self._waits.audio += file_audio

    def _time_spent_waiting(self, now: float) -> float:
        """Wall clock this run has spent in tails, including one in progress."""
        active = 0.0
        if self._active_wait is not None:
            started_at, _audio = self._active_wait
            active = max(now - started_at, 0.0)
        return self._waits.seconds + active

    def rate(self, now: float) -> float | None:
        """Seconds spent DECODING per second of audio, or None if not yet known.

        Tails are subtracted out rather than averaged in, so this stays a
        measure of decoding alone and the tail term can be added separately
        without charging the same seconds twice (see the module docstring).

        Takes `now` rather than reading a clock, so the whole estimator can be
        driven by a fake one in tests - and so the rate and the estimate built
        from it are always read at the same instant.
        """
        if self._decoding_started_at is None or self.audio_done < MIN_AUDIO_FOR_A_RATE:
            return None
        elapsed = now - self._decoding_started_at - self._time_spent_waiting(now)
        if elapsed <= 0:
            return None
        return elapsed / self.audio_done

    def remaining(self, now: float) -> float | None:
        """Seconds still to go, or None when that is genuinely not known yet.

        None covers three real situations, and each is better said out loud
        than papered over with a number: nothing has been decoded yet (model
        loading, or the VAD pass before the first segment); too little has
        been decoded for a rate to mean anything; or a tail of unknown length
        is being waited out for the first time in this run, with nothing
        measured to predict it from.
        """
        rate = self.rate(now)
        if rate is None:
            return None

        remaining_audio = max(self.audio_total - self.audio_done, 0.0)
        estimate = remaining_audio * rate

        wait_rate = self._waits.rate
        if wait_rate is None:
            if self._active_wait is None:
                # No tail has been measured and none is running. Either this
                # run has none at all (speaker identification off, or
                # diarization finishing underneath transcription every time,
                # which is the common case) or the first one has not happened
                # yet. Nothing to add, and nothing to apologise for.
                return estimate
            # A tail IS running and this run has never measured one. Its
            # length could be seconds or minutes - on a real batch it was
            # 280s - so any number here would be an invention, and a number
            # that then sat at zero for four and a half minutes is exactly
            # the behaviour this change exists to remove.
            return None

        owed = wait_rate * self._audio_owing_a_tail()
        # Time already served against the tail in progress. Floored at zero
        # because the prediction comes from a different file and can simply be
        # short; a countdown running past zero into negative numbers would be
        # a worse lie than an optimistic one.
        return estimate + max(owed - self._time_in_current_wait(now), 0.0)

    def _time_in_current_wait(self, now: float) -> float:
        if self._active_wait is None:
            return 0.0
        started_at, _audio = self._active_wait
        return max(now - started_at, 0.0)
