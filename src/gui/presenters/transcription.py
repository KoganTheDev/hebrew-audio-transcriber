"""What a transcription run should be, decided without touching Qt.

The decisions (file summary, device, TranscriptionOptions) as a pure function,
so they are testable without a MainWindow; the view does only the Qt work.
Translation is passed in as a callable, since gui/i18n.py imports PyQt5.
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.run_options import TranscriptionOptions


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
    """The step 3 header: the filename for one file, a translated count for a
    batch (names would overflow the header).
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
    """Turn the wizard's answers into one run description. `durations` (the
    probed lengths, per file) make progress duration-weighted.
    """
    # The CUDA branch is untested (no NVIDIA GPU on the development machine);
    # Transcriber.load_model retries on CPU if CUDA fails to initialise.
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
