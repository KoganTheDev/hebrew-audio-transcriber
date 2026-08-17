"""
Tests for the batch transcription worker (core/worker.py).

Transcriber itself is swapped for a fake: these tests are about the batch
loop's own logic (progress rescaling, one-file-failure isolation), not about
faster-whisper. The fake stands in wherever core.worker does
`from speech_to_text.core.transcriber import Transcriber` - patched on the
transcriber module itself so that late import picks it up.
"""

import os
import re

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
        if source == "fatal.wav":
            # A BaseException, not an Exception - simulates the process
            # actually dying (kill -9, a forced reboot, power loss) rather
            # than a caught-and-logged per-file failure. Nothing in
            # run_transcription_process catches anything broader than
            # Exception, so this must propagate all the way out and the
            # function must never reach its final render/write.
            raise KeyboardInterrupt("simulated hard kill mid-transcription")
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


class TestCheckpointing:
    """
    Phase 1: the output HTML is rewritten after every file, not just at the
    end, so a crash mid-batch does not lose already-finished transcripts.
    """

    def _doc_id(self, html_out: str) -> str:
        match = re.search(r'data-doc-id="([^"]+)"', html_out)
        assert match, "expected a data-doc-id attribute on <html>"
        return match.group(1)

    def test_a_hard_kill_mid_batch_still_leaves_the_earlier_files_transcripts_on_disk(
        self, tmp_path
    ):
        """
        Proves the property directly rather than by inference from the final
        file: the THIRD file's transcription raises KeyboardInterrupt, a
        BaseException that run_transcription_process's `except Exception`
        clauses do not catch, so the function propagates out and NEVER
        reaches emit_progress(("w_saving", ...)) or the final
        _atomic_write_html call - there is no "last write" here at all. If
        the first two files' transcripts are on disk anyway, only the
        per-file checkpoint could have put them there.
        """
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(
            identify_speakers=False, audio_durations=[10.0, 10.0, 10.0],
        )
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        with pytest.raises(KeyboardInterrupt):
            worker.run_transcription_process(
                ["a.wav", "b.wav", "fatal.wav"],
                output_path, options, progress_queue, result_queue,
            )

        # The run died before it could put anything on result_queue at all.
        assert not result_queue.items

        with open(output_path, encoding="utf-8") as f:
            html_out = f.read()
        assert "hello from a.wav" in html_out
        assert "hello from b.wav" in html_out

    def test_output_file_already_holds_earlier_transcripts_while_a_later_file_is_still_running(
        self, tmp_path, monkeypatch
    ):
        """
        Reads the output file WHILE the third file's transcription is still
        in progress - before the batch has finished at all - and confirms
        the first two files' transcripts are already there, and the third's
        is not. This is direct evidence the checkpoint after file 2 hit disk
        before the run ended, rather than an inference from the file's final
        contents (which the final write would produce with or without
        checkpointing).
        """
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(
            identify_speakers=False, audio_durations=[10.0, 10.0, 10.0],
        )
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        seen_mid_run = {}
        real_transcribe = FakeTranscriber.transcribe

        def spying_transcribe(self, source, total_duration_seconds=0):
            if source == "c.wav" and os.path.exists(output_path):
                with open(output_path, encoding="utf-8") as f:
                    seen_mid_run["content"] = f.read()
            return real_transcribe(self, source, total_duration_seconds=total_duration_seconds)

        monkeypatch.setattr(FakeTranscriber, "transcribe", spying_transcribe)

        worker.run_transcription_process(
            ["a.wav", "b.wav", "c.wav"], output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert "content" in seen_mid_run, "expected the output file to already exist by file 3"
        assert "hello from a.wav" in seen_mid_run["content"]
        assert "hello from b.wav" in seen_mid_run["content"]
        assert "hello from c.wav" not in seen_mid_run["content"]

    def test_doc_id_is_stable_across_checkpoints(self, tmp_path, monkeypatch):
        """
        render_html() mints a fresh uuid4 doc_id per call by default; the
        worker must pin one and reuse it across every checkpoint, or the
        browser's localStorage autosave key would change underneath a user
        who is editing a partially-written file.
        """
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0, 10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        seen_doc_ids = []
        real_write = worker._atomic_write_html

        def recording_write(path, content):
            seen_doc_ids.append(self._doc_id(content))
            real_write(path, content)

        monkeypatch.setattr(worker, "_atomic_write_html", recording_write)

        worker.run_transcription_process(
            ["a.wav", "b.wav"], output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert len(seen_doc_ids) >= 2, "expected at least one checkpoint plus the final write"
        assert len(set(seen_doc_ids)) == 1

    def _vista(self, html_out: str) -> str:
        # The backdrop's image now lives in a per-document <style> element
        # (a plain style="" attribute can only ever set one rule, and the
        # portrait art-direction swap needs a media query - see formatting.py
        # render_html()'s .backdrop <style> comment), not an inline style
        # attribute on the element itself - match the landscape rule's url().
        match = re.search(r'\.backdrop\{background-image:url\(([^)]+)\)\}', html_out)
        assert match, "expected a .backdrop rule with a background-image url()"
        return match.group(1)

    def test_vista_is_stable_across_checkpoints(self, tmp_path, monkeypatch):
        """
        render_html() picks a fresh random vista per call by default, exactly
        like it mints a fresh doc_id - the same reasoning as
        test_doc_id_is_stable_across_checkpoints applies here: without a pin,
        the backdrop photo would change on every per-file checkpoint rewrite
        and flicker to a different image mid-batch, which is not what "one
        document" means.
        """
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0, 10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        seen_vistas = []
        real_write = worker._atomic_write_html

        def recording_write(path, content):
            seen_vistas.append(self._vista(content))
            real_write(path, content)

        monkeypatch.setattr(worker, "_atomic_write_html", recording_write)

        worker.run_transcription_process(
            ["a.wav", "b.wav"], output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert len(seen_vistas) >= 2, "expected at least one checkpoint plus the final write"
        assert len(set(seen_vistas)) == 1

    def test_no_stray_temp_file_survives_a_successful_run(self, tmp_path):
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0, 10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav", "b.wav"], output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert os.listdir(tmp_path) == ["out.html"]

    def test_a_single_file_run_is_unchanged(self, tmp_path):
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"], output_path, options, progress_queue, result_queue,
        )

        assert result_queue.items[-1] == ("finished", output_path)
        with open(output_path, encoding="utf-8") as f:
            html_out = f.read()
        assert "hello from a.wav" in html_out
        assert os.listdir(tmp_path) == ["out.html"]
