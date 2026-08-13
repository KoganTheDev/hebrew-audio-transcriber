"""
Tests for the batch transcription worker (core/worker.py).

Transcriber itself is swapped for a fake: these tests are about the batch
loop's own logic (progress rescaling, one-file-failure isolation), not about
faster-whisper. The fake stands in wherever core.worker does
`from speech_to_text.core.transcriber import Transcriber` - patched on the
transcriber module itself so that late import picks it up.
"""

import os

import pytest

from speech_to_text.core import worker
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.core.segments import Segment


class FakeQueue:
    """Minimal stand-in for multiprocessing.Queue - runs in-process, synchronously."""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class FakeTranscriber:
    """
    Mimics just enough of Transcriber's shape and progress-reporting contract
    for the batch loop: load_model() succeeds once, transcribe() reports
    progress on the same fixed 15->90 absolute sub-range the real
    Transcriber.transcribe() uses (see core/worker.py's _transcribe_one
    docstring), and raises for a file path the test marks as broken.
    """

    def __init__(self, model_size, device, language, progress_callback):
        self.progress_callback = progress_callback

    def load_model(self):
        self.progress_callback(("w_loading_model", {}), 5)
        self.progress_callback(("w_model_loaded", {}), 15)
        return True

    def transcribe(self, source, total_duration_seconds=0):
        if source == "broken.wav":
            raise RuntimeError("simulated decode failure")
        self.progress_callback(("w_starting", {}), 15)
        for pct in (30, 50, 70, 90):
            self.progress_callback(("w_transcribing_time", {}), pct)
        return [Segment(start=0, end=1, text=f"hello from {source}")]


@pytest.fixture(autouse=True)
def fake_transcriber(monkeypatch):
    import speech_to_text.core.transcriber as transcriber_module
    monkeypatch.setattr(transcriber_module, "Transcriber", FakeTranscriber)


def _progress_percents(progress_queue, keys=None):
    """Percentages of ('progress', key, params, percent) items, optionally filtered by key."""
    out = []
    for item in progress_queue.items:
        if item[0] != "progress":
            continue
        _, key, _params, percent = item
        if keys is None or key in keys:
            out.append(percent)
    return out


class TestBatchProgressRescaling:

    def test_per_file_progress_is_monotonic_and_stays_within_the_batch_band(self, tmp_path):
        """
        The 12-98% band is shared across every file in the batch, weighted by
        duration - a long file among short ones must not make the bar jump
        or run backwards.
        """
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0, 100.0, 5.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav", "b.wav", "c.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            result_queue,
        )

        # Only the per-file transcription messages - not init/load/format/save,
        # which are intentionally outside the 12-98% per-file band.
        per_file_percents = _progress_percents(
            progress_queue, keys={"w_starting", "w_transcribing_time", "w_transcription_done"}
        )
        assert per_file_percents, "expected at least one per-file progress message"
        assert all(12 <= p <= 98 for p in per_file_percents)
        # The duration-weighted rescale itself is monotonic across the whole
        # batch (this is what the formula in run_transcription_process
        # guarantees). Model loading, which happens once before the batch
        # loop starts and is not part of the rescaled band, is not included
        # here - Transcriber's own hardcoded "model loaded" percentage
        # (15%) already sits above this band's 12% floor even in a
        # single-file run, which predates this refactor.
        assert per_file_percents == sorted(per_file_percents)

        assert result_queue.items[-1][0] == "finished"

    def test_a_single_file_batch_still_reaches_completion(self, tmp_path):
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"], str(tmp_path / "out.html"), options, progress_queue, result_queue,
        )

        assert result_queue.items[-1] == ("finished", str(tmp_path / "out.html"))
        assert _progress_percents(progress_queue)[-1] == 100


class TestBatchFailureIsolation:

    def test_one_failing_file_does_not_lose_the_others(self, tmp_path):
        """
        Losing a finished transcript to one bad file would be indefensible
        given how long transcription takes - see core/worker.py's module
        docstring. Only the broken file's section should show the failure
        notice; the rest of the batch must still be fully transcribed.
        """
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(
            identify_speakers=False,
            audio_durations=[10.0, 10.0, 10.0],
            failed_label="NOTICE: this one failed",
        )
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["good1.wav", "broken.wav", "good2.wav"],
            output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        with open(output_path, encoding="utf-8") as f:
            html_out = f.read()

        assert "hello from good1.wav" in html_out
        assert "hello from good2.wav" in html_out
        assert "NOTICE: this one failed" in html_out
        assert "<h1>broken.wav</h1>" in html_out

    def test_every_file_failing_is_reported_as_an_error(self, tmp_path):
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0, 10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["broken.wav", "broken.wav"],
            str(tmp_path / "out.html"), options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "error"
        assert not os.path.exists(str(tmp_path / "out.html"))
