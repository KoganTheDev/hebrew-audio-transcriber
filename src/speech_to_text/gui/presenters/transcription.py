"""What a transcription run should be, decided without touching Qt.

MainWindow._start_transcription used to interleave three unrelated jobs:
widget work (switching to step 3, seeding focus, wiring signals, starting
the QThread), the decisions that shape the run (what the file summary
reads, which device to use, what TranscriptionOptions to build), and
logging. Only the first genuinely needs Qt, but because the three lived in
one method the decisions could only be exercised by building a real
MainWindow against a live QApplication - which is a large part of why
tests/test_gui.py is over 1,400 lines.

This module owns the middle job and nothing else. It is a pure function
over a dataclass: no hidden state, no I/O, no widgets. The view calls it
first, then does only Qt work with the result.

Translation arrives as a callable rather than by importing `t`: gui/i18n.py
imports PyQt5 (QObject/QSettings back the language state), so importing it
here would defeat the purpose. The view passes its own `t`; a test passes a
stub and asserts on the key and params.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable, Protocol

from speech_to_text.core.options import TranscriptionOptions


class DeviceRecommender(Protocol):
    """The one thing this module needs from HardwareDetector.

    Stated structurally so tests can inject a two-line fake instead of
    constructing a real detector, which probes the machine it runs on.
    """

    def get_device_recommendation(self) -> tuple[str, str]: ...


@dataclass(frozen=True)
class TranscriptionRequest:
    """Everything the view needs in order to start a run.

    Frozen because it is a decision already taken: the view reads it to
    populate widgets and construct the worker thread, and never edits it.
    """

    files: list[str]
    model: str
    device: str
    device_reason: str
    durations: list[float]
    options: TranscriptionOptions

    # Already-rendered text for the step 3 header: a bare filename for a
    # single file, a translated count for a batch.
    file_summary: str


def build_file_summary(files: Sequence[str], translate: Callable[..., str]) -> str:
    """The step 3 header line for this selection.

    One file is named outright - the filename is the most useful thing the
    user can be shown, and it fits. A batch is not: the names would either
    overflow the header or be truncated into uselessness, so it becomes a
    count instead, translated because the surrounding UI may be Hebrew.
    """
    if len(files) == 1:
        return os.path.basename(files[0])
    return translate("files_count_label", count=len(files))


def build_transcription_request(
    *,
    files: Sequence[str],
    model: str,
    durations: Sequence[float],
    hardware: DeviceRecommender,
    identify_speakers: bool,
    num_speakers: int,
    translate: Callable[..., str],
) -> TranscriptionRequest:
    """Turn the wizard's collected answers into one run description.

    `durations` are the real PyAV-measured audio lengths gathered on step 1,
    one per file in the same order, which is what makes the progress
    percentages duration-weighted rather than file-counted.
    """
    # get_device_recommendation() was long dead code (hardware_detection.py
    # can return "cuda", but nothing called it - a literal "cpu" was the
    # only device value ever used). Wiring it in is UNTESTED on real GPU
    # hardware: the development machine has no NVIDIA GPU at all (Intel
    # Iris Xe only), so the "cuda" branch has never actually run here.
    # Safety net if it's wrong: Transcriber.load_model() catches a CUDA init
    # failure and retries on CPU (see its docstring) rather than failing the
    # transcription outright - a live failure mode on any machine with a
    # driver/CUDA-version mismatch.
    device, device_reason = hardware.get_device_recommendation()

    return TranscriptionRequest(
        files=list(files),
        model=model,
        device=device,
        device_reason=device_reason,
        durations=list(durations),
        options=TranscriptionOptions(
            identify_speakers=identify_speakers,
            num_speakers=num_speakers,
        ),
        file_summary=build_file_summary(files, translate),
    )
