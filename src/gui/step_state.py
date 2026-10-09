"""Where a step stands, shared by the wizard stepper and step 3's checklist.

Its own module so both can import it: gui.stepper imports gui.steps, which
imports the checklist, so the checklist cannot import gui.stepper back.
"""

from enum import Enum


class StepState(Enum):
    PENDING = "pending"
    CURRENT = "current"
    DONE = "done"


# The i18n key that names each state for a screen reader.
STATUS_KEYS = {
    StepState.PENDING: "step_status_pending",
    StepState.CURRENT: "step_status_current",
    StepState.DONE: "step_status_done",
}
