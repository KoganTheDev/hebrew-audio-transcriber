"""
Contrast guarantees for the PyQt5 app's own palette, speech_to_text.gui.theme.COLORS.

Sibling to tests/test_transcript_styles.py, which does the identical job for
the HTML transcript document's stylesheet - see that file's module docstring
for the motivating story. The app palette has its own version of exactly the
same failure mode: text_tertiary was originally overlay0 (#6c7086), which
measures 3.36:1 against the card background (bg_tertiary), below the 4.5:1
body-text floor, while carrying real caption text (model card descriptions,
the transcription step's status line). It was only caught by hand-computing
the ratio during the palette audit that theme.py's COLORS comments now
document inline - nothing stopped a later edit from quietly reintroducing it,
which is what this file is for.

Put beside test_transcript_styles.py rather than folded into test_gui.py:
test_gui.py drives widget behaviour (it needs a QApplication and real widget
instances), while this - like test_transcript_styles.py - only ever reads a
plain Python dict of hex strings. Keeping it separate means it collects and
runs without needing Qt at all.

contrast_ratio() and _relative_luminance() are imported from
test_transcript_styles rather than copied: the maths (WCAG 2.1 relative
luminance and contrast ratio) has exactly one correct implementation, and a
second hand-typed copy is a second place for a transcription slip to hide.
"""

import pytest

from speech_to_text.gui.theme import COLORS
from tests.test_transcript_styles import contrast_ratio

TEXT_MIN = 4.5
UI_MIN = 3.0

# The three surfaces text and controls actually render on in this app -
# crust/mantle/base, i.e. bg_primary (window ground), bg_secondary (header
# and nav bar) and bg_tertiary (cards and panels). Not surface_hover: nothing
# in COLORS's own comments measures a ratio against it, and treating a hover
# state as a fourth "ground" would be asserting a pairing nobody audited by
# hand in the first place - see this file's own module docstring on
# asserting what renders, not every combination.
GROUNDS = ["bg_primary", "bg_secondary", "bg_tertiary"]

# (foreground token, background token, minimum). Only pairs that actually
# occur on screen - see test_transcript_styles.PAIRS for why a table of every
# possible combination would be noise rather than signal.
PAIRS = []

# Body text on every ground it can sit on. text_tertiary is here deliberately
# - it is the one token this file exists to guard (see module docstring) -
# held to the same 4.5:1 floor as its two siblings, no special-casing.
for _fg in ("text_primary", "text_secondary", "text_tertiary"):
    for _bg in GROUNDS:
        PAIRS.append((_fg, _bg, TEXT_MIN))

# Semantic colours (the accent brand colour, success/error states) are all
# used as text at some point - accent for the header title and links, success
# for the step-3 headline, error for the banner message - so all three hold
# the text floor on every ground, not just the UI floor a mere icon tint
# would need.
for _fg in ("accent", "success", "error"):
    for _bg in GROUNDS:
        PAIRS.append((_fg, _bg, TEXT_MIN))

# accent_text is the ink painted ON a filled accent surface - the primary
# button's label - never against one of the three window grounds directly,
# so its pairing is with the three accent FILLS a button can show
# (resting/hover/pressed - see button_primary_qss), not with GROUNDS.
for _bg in ("accent", "accent_hover", "accent_dark"):
    PAIRS.append(("accent_text", _bg, TEXT_MIN))

# control_border is the resting outline of every bordered control (model
# cards, secondary buttons, checkboxes/radios/spin boxes - see its own
# comment in theme.py) - WCAG 1.4.11's 3:1 floor for a boundary a control is
# identified by, not the 4.5:1 body-text floor, because it never carries
# text of its own.
for _bg in GROUNDS:
    PAIRS.append(("control_border", _bg, UI_MIN))

# focus is the keyboard-focus ring's own colour (see gui/focus.py and the
# [kbdFocus="true"] rules in theme.py) - also a non-text UI signal, held to
# the same 3:1 floor as control_border.
for _bg in GROUNDS:
    PAIRS.append(("focus", _bg, UI_MIN))

# text_disabled is deliberately EXCLUDED from PAIRS above, not silently
# omitted - see theme.py's own comment on the token for the full numbers
# (3.84 / 3.59 / 3.36 against crust/mantle/base). It fails the 4.5:1
# body-text floor on two of the three grounds by design: WCAG 1.4.3 exempts
# inactive-control text from the contrast floor entirely (a disabled button's
# label being harder to read is the point - it signals "you can't act on
# this" partly through that reduced legibility), and the only other place
# this token is used is muted icon tints, which only need to clear 3:1.
# Holding it to the 4.5:1 floor here would fail a token that is correct as
# shipped; leaving it out of PAIRS with no explanation would look like an
# oversight to the next person who reads this file and reintroduces it as a
# caption colour by mistake - hence this comment, not just the omission.


@pytest.mark.parametrize("foreground,background,minimum", PAIRS)
def test_contrast_meets_wcag(foreground, background, minimum):
    fg, bg = COLORS.get(foreground), COLORS.get(background)
    assert fg and fg.startswith("#"), f"{foreground} missing or not a hex colour in COLORS"
    assert bg and bg.startswith("#"), f"{background} missing or not a hex colour in COLORS"

    ratio = contrast_ratio(fg, bg)
    assert ratio >= minimum, (
        f"{foreground} ({fg}) on {background} ({bg}) is {ratio:.2f}:1, "
        f"below the {minimum}:1 minimum"
    )
