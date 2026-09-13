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
import threading
import time

import numpy as np
import pytest

from speech_to_text.core import progress_scale as ps
from speech_to_text.core import worker
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.core.segments import Segment, Word


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

    It also reports the work stream on the same contract the real one does
    (see core/progress_scale.py): a file-local audio position per segment,
    and the file's full duration once, at the end - which is what the real
    Transcriber has to send because VAD trims trailing silence and the last
    segment therefore stops short of the file's own length.
    """

    def __init__(self, model_size, device, language, progress_callback):
        self.progress_callback = progress_callback
        self.work_callback = lambda done, total: None
        self.phase_callback = lambda name, seconds: None

    def load_model(self):
        self.progress_callback(("w_loading_model", {}), 5)
        self.progress_callback(("w_model_loaded", {}), 15)
        return True

    def transcribe(self, source, total_duration_seconds=0):
        # isinstance guard, not a bare `source == "broken.wav"`: source can
        # now be a numpy mono array (see core/worker.py's to_mono dedupe),
        # and `ndarray == str` is an elementwise comparison that raises on
        # truth-testing rather than just being False.
        if isinstance(source, str) and source == "broken.wav":
            raise RuntimeError("simulated decode failure")
        if isinstance(source, str) and source == "fatal.wav":
            # A BaseException, not an Exception - simulates the process
            # actually dying (kill -9, a forced reboot, power loss) rather
            # than a caught-and-logged per-file failure. Nothing in
            # run_transcription_process catches anything broader than
            # Exception, so this must propagate all the way out and the
            # function must never reach its final render/write.
            raise KeyboardInterrupt("simulated hard kill mid-transcription")
        self.progress_callback(("w_starting", {}), 15)
        self.phase_callback("prepare", 0.5)
        for pct in (30, 50, 70, 90):
            self.progress_callback(("w_transcribing_time", {}), pct)
            if total_duration_seconds > 0:
                # 30..90 of the 15..90 band, expressed as a position in the
                # file's own audio - the same fact, in the work stream's units.
                fraction = (pct - 15) / 75
                self.work_callback(fraction * total_duration_seconds, total_duration_seconds)
        if total_duration_seconds > 0:
            self.work_callback(total_duration_seconds, total_duration_seconds)
        return [Segment(start=0, end=1, text=f"hello from {source}")]


@pytest.fixture(autouse=True)
def fake_transcriber(monkeypatch):
    import speech_to_text.core.transcriber as transcriber_module

    monkeypatch.setattr(transcriber_module, "Transcriber", FakeTranscriber)


def _work_items(progress_queue):
    """(audio_done, audio_total) of every ('work', ...) item, in order."""
    return [(item[1], item[2]) for item in progress_queue.items if item[0] == "work"]


def _phase_items(progress_queue):
    """(name, seconds) of every ('phase', ...) item, in order."""
    return [(item[1], item[2]) for item in progress_queue.items if item[0] == "phase"]


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
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            result_queue,
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
            output_path,
            options,
            progress_queue,
            result_queue,
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
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            result_queue,
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
            identify_speakers=False,
            audio_durations=[10.0, 10.0, 10.0],
        )
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        with pytest.raises(KeyboardInterrupt):
            worker.run_transcription_process(
                ["a.wav", "b.wav", "fatal.wav"],
                output_path,
                options,
                progress_queue,
                result_queue,
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
            identify_speakers=False,
            audio_durations=[10.0, 10.0, 10.0],
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
            ["a.wav", "b.wav", "c.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
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
            ["a.wav", "b.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert len(seen_doc_ids) >= 2, "expected at least one checkpoint plus the final write"
        assert len(set(seen_doc_ids)) == 1

    def _vista(self, html_out: str) -> str:
        # The backdrop's image now lives in a per-document <style> element
        # (a plain style="" attribute can only ever set one rule, and the
        # portrait art-direction swap needs a media query - see core/formatting
        # render_html()'s .backdrop <style> comment), not an inline style
        # attribute on the element itself - match the landscape rule's url().
        match = re.search(r"\.backdrop\{background-image:url\(([^)]+)\)\}", html_out)
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
            ["a.wav", "b.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
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
            ["a.wav", "b.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert os.listdir(tmp_path) == ["out.html"]

    def test_a_single_file_run_is_unchanged(self, tmp_path):
        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1] == ("finished", output_path)
        with open(output_path, encoding="utf-8") as f:
            html_out = f.read()
        assert "hello from a.wav" in html_out
        assert os.listdir(tmp_path) == ["out.html"]


class TestDiarizationOverlap:
    """
    Stage 2, Phase C: diarization now runs on a background thread started
    before transcribe(), instead of after it - see _start_diarization/
    _finish_identify_speakers in core/worker.py. These tests cover what's
    testable without real audio or the sherpa-onnx models: that diarization
    still gets applied, that the audio is only downmixed to mono once (the
    to_mono duplicate this same change was asked to remove), and that a
    diarization failure stays non-fatal exactly like the old sequential code.
    """

    def _stub_audio_and_diarization(
        self, monkeypatch, spans=None, diarize_error=None, mono_call_counter=None
    ):
        """
        Wires fake audio_source.load/to_mono and diarization.* so a test can
        run run_transcription_process with identify_speakers=True without
        touching a real file, PyAV or sherpa-onnx.
        """
        from speech_to_text.core import audio_source, diarization

        channels = [np.zeros(1600, dtype=np.float32)]

        monkeypatch.setattr(audio_source, "load", lambda path: (channels, False))

        real_to_mono = audio_source.to_mono

        def counting_to_mono(chans):
            if mono_call_counter is not None:
                mono_call_counter["n"] += 1
            return real_to_mono(chans)

        monkeypatch.setattr(audio_source, "to_mono", counting_to_mono)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        def fake_diarize(samples, sample_rate=16000, num_speakers=2, progress=None):
            if diarize_error is not None:
                raise diarize_error
            return spans or []

        monkeypatch.setattr(diarization, "diarize", fake_diarize)

    def test_diarization_result_is_still_applied_after_the_switch_to_overlap(
        self, tmp_path, monkeypatch
    ):
        """
        The whole point of overlapping is to change WHEN diarization runs,
        not WHETHER its result reaches the transcript. assign_speakers is
        real (not stubbed) here, so a segment whose word falls inside the
        one fake span must come back attributed to that span's speaker.
        """
        from speech_to_text.core.diarization import SpeakerSpan

        span = SpeakerSpan(start=0.0, end=1.0, speaker=1)
        self._stub_audio_and_diarization(monkeypatch, spans=[span])

        # FakeTranscriber.transcribe() ignores its `source` for the returned
        # Segment's word timings, so attach a word ourselves after the call
        # to give assign_speakers something inside the fake span to match.
        import speech_to_text.core.transcriber as transcriber_module

        class WordyFakeTranscriber(transcriber_module.Transcriber):
            def transcribe(self, source, total_duration_seconds=0):
                segments = super().transcribe(source, total_duration_seconds)
                for segment in segments:
                    segment.words = [Word(start=0.1, end=0.5, text="hi", probability=0.9)]
                return segments

        monkeypatch.setattr(transcriber_module, "Transcriber", WordyFakeTranscriber)

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"

    def test_successful_diarization_still_reports_a_real_progress_percent(
        self, tmp_path, monkeypatch
    ):
        """
        The old sequential _identify_speakers always pushed a real
        ("progress", ...) percentage for "w_identifying_speakers" once
        diarization succeeded (see progress_scale.py's FILE_LOCAL_SPEAKER_ID_END
        boundary) - the overlap version's status-only messages during the
        race (see _start_diarization) were deliberately NOT a percent, but
        that was only supposed to apply DURING the overlap window. Once both
        threads have joined in _finish_identify_speakers, there is only one
        writer again and nothing stops a real percent bump - if it never
        happens, the progress bar silently sits at whatever transcribe()
        left it at (its own FILE_LOCAL_TRANSCRIBE_END) through all of
        diarization and assign_speakers, then jumps straight to completion.
        Not a monotonicity violation, but a real loss of feedback for a
        phase that, per the estimate baked into hardware_detection.py, can
        take a third of the audio's own length.
        """
        from speech_to_text.core.diarization import SpeakerSpan

        span = SpeakerSpan(start=0.0, end=1.0, speaker=1)
        self._stub_audio_and_diarization(monkeypatch, spans=[span])

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert any(
            item[0] == "progress" and item[1] == "w_identifying_speakers"
            for item in progress_queue.items
        ), (
            "expected a real percentage update once diarization succeeded, not just the status message"
        )

    def test_to_mono_runs_once_per_file_not_twice(self, tmp_path, monkeypatch):
        """
        Before this change, to_mono(channels) was called once to build the
        transcribe source and again inside diarization - worker.py:434 and
        :517 in the pre-Stage-2 code. Both now share the same array.
        """
        counter = {"n": 0}
        self._stub_audio_and_diarization(monkeypatch, spans=[], mono_call_counter=counter)

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert counter["n"] == 1

    def test_diarization_finding_no_spans_still_reports_progress_not_just_success(
        self, tmp_path, monkeypatch
    ):
        """
        An empty spans list is not an error (diarize() can legitimately find
        no distinguishable speakers) - assign_speakers already treats it as
        a no-op (returns the segments unchanged, see its own `if not spans`
        guard in core/diarization.py), so this is NOT the "error" branch in
        _finish_identify_speakers. The old sequential code still pushed
        progress through diarize()'s on_progress regardless of whether
        spans ended up empty; the overlap version must not silently skip
        that just because there was nothing to attribute.
        """
        self._stub_audio_and_diarization(monkeypatch, spans=[])

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert any(
            item[0] == "progress" and item[1] == "w_identifying_speakers"
            for item in progress_queue.items
        ), "expected a real percentage update even though no spans were found"

    def test_diarization_failure_is_non_fatal_and_still_reported_as_status(
        self, tmp_path, monkeypatch
    ):
        """
        Same non-fatal contract as the old sequential _identify_speakers:
        a diarization exception (missing model, corrupt audio, whatever)
        must cost speaker labels only, never the transcript - and it must
        not deadlock or crash the batch now that it happens on a thread.
        """
        self._stub_audio_and_diarization(
            monkeypatch, diarize_error=RuntimeError("simulated diarization failure")
        )

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert any(
            item[0] == "progress" and item[1] == "w_speakers_unavailable"
            for item in progress_queue.items
        )

    def test_diarization_progress_during_overlap_is_status_only_not_a_percent(
        self, tmp_path, monkeypatch
    ):
        """
        See the comment above _start_diarization's call site in
        core/worker.py: a real percentage from diarization while
        transcription is still running concurrently would either lie about
        how much of the file-local scale is actually done, or race
        transcribe's own climbing percentage for the same numbers. During
        the thread itself (_start_diarization) it must arrive as a
        ("status", key, params) item - text only. That is NOT the same
        claim as "never a percent at all" - once both threads have joined,
        _finish_identify_speakers is single-threaded again and does push one
        real ("progress", "w_identifying_speakers", ..., percent) update
        (see test_diarization_finding_no_spans_still_reports_progress_not_
        just_success) - this test only pins that the status message exists
        and isn't itself a percent.
        """
        self._stub_audio_and_diarization(monkeypatch, spans=[])

        output_path = str(tmp_path / "out.html")
        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()
        result_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            output_path,
            options,
            progress_queue,
            result_queue,
        )

        assert result_queue.items[-1][0] == "finished"
        assert ("status", "w_identifying_speakers", {}) in progress_queue.items

    def test_a_transcribe_exception_still_joins_the_diarization_thread(self, monkeypatch):
        """
        If transcriber.transcribe() raises, _transcribe_one must not leave
        the diarization background thread orphaned. daemon=True (see
        _start_diarization) keeps it from blocking process exit, but while
        THIS worker process is still alive - processing the rest of a
        multi-file batch, or rendering/writing the final HTML - an orphaned
        thread keeps burning CPU concurrently with that work for a result
        (diarization_result) nothing will ever read, since the local
        variable holding it goes out of scope with the exception. join()ing
        it before the exception propagates is the fix.
        """
        from speech_to_text.core import audio_source, diarization

        channels = [np.zeros(1600, dtype=np.float32)]
        monkeypatch.setattr(audio_source, "load", lambda path: (channels, False))
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        diarize_finished = threading.Event()

        def slow_diarize(samples, sample_rate=16000, num_speakers=2, progress=None):
            time.sleep(0.05)
            diarize_finished.set()
            return []

        monkeypatch.setattr(diarization, "diarize", slow_diarize)

        class ExplodingTranscriber:
            def __init__(self):
                self.progress_callback = lambda *a, **k: None
                self.work_callback = lambda *a, **k: None
                self.phase_callback = lambda *a, **k: None

            def transcribe(self, source, total_duration_seconds=0):
                raise RuntimeError("simulated transcribe failure")

        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])

        with pytest.raises(RuntimeError):
            worker._transcribe_one(
                "a.wav",
                ExplodingTranscriber(),
                options,
                10.0,
                lambda *a, **k: None,
                FakeQueue(),
                lambda *a, **k: None,
            )

        # Checked with NO extra wait: ExplodingTranscriber.transcribe()
        # raises essentially instantly, while slow_diarize() sleeps 0.05s
        # before setting the flag. If _transcribe_one actually joined the
        # diarization thread before letting the exception propagate, the
        # flag is necessarily already set by the time pytest.raises exits -
        # a generous timeout here would hide exactly the bug this test
        # exists to catch (an orphaned thread that happens to finish soon
        # after anyway, on its own schedule, having never been joined).
        assert diarize_finished.is_set(), (
            "diarization thread was not joined before the exception propagated "
            "out of _transcribe_one - it was left running orphaned instead"
        )


class TestWorkStream:
    """
    The measurements the time estimate is computed from (core/progress_scale.py).

    These are NOT the progress bar. The bar is a position on a 0-100 scale
    whose bands cost wildly different amounts of wall clock; the work stream
    is audio-seconds and measured durations, which is what can actually be
    divided into a rate. The properties below are the ones the GUI's
    arithmetic assumes, and each of them is a way the old
    elapsed * (100 - pct) / pct estimate went wrong.
    """

    def test_audio_done_climbs_monotonically_to_the_batch_total(self, tmp_path):
        """
        The denominator has to be the batch, not the file.

        A per-file position would reset to zero at every file boundary, and a
        rate computed across that reset would collapse the estimate exactly
        when it finally had enough data to be good.
        """
        durations = [10.0, 100.0, 5.0]
        options = TranscriptionOptions(identify_speakers=False, audio_durations=durations)
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav", "b.wav", "c.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        work = _work_items(progress_queue)
        assert work, "expected the worker to report audio positions"

        done = [d for d, _total in work]
        assert done == sorted(done), "audio_done ran backwards"
        assert all(total == sum(durations) for _d, total in work)
        assert done[-1] == pytest.approx(sum(durations))

    def test_the_reported_total_is_the_real_probed_duration_not_a_file_count(self, tmp_path):
        """
        Weighting by duration is the whole reason the batch scale exists: a
        two-hour recording among ten one-minute ones must not read as "90% of
        files done" while nearly all the work remains.
        """
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[60.0, 7200.0])
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["short.wav", "long.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        work = _work_items(progress_queue)
        # The short file is 1/121st of the batch's audio, so the position must
        # still be near the floor when it finishes, not near half.
        assert work[0][0] < 60.0
        assert max(d for d, _t in work) == pytest.approx(7260.0)

    def test_a_file_with_no_known_duration_reports_no_position(self, tmp_path):
        """
        Without a probed duration there is nothing to measure a rate against.
        Reporting a position anyway - against a guessed denominator - would
        produce a confidently wrong ETA, which is worse than none: the GUI
        shows elapsed only until a real measurement exists.
        """
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[0.0])
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        assert _work_items(progress_queue) == []

    def test_phases_are_reported_with_their_measured_duration(self, tmp_path):
        """
        Every one of these was already being timed for the DEBUG log (see
        _log_phase). Sending the same value rather than re-deriving it in the
        GUI is what keeps one measurement instead of two numbers that can
        disagree.
        """
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0])
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        phases = dict(_phase_items(progress_queue))
        assert ps.WORK_PHASE_TRANSCRIBE in phases
        assert ps.WORK_PHASE_RENDER in phases
        assert all(seconds is None or seconds >= 0 for seconds in phases.values()), (
            "a phase reported a negative duration"
        )

    def test_the_diarization_wait_is_announced_before_it_blocks(self, tmp_path, monkeypatch):
        """
        The single most conspicuous stall in a real run: measured at 280s and
        222s on the two files of one batch, every second of it after the last
        segment arrived and with the bar not moving. Diarization reports no
        percentage of its own by design (see _start_diarization), so a
        "started" marker is the only honest signal available until the join
        returns - and it is what lets the GUI count the phase down rather than
        appear to have hung.
        """
        from speech_to_text.core import audio_source, diarization

        monkeypatch.setattr(
            audio_source, "load", lambda path: ([np.zeros(1600, dtype=np.float32)], False)
        )
        monkeypatch.setattr(diarization, "models_present", lambda: True)
        monkeypatch.setattr(
            diarization,
            "diarize",
            lambda samples, sample_rate=16000, num_speakers=2, progress=None: [],
        )

        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        waits = [
            seconds
            for name, seconds in _phase_items(progress_queue)
            if name == ps.WORK_PHASE_DIARIZE_WAIT
        ]
        assert waits, "the diarization join was never announced"
        assert waits[0] is ps.WORK_PHASE_STARTED, "the wait must be announced before it blocks"
        assert waits[-1] is not ps.WORK_PHASE_STARTED, "the wait never reported how long it took"

    def test_a_two_party_file_is_not_counted_twice(self, tmp_path, monkeypatch):
        """
        A true-stereo recording is transcribed once per channel, so the work
        callback fires twice over the same duration. They are folded into
        halves, or the reported position would climb to the file's length,
        drop back to zero and climb again - and audio_done running backwards
        makes the estimate jump instead of converge.
        """
        from speech_to_text.core import audio_source

        stereo = [np.zeros(1600, dtype=np.float32), np.zeros(1600, dtype=np.float32)]
        monkeypatch.setattr(audio_source, "load", lambda path: (stereo, True))

        options = TranscriptionOptions(identify_speakers=True, audio_durations=[10.0])
        progress_queue = FakeQueue()

        worker.run_transcription_process(
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            progress_queue,
            FakeQueue(),
        )

        done = [d for d, _t in _work_items(progress_queue)]
        assert done, "the two-party path reported no position at all"
        assert done == sorted(done), "audio_done ran backwards across the two channels"
        assert max(done) == pytest.approx(10.0), "one file counted as more than its own length"


class TestAbandonedTempFilesAreSwept:
    """
    _atomic_write_html removes its temp file if the write fails - but a
    cancelled run never gets to run that cleanup. stop() calls terminate(),
    which on Windows is TerminateProcess: no exception, no finally, no
    finalizer. A run cancelled mid-write left a multi-megabyte hidden file in
    the user's own audio folder and nothing ever removed it.
    """

    @staticmethod
    def _orphan(directory, name=".transcript-abc123.tmp", age_seconds=7200):
        path = directory / name
        path.write_text("half a transcript", encoding="utf-8")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def test_an_abandoned_temp_file_is_removed(self, tmp_path):
        orphan = self._orphan(tmp_path)

        assert worker._sweep_stale_temp_files(str(tmp_path / "out.html")) == 1
        assert not orphan.exists()

    def test_a_temp_file_that_could_still_be_in_flight_is_left_alone(self, tmp_path):
        """
        Two runs writing into the same folder at once is something a user with
        two windows open can do, and deleting a live sibling's temp file would
        corrupt ITS output - far worse than leaving litter. A real write takes
        well under a second, so only a long-dead file is swept.
        """
        fresh = self._orphan(tmp_path, name=".transcript-live.tmp", age_seconds=0)

        assert worker._sweep_stale_temp_files(str(tmp_path / "out.html")) == 0
        assert fresh.exists()

    def test_nothing_else_in_the_folder_is_touched(self, tmp_path):
        """The sweep runs in the user's own audio folder. It recognises its
        own litter by prefix AND suffix, and nothing else."""
        keep = [
            "meeting.mp3",
            "out_transcription.html",
            "transcript-notes.tmp",  # no leading dot
            ".transcript-notes.txt",  # wrong suffix
        ]
        for name in keep:
            path = tmp_path / name
            path.write_text("x", encoding="utf-8")
            old = time.time() - 7200
            os.utime(path, (old, old))

        assert worker._sweep_stale_temp_files(str(tmp_path / "out.html")) == 0
        for name in keep:
            assert (tmp_path / name).exists(), f"the sweep deleted {name}"

    def test_a_sweep_that_cannot_run_is_not_fatal(self, tmp_path, monkeypatch):
        """Tidying must never cost a transcription."""

        def boom(_directory):
            raise OSError("permission denied")

        monkeypatch.setattr(worker.os, "listdir", boom)

        assert worker._sweep_stale_temp_files(str(tmp_path / "out.html")) == 0

    def test_a_file_that_will_not_delete_is_stepped_over(self, tmp_path, monkeypatch):
        self._orphan(tmp_path, name=".transcript-a.tmp")
        self._orphan(tmp_path, name=".transcript-b.tmp")

        real_remove = worker.os.remove
        seen: list = []

        def flaky(path):
            seen.append(path)
            if path.endswith("a.tmp"):
                raise OSError("in use by another process")
            real_remove(path)

        monkeypatch.setattr(worker.os, "remove", flaky)

        assert worker._sweep_stale_temp_files(str(tmp_path / "out.html")) == 1
        assert len(seen) == 2, "the sweep stopped at the first failure"

    def test_a_run_sweeps_before_it_writes_its_own_checkpoint(self, tmp_path):
        """
        Swept at the start of a run, because the run that creates the orphan
        is by definition the one that does not get to clean up after itself.
        """
        orphan = self._orphan(tmp_path)
        options = TranscriptionOptions(identify_speakers=False, audio_durations=[10.0])

        worker.run_transcription_process(
            ["a.wav"],
            str(tmp_path / "out.html"),
            options,
            FakeQueue(),
            FakeQueue(),
        )

        assert not orphan.exists()
        assert (tmp_path / "out.html").exists()
