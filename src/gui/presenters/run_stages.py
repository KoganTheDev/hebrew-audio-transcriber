"""Which stage step 3's checklist shows, from the worker's phase reports.

Phases arrive per file, in order: decode, VAD prepare, transcribe, then - with
speaker labels - the diarization wait and speaker assignment, then Hebrew
correction and the HTML render. Everything before the first is the model
loading. Most phases report only when they END, so each moves the list to the
stage after it; a decode once past transcription is the next file of a batch.
"""

from enum import Enum

from core.progress_scale import (
    WORK_PHASE_ASSIGN,
    WORK_PHASE_CORRECT,
    WORK_PHASE_DECODE,
    WORK_PHASE_DIARIZE_WAIT,
    WORK_PHASE_RENDER,
    WORK_PHASE_TRANSCRIBE,
)


class Stage(Enum):
    """Values are the i18n keys of the stage names."""

    LOAD = "stage_loading_model"
    TRANSCRIBE = "stage_transcribing"
    SPEAKERS = "stage_speakers"
    FINISH = "stage_finishing"


def stages_for(identify_speakers: bool) -> list[Stage]:
    """The checklist's rows: a speaker stage only when speakers are labelled."""
    stages = [Stage.LOAD, Stage.TRANSCRIBE]
    if identify_speakers:
        stages.append(Stage.SPEAKERS)
    return [*stages, Stage.FINISH]


def next_stage(
    active: Stage | None, phase: str, started: bool, identify_speakers: bool
) -> Stage | None:
    """The stage to show after a phase report, or None to stay put."""
    if phase == WORK_PHASE_TRANSCRIBE and not started:
        return Stage.SPEAKERS if identify_speakers else Stage.FINISH
    if phase == WORK_PHASE_DIARIZE_WAIT:
        return Stage.SPEAKERS
    if phase in (WORK_PHASE_ASSIGN, WORK_PHASE_CORRECT, WORK_PHASE_RENDER) and not started:
        return Stage.FINISH
    if active is Stage.LOAD or (
        phase == WORK_PHASE_DECODE and active in (Stage.SPEAKERS, Stage.FINISH)
    ):
        return Stage.TRANSCRIBE
    return None
