"""Core Transcription Module
Handles the actual transcription process.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, cast

from speech_to_text import config
from speech_to_text.core.formatting import format_mmss
from speech_to_text.core.hebrew_text import isolate_rtl
from speech_to_text.core.progress_scale import (
    STATUS_ONLY_PERCENT,
    TRANSCRIBER_LOAD_START_PERCENT,
    TRANSCRIBER_MODEL_LOADED_PERCENT,
    TRANSCRIBER_TRANSCRIBE_END_PERCENT,
    TRANSCRIBER_TRANSCRIBE_SPAN,
    WORK_PHASE_PREPARE,
    WORK_PHASE_STARTED,
)
from speech_to_text.core.segments import Segment, Word

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)

# Exception class names that mean "the machine could not reach the model",
# as opposed to "the model is wrong". Matched by NAME, walking the class
# hierarchy, rather than by isinstance: these types come from requests and
# huggingface_hub, which are transitive dependencies of faster-whisper. This
# module already guards its faster_whisper import (see below) because it has
# to import cleanly without it, so importing their error classes at module
# level to run isinstance against would undo that.
#
# LocalEntryNotFoundError is the important one: it is what the hub raises
# when it cannot reach the network AND has nothing cached, which is exactly
# the first-run-without-internet case. Deliberately absent is
# HfHubHTTPError - a 404 for a repo that does not exist reaches the network
# perfectly well and is not this.
_NETWORK_FAILURE_NAMES = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
        "LocalEntryNotFoundError",
        "OfflineModeIsEnabled",
        "NewConnectionError",
        "MaxRetryError",
    }
)


def _is_network_failure(error: BaseException) -> bool:
    """Whether this exception means the network, not the model."""
    seen: set[int] = set()
    queue: list[BaseException | None] = [error]
    while queue:
        current = queue.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for klass in type(current).__mro__:
            if klass.__name__ in _NETWORK_FAILURE_NAMES:
                return True
        # A hub failure usually arrives wrapped, with the socket error that
        # actually happened as its cause.
        queue.append(current.__cause__)
        queue.append(current.__context__)
    return False


class Transcriber:
    """Handles speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = config.DEFAULT_MODEL,
        device: str = "cpu",
        language: str = config.LANGUAGE,
        progress_callback: Callable | None = None,
        compute_type: str | None = None,
        beam_size: int | None = None,
        cpu_threads: int | None = None,
        num_workers: int | None = None,
        work_callback: Callable | None = None,
        phase_callback: Callable | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.progress_callback = progress_callback or self._default_callback
        # The time estimate's two inputs, kept separate from progress_callback
        # because they are measurements rather than a position on a bar (see
        # core/progress_scale.py's work-stream section). Both default to a
        # no-op, so every existing caller - the eval harness included - is
        # unchanged by their existence.
        #
        # work_callback(audio_done, audio_total) is FILE-LOCAL: this module
        # transcribes one thing and knows nothing about batches. core/worker.py
        # rescales it to batch-wide, which is the same division of labour
        # progress_callback already has.
        self.work_callback = work_callback or self._default_work_callback
        self.phase_callback = phase_callback or self._default_phase_callback
        # Any, not Optional[WhisperModel]: WhisperModel is itself None when
        # faster-whisper is not installed (see the import guard above), so
        # there is no static type here to be Optional of.
        self.model: Any = None
        # All four default to None so production behaviour (worker.py's call
        # site, which never passes them) is unchanged from before these
        # existed: compute_type resolves from config.compute_type_for_device
        # at load time (device-conditional - see that function's docstring),
        # beam_size from config.BEAM_SIZE, and cpu_threads/num_workers stay
        # unset (ctranslate2 picks its own thread count). Explicit values
        # exist so tests/eval/compare_models.py can sweep them without a
        # parallel construction path.
        # Set by load_model when it fails, so the caller can say WHY rather
        # than showing one "failed to load" for a missing network and a
        # broken model alike. None until a load has actually failed.
        self.load_failed_on_network = False
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        logger.debug(
            f"Transcriber initialized: model={model_size}, device={device}, lang={language}"
        )

    @property
    def model_repo(self) -> str:
        """The identifier faster-whisper actually loads.

        config.MODELS keys are this app's own stable names; "repo" is the
        upstream address (a bare Whisper size, or a HuggingFace repo holding
        CTranslate2 weights). An unknown key falls through to itself so callers
        can still pass a raw Whisper size or repo id directly - useful for the
        evaluation harness, which benchmarks models that have no GUI card.
        """
        entry = config.MODELS.get(self.model_size)
        # cast, not str(): config.MODELS holds heterogeneous per-model values,
        # so "repo" types as object even though every entry's is a str.
        return cast(str, entry["repo"]) if entry else self.model_size

    @staticmethod
    def _default_callback(message: tuple[str, dict[str, Any]], progress: int) -> None:
        """Default progress callback."""
        pass

    @staticmethod
    def _default_work_callback(audio_done: float, audio_total: float) -> None:
        """Default work callback - see __init__ for why this exists."""
        pass

    @staticmethod
    def _default_phase_callback(name: str, seconds: float | None) -> None:
        """Default phase callback - see __init__ for why this exists."""
        pass

    def load_model(self) -> bool:
        """Load the Whisper model.

        device="cuda" is reachable once gui/main_window.py wires up
        get_device_recommendation() (see hardware_detection.py) - but a CUDA
        recommendation is a guess from nvidia-smi output, not proof the
        ctranslate2/CUDA runtime actually initialises: a driver/CUDA-version
        mismatch, a half-installed driver, or too little free VRAM all
        surface only here, as an exception from WhisperModel() itself. NONE
        of that path has been exercised on real hardware - this development
        machine has no NVIDIA GPU at all (Intel Iris Xe only), so the retry
        below is reasoned about, not measured. If cuda load throws, retry
        once on cpu with a cpu-appropriate compute_type rather than
        surfacing a failure the user can do nothing useful with; a machine
        that would work fine on CPU should not fail just because its GPU
        path had a problem.
        """
        try:
            if not WhisperModel:
                logger.error("faster-whisper package not installed")
                return False

            logger.info(f"Loading {self.model_size} model on {self.device}...")
            # Loading-model phase occupies 5-15% of the overall progress bar
            # (see run_transcription_process in core/worker.py for the full
            # phase breakdown).
            # Progress messages are (i18n key, params) tuples, not text -
            # this module runs in the worker process, which knows nothing
            # about the UI language; the GUI renders keys at display time.
            self.progress_callback(
                ("w_loading_model", {"model": self.model_size}), TRANSCRIBER_LOAD_START_PERCENT
            )

            self._load_on(self.device)

            logger.info(f"✓ Model loaded successfully: {self.model_size} ({self.device})")
            self.progress_callback(
                ("w_model_loaded", {"model": self.model_size}), TRANSCRIBER_MODEL_LOADED_PERCENT
            )
            return True

        except Exception as e:
            if self.device == "cuda":
                logger.warning(
                    f"CUDA model load failed ({e}); falling back to CPU. "
                    "This fallback is untested on real GPU hardware - see "
                    "load_model()'s docstring.",
                    exc_info=True,
                )
                try:
                    self.device = "cpu"
                    self._load_on(self.device)
                    logger.info(
                        f"✓ Model loaded successfully: {self.model_size} (cpu, after CUDA fallback)"
                    )
                    self.progress_callback(
                        ("w_model_loaded", {"model": self.model_size}),
                        TRANSCRIBER_MODEL_LOADED_PERCENT,
                    )
                    return True
                except Exception as fallback_error:
                    e = fallback_error

            self.load_failed_on_network = _is_network_failure(e)
            logger.error(
                f"Failed to load {self.model_size} model: {e}"
                f"{' (network unreachable)' if self.load_failed_on_network else ''}",
                exc_info=True,
            )
            self.progress_callback(("w_error_loading", {"detail": str(e)}), STATUS_ONLY_PERCENT)
            return False

    def _fetch_weights(self) -> str | None:
        """Download the model, reporting progress, and return its local path.

        Returns None to mean "carry on as before": WhisperModel does its own
        download, silently, exactly as it did before this existed.

        Why this exists. WhisperModel's constructor pulls 1.6 GB for
        ivrit-turbo or 3.1 GB for ivrit-large through huggingface_hub, which
        gives the caller no progress callback at all. The bar therefore sat at
        TRANSCRIBER_LOAD_START_PERCENT for anywhere from ten minutes to the
        better part of an hour on a first run, under a status line that only
        ever said "loading". A user watching that screen concludes the app has
        hung, and kills it.

        Why the progress is a FILE COUNT and not a percentage of bytes, which
        is what anyone would rather show. Two better-looking approaches were
        measured and both fail for structural reasons:

        - snapshot_download takes a tqdm_class, which looks like the hook for
          byte counts. It only ever receives the outer "Fetching N files" bar,
          unit "it". The per-file byte bars come from huggingface_hub's own
          internal hf_tqdm and are not overridable by a caller. Probed
          directly against 0.36: the only bar handed to tqdm_class reports 6
          units total for faster-whisper-tiny.
        - Summing bytes on disk under the cache directory reads a flat 3 MB of
          76 for the whole of a cold tiny download. huggingface_hub stages the
          large blobs outside the cache through its xet backend and moves them
          into place at the end, so there is no growing file in the cache to
          watch.

        So the file count is what is actually available. It is coarse - a
        model is mostly one big weights file - but it moves, and it is paired
        with the total download size from config.MODELS so the message says
        how much is coming. That is the difference between a screen that looks
        frozen and one that does not, which is the whole point.

        Everything is wrapped: any failure falls back to the plain path rather
        than taking transcription down with it.
        """
        try:
            from huggingface_hub import snapshot_download
            from tqdm.auto import tqdm as _tqdm
        except Exception as e:  # pragma: no cover - only if the hub/tqdm move
            logger.debug(f"Progress-reporting download unavailable ({e}); using the plain path")
            return None

        entry = config.MODELS.get(self.model_size) or {}
        size_text = cast(str, entry.get("download_size") or "")
        emit = self.progress_callback

        class _ReportingTqdm(_tqdm):  # type: ignore[misc]  # tqdm ships no types
            def update(self, n: int | None = 1) -> bool | None:
                out: bool | None = super().update(n)
                try:
                    total = int(self.total or 0)
                    if total > 0:
                        emit(
                            (
                                "w_downloading_model",
                                {
                                    "done": int(self.n or 0),
                                    "total": total,
                                    "size": size_text,
                                },
                            ),
                            TRANSCRIBER_LOAD_START_PERCENT,
                        )
                except Exception:  # pragma: no cover - never break a download
                    pass
                return out

        try:
            return snapshot_download(
                repo_id=config.hf_repo_id(self.model_repo),
                cache_dir=config.MODEL_DOWNLOAD_ROOT,
                tqdm_class=_ReportingTqdm,
            )
        except Exception as e:
            # Not fatal on its own: WhisperModel gets its turn next and may
            # succeed from a partial cache, and huggingface_hub keeps its
            # partial files so a retry resumes rather than starting over.
            logger.warning(
                f"Progress-reporting download did not finish ({e}); using the plain path"
            )
            return None

    def _load_on(self, device: str) -> None:
        """Construct WhisperModel for the given device, resolving every knob
        that is None to its production default. Split out of load_model() so
        the CUDA-fails-fall-back-to-CPU retry (see load_model's docstring)
        can call it a second time with device swapped, without duplicating
        the argument-resolution logic.

        cpu_threads/num_workers are left unset unless explicitly given -
        ctranslate2 picks its own thread count in that case. Phase B's
        measurement (see tests/eval/compare_models.py and the Stage 2
        report) found no repeatable win from pinning either on this 4-core
        machine, so production leaves them alone; the knobs exist so the
        eval harness can still sweep them.
        """
        compute_type = self.compute_type or config.compute_type_for_device(device)
        kwargs: dict[str, Any] = dict(
            device=device,
            compute_type=compute_type,
            # Absolute, resolved once at import time: a relative path would
            # resolve against the working directory, and the console script
            # can be launched from anywhere. See config.MODEL_DOWNLOAD_ROOT.
            download_root=config.MODEL_DOWNLOAD_ROOT,
        )
        if self.cpu_threads is not None:
            kwargs["cpu_threads"] = self.cpu_threads
        if self.num_workers is not None:
            kwargs["num_workers"] = self.num_workers

        # A local path when the progress-reporting download ran, otherwise the
        # repo id, leaving WhisperModel to fetch it exactly as it always has.
        target = self._fetch_weights() or self.model_repo
        self.model = WhisperModel(target, **kwargs)

    def transcribe(
        self, audio_file: Any, total_duration_seconds: float = 0
    ) -> list[Segment] | None:
        """Transcribe audio to structured segments.

        Args:
            audio_file: Path to an audio/video file, or a float32 mono 16 kHz
                numpy array. faster-whisper accepts either; the array form is
                what lets the stereo channel-split path transcribe one
                speaker's channel at a time without writing temp files
                (see core.audio_source).
            total_duration_seconds: Real audio length (from probing the file
                before transcription starts, see gui.audio_utils), used to
                turn each segment's timestamp into an accurate percentage of
                real work done. Without it, progress falls back to a rough
                per-segment estimate.

        Returns:
            List of Segment (with per-word timings and confidences), or None
            if error. Callers that just want text use
            core.segments.plain_text.

        """
        if not self.model:
            logger.error("Model not loaded - call load_model() first")
            self.progress_callback(("w_model_not_loaded", {}), STATUS_ONLY_PERCENT)
            return None

        logger.info(f"Starting transcription: {audio_file}")
        logger.debug(f"Language: {self.language}, Device: {self.device}")

        try:
            # Transcribing phase occupies 15-90% of the overall progress bar.
            self.progress_callback(("w_starting", {}), TRANSCRIBER_MODEL_LOADED_PERCENT)

            # The stretch between here and the first Segment is the longest
            # stretch of the whole run with nothing to report: model.transcribe()
            # runs Silero VAD over the entire file and decodes the first ~30s
            # window before it yields anything at all. Measured on this machine:
            # 67s on a 15-minute file, all of it at a fixed percentage. Timing it
            # as its own phase is what lets the GUI say "this is a known step
            # that costs this much" instead of showing a bar that has stopped.
            prepare_start = time.perf_counter()
            self.phase_callback(WORK_PHASE_PREPARE, WORK_PHASE_STARTED)

            segments, info = self.model.transcribe(
                audio_file,
                language=self.language,
                beam_size=self.beam_size if self.beam_size is not None else config.BEAM_SIZE,
                # Per-word timings and confidences. Needed twice over: word
                # boundaries are what let diarization attribute a speaker
                # change that happens mid-segment, and word probabilities are
                # what let the Hebrew correction pass touch only the words the
                # model was unsure about. Load-bearing - do not turn off to
                # save time (see core/worker.py's module docstring).
                word_timestamps=True,
                vad_filter=config.VAD_FILTER,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            logger.debug(f"Transcription info: {info}")

            # info carries duration_after_vad - how much audio actually has to
            # be decoded once silence is dropped. Logged rather than used as the
            # work denominator: the GUI measures its rate against wall clock, so
            # skipped silence already shows up as the position simply jumping,
            # and swapping denominators mid-file would make the rate wobble for
            # no gain. It is here because it is the one number that explains why
            # a file ran faster than its length suggested.
            # _as_float, not the raw attribute: faster-whisper's info type has
            # changed shape across releases and the test suite feeds in
            # MagicMocks, neither of which should be able to abort a
            # transcription that is otherwise about to succeed - the same
            # defensiveness _to_segment applies for the same reason.
            speech_seconds = _as_float(
                getattr(info, "duration_after_vad", None), total_duration_seconds
            )
            logger.debug(
                f"Decoding {speech_seconds:.1f}s of speech "
                f"out of {total_duration_seconds:.1f}s of audio"
            )
            self.phase_callback(WORK_PHASE_PREPARE, time.perf_counter() - prepare_start)

            collected: list[Segment] = []
            segment_count = 0

            # 'segments' is a lazy generator - faster-whisper decodes one
            # segment at a time as it's iterated. Iterating it directly
            # (instead of materializing it with list() first) is what makes
            # per-segment progress updates reflect real, ongoing work rather
            # than firing all at once after decoding has already finished.
            for segment in segments:
                segment_count += 1
                try:
                    segment_preview = segment.text[:50] if segment.text else "(empty)"
                    # The preview is often Hebrew, and it's the last thing on
                    # the line - LOG_FORMAT (main.py) puts %(message)s after
                    # only LTR fields. Isolated so a trailing neutral
                    # character (faster-whisper leaves a comma on truncated
                    # segments) resolves against this LTR line instead of
                    # reordering into the Hebrew. See hebrew_text.isolate_rtl.
                    logger.debug(f"Segment {segment_count}: {isolate_rtl(segment_preview)}")
                except Exception:
                    pass  # Skip debug logging if segment attributes are problematic

                if segment.text:
                    collected.append(_to_segment(segment))

                segment_end = getattr(segment, "end", None)
                message: tuple[str, dict[str, Any]]
                if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                    # Real progress: how far into the audio this segment ends.
                    fraction = min(segment_end / total_duration_seconds, 1.0)
                    message = (
                        "w_transcribing_time",
                        {
                            "position": format_mmss(segment_end),
                            "total": format_mmss(total_duration_seconds),
                        },
                    )
                else:
                    # No reliable duration to measure against (shouldn't
                    # normally happen - the GUI always probes the real
                    # duration first) - fall back to a soft, ever-increasing
                    # estimate that never claims to reach completion.
                    fraction = min(0.03 * segment_count, 0.95)
                    message = ("w_transcribing_seg", {"n": segment_count})

                progress = TRANSCRIBER_MODEL_LOADED_PERCENT + int(
                    fraction * TRANSCRIBER_TRANSCRIBE_SPAN
                )
                self.progress_callback(message, progress)

                # The same fact the percentage above was derived from, sent on
                # unrounded and in its own units. The bar needs a 0-100; the
                # clock needs audio-seconds, and turning one back into the other
                # is exactly the lossy step that made the old estimate wrong.
                # Only when the duration is real - without it there is nothing
                # to measure a rate against, and a made-up denominator would
                # produce a confidently wrong ETA rather than none.
                if total_duration_seconds > 0 and isinstance(segment_end, (int, float)):
                    self.work_callback(
                        min(float(segment_end), total_duration_seconds),
                        total_duration_seconds,
                    )

            logger.info(f"✓ Transcription complete: {len(collected)} segments")
            # This file's audio is now fully accounted for, which the last
            # segment's end does NOT say on its own: VAD trims trailing silence,
            # so a recording that ends quietly stops yielding segments well
            # short of its own length. Without this the batch's audio_done would
            # never reach audio_total and the ETA would keep a phantom tail.
            if total_duration_seconds > 0:
                self.work_callback(total_duration_seconds, total_duration_seconds)
            self.progress_callback(("w_transcription_done", {}), TRANSCRIBER_TRANSCRIBE_END_PERCENT)
            return collected

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            logger.debug(f"Error details: {type(e).__name__}")
            # Status-only, not 0: inside a batch the worker rescales this, and
            # a 0 would drag the bar back to the start of the failed file.
            self.progress_callback(("w_error", {"detail": str(e)}), STATUS_ONLY_PERCENT)
            return None


def _to_segment(raw: Any) -> Segment:
    """Convert one faster-whisper Segment into our own Segment.

    Every attribute is read defensively. faster-whisper's segment type has
    changed shape across releases, `words` is None whenever word_timestamps
    is off, and the test suite feeds in MagicMocks whose attributes are mocks
    rather than numbers - none of which should be able to abort a
    transcription that has otherwise succeeded. Missing timings degrade to
    0.0, missing confidence degrades to 1.0 (i.e. "assume the model was sure",
    so the correction pass leaves the word alone rather than mangling it on
    the strength of absent data).
    """
    words = []
    for raw_word in getattr(raw, "words", None) or []:
        word_text = getattr(raw_word, "word", None)
        if not isinstance(word_text, str):
            continue
        words.append(
            Word(
                start=_as_float(getattr(raw_word, "start", None), 0.0),
                end=_as_float(getattr(raw_word, "end", None), 0.0),
                text=word_text,
                probability=_as_float(getattr(raw_word, "probability", None), 1.0),
            )
        )

    return Segment(
        start=_as_float(getattr(raw, "start", None), 0.0),
        end=_as_float(getattr(raw, "end", None), 0.0),
        text=raw.text,
        words=words,
    )


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
