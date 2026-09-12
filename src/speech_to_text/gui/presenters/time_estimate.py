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

# How much audio has to be decoded before a rate is worth projecting from.
# Three numbers rather than one, because two different things make an early
# rate untrustworthy and they pull opposite ways.
#
# The floor: faster-whisper emits its first segments in a burst once the
# first 30s window finishes, so a rate taken from the very first report
# reflects that burst and not the pace. Two windows is the same threshold
# core/calibration.py settled on, for the same reason.
MIN_AUDIO_FOR_A_RATE = 60.0

# The share: a tenth of the batch, because early decoding is genuinely slower
# than late decoding. Diarization runs on a thread alongside transcription and
# competes for the same cores until it finishes, so the first stretch of the
# first file is the least representative part of a run. Measured on a real
# 1665s batch: the rate read 1.838 after 85s of audio, 1.159 after 287s, and
# 1.056 by the end. Projecting from the 85s reading put the first number a
# user saw at 48:13 against a true 26:26 - honest arithmetic over data that
# was not yet representative, which is its own kind of confidently wrong.
# A tenth pushes that first number to 30:14, still high but no longer absurd.
MIN_SHARE_FOR_A_RATE = 0.10

# The ceiling on that share, so a long batch does not stay silent for an hour
# waiting to reach a tenth of itself. Five minutes of audio is enough to have
# averaged over the contended opening whatever the batch's total length.
MAX_AUDIO_BEFORE_A_RATE = 300.0


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

    # Monotonic reading at the moment this batch began working on its first
    # file. Not the run's start: model loading sits before it and is anywhere
    # from two seconds on a warm cache to tens of minutes on a first download,
    # so folding it into a per-audio-second rate would poison every number
    # derived from it. It happens once, and no amount of audio pays for it.
    #
    # It is also NOT the first work report, which is where this was anchored
    # first and is subtly wrong: faster-whisper releases its first segments in
    # a burst after decoding a whole 30s window, so by the time that report
    # arrives half a minute of audio is already done. Measuring from there
    # while still dividing by ALL the audio counts that half-minute as free -
    # two errors that happen to point opposite ways and cancel by luck rather
    # than by reasoning. Anchoring at the start of the work instead makes the
    # rate mean what it says: every second spent decoding, over every second
    # of audio decoded.
    _decoding_started_at: float | None = None

    # Audio position when the current file began, so the file's own length is
    # known while its tail is being waited out. Taken from the work stream
    # rather than the durations list the GUI already holds, so there is one
    # source for what counts as done and it cannot disagree with itself.
    _current_file_audio_start: float = 0.0
    _current_file_index: int | None = None

    # When audio_done last actually moved. The rate is measured to HERE, not
    # to the caller's "now", because faster-whisper releases its segments in
    # bursts: it decodes a whole 30s window and then yields everything in it
    # at once. Measured against "now", the rate therefore climbs through every
    # gap between bursts and drops back on each one, and the readout visibly
    # counts UP before snapping down - seen live at 1:43 climbing to 2:00 and
    # then falling to 0:52 on the next burst. Dividing only by work that has
    # actually completed makes the rate a measurement again; the gap since is
    # handled by counting down through it, below.
    _last_work_at: float | None = None
    # Tail seconds already measured when audio_done last moved. Everything in
    # _waits.seconds beyond this happened AFTER the last work report, which
    # puts it in the gap since - so it must not be charged to decoding at
    # either end: not subtracted from the rate's window (it is outside it) and
    # not counted as time served against the next chunk (no decoding happened).
    _waited_at_last_work: float = 0.0

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

    def note_work_started(self, now: float) -> None:
        """The batch has begun working on audio, whether or not any is done yet.

        Called for the first phase of the first file - decoding it, or
        faster-whisper's VAD pass over it - which is the first moment after
        the model is loaded that time starts being spent on this batch's
        audio. Everything before it is one-time setup that no amount of audio
        should be charged for.
        """
        if self._decoding_started_at is None:
            self._decoding_started_at = now

    def note_work(self, audio_done: float, audio_total: float, now: float) -> None:
        """Record an audio position reported by the worker."""
        # Fallback anchor. A caller that only feeds work reports still gets a
        # rate, just one that reads the first burst's audio as free - see
        # _decoding_started_at for why that is the worse of the two.
        self.note_work_started(now)
        # max(), not plain assignment: messages cross a process boundary and a
        # position that went backwards would make the rate jump rather than
        # settle. The worker guarantees monotonicity; this makes the estimate
        # not depend on that guarantee holding.
        before = self.audio_done
        self.audio_done = max(self.audio_done, audio_done)
        self.audio_total = max(self.audio_total, audio_total)
        if self.audio_done > before:
            self._last_work_at = now
            self._waited_at_last_work = self._waits.seconds

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

    def _audio_needed_for_a_rate(self) -> float:
        """How much audio must be decoded before projecting from the rate."""
        share = min(self.audio_total * MIN_SHARE_FOR_A_RATE, MAX_AUDIO_BEFORE_A_RATE)
        return max(MIN_AUDIO_FOR_A_RATE, share)

    def rate(self, now: float) -> float | None:
        """Seconds spent DECODING per second of audio, or None if not yet known.

        Measured over completed work only: from the start of the batch's first
        file to the last moment audio_done actually moved, over the audio done
        by then. `now` is accepted so this reads like remaining() and can be
        driven by the same fake clock, but it is deliberately NOT the end of
        the window - see _last_work_at for the burst behaviour that makes
        using it produce a rate that saws up and down rather than settling.

        Tails are subtracted out rather than averaged in, so this stays a
        measure of decoding alone and the tail term can be added separately
        without charging the same seconds twice (see the module docstring).
        """
        if self._decoding_started_at is None:
            return None
        if self.audio_done < self._audio_needed_for_a_rate():
            return None
        if self._last_work_at is None:
            return None
        elapsed = self._last_work_at - self._decoding_started_at - self._waited_at_last_work
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
        # Less whatever of the chunk now being decoded is already paid for, so
        # the number ticks down between bursts instead of stepping on each one.
        decoding_left = max(remaining_audio * rate - self._time_since_work_moved(now), 0.0)

        wait_rate = self._waits.rate
        if wait_rate is None:
            if self._active_wait is None:
                # No tail has been measured and none is running. Either this
                # run has none at all (speaker identification off, or
                # diarization finishing underneath transcription every time,
                # which is the common case) or the first one has not happened
                # yet. Nothing to add, and nothing to apologise for.
                return decoding_left
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
        tail = max(owed - self._time_in_current_wait(now), 0.0)
        return decoding_left + tail

    def _time_since_work_moved(self, now: float) -> float:
        """Time spent DECODING since audio_done last moved.

        This is time already served against the chunk currently being decoded,
        which `remaining_audio * rate` charges for in full. Counting it off is
        what turns a number that only steps on each burst into one that ticks
        down every second, without letting the gap inflate the rate itself.

        Any tail inside the gap is excluded, whether it is still running or
        has just finished. Without that exclusion a 280s diarization wait was
        read as 280s of decoding already done and knocked the estimate down by
        the same amount the moment the wait ended.
        """
        if self._last_work_at is None:
            return 0.0
        waited_since = self._waits.seconds - self._waited_at_last_work
        gap = now - self._last_work_at - waited_since - self._time_in_current_wait(now)
        return max(gap, 0.0)

    def _time_in_current_wait(self, now: float) -> float:
        if self._active_wait is None:
            return 0.0
        started_at, _audio = self._active_wait
        return max(now - started_at, 0.0)
