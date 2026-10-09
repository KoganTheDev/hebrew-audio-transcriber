"""How long is left, computed from what this run has actually done.

Not projected from the progress bar: its bands cost very different time (the
VAD pass sits at a fixed 5% for over a minute), so a bar-based estimate froze
or kept projecting a pace that had ended - 1h 6m predicted for a 38m batch.
Instead, two rates over measured work:

    decode rate = time spent decoding / audio-seconds decoded
    tail rate   = leftover diarization / audio-seconds it followed
    remaining   = audio left * decode rate + audio owing a tail * tail rate

Audio-seconds are exact (probed) and add up across a batch; per-file overhead
is absorbed by the measured average. Tails stay a separate rate because each
is owed at the END of its file: folding them into the average over-predicts
right after one and under-predicts just before the next. Nothing is guessed -
an unmeasured quantity is None, and the caller shows "calculating".
"""

from dataclasses import dataclass, field

# How much audio must be decoded before a rate is worth projecting. The floor:
# segments arrive in a burst after the first 30 s window, so the first report
# is not the pace (two windows, as in core/calibration.py).
MIN_AUDIO_FOR_A_RATE = 60.0

# The share: early decoding is slower while diarization competes for cores.
# On a real 1665 s batch the rate read 1.838 after 85 s, 1.056 by the end;
# waiting for a tenth moved the first estimate from 48:13 to 30:14 (true 26:26).
MIN_SHARE_FOR_A_RATE = 0.10

# The ceiling on that share, so a long batch does not stay silent for an hour
# waiting to reach a tenth of itself. Five minutes of audio is enough to have
# averaged over the contended opening whatever the batch's total length.
MAX_AUDIO_BEFORE_A_RATE = 300.0


@dataclass
class _WaitMeasurement:
    """Diarization left over after transcription finished, per audio-second.

    On this hardware diarization hides under transcription (26.6 s vs
    130.3 s); a fast GPU or small model would leave a visible wait. Not yet
    observed since diarization moved onto a thread - a guard, not the common
    path.
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
    """Accumulates one run's measurements and answers "how much longer?" -
    stateful, since the answer depends on the whole run so far.
    """

    audio_total: float = 0.0
    audio_done: float = 0.0

    # When work on the batch's audio began: after model loading (seconds to
    # tens of minutes, which no amount of audio should pay for), and before the
    # first work report (which arrives after a whole 30 s window is done).
    _decoding_started_at: float | None = None

    # Audio position when the current file began, so the file's own length is
    # known while its tail is being waited out. Taken from the work stream
    # rather than the durations list the GUI already holds, so there is one
    # source for what counts as done and it cannot disagree with itself.
    _current_file_audio_start: float = 0.0
    _current_file_index: int | None = None

    # When audio_done last moved. The rate is measured to here, not to "now":
    # segments arrive in bursts, so a rate to "now" sawed up and down (seen
    # live climbing 1:43 -> 2:00, then dropping to 0:52). The gap since is
    # counted down separately.
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
        """Audio whose file has not yet paid its diarization tail - including
        the file being decoded now, which owes its tail in full until it ends.
        """
        return max(self.audio_total - self._waits.audio, 0.0)

    def note_work_started(self, now: float) -> None:
        """The first phase of the first file has started: the clock starts
        here, after one-time setup.
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
        """Seconds spent decoding per audio-second, or None if not yet known.

        Measured over completed work only (to _last_work_at, not `now`), with
        tails subtracted so the tail term is not charged twice.
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
        """Seconds still to go, or None while unknown: nothing decoded yet, too
        little decoded for a rate, or a first tail of unknown length.
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
            # length is not knowable in advance - diarization reports no
            # progress while it works - so any number here would be an
            # invention, and a number that then sat at zero for minutes is
            # exactly the behaviour this change exists to remove.
            return None

        owed = wait_rate * self._audio_owing_a_tail()
        # Time already served against the tail in progress. Floored at zero
        # because the prediction comes from a different file and can simply be
        # short; a countdown running past zero into negative numbers would be
        # a worse lie than an optimistic one.
        tail = max(owed - self._time_in_current_wait(now), 0.0)
        return decoding_left + tail

    def _time_since_work_moved(self, now: float) -> float:
        """Decoding time since audio_done last moved - counted off the estimate
        so it ticks down every second between bursts. Tails in the gap are
        excluded, or a finished wait would knock its whole length off.
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
