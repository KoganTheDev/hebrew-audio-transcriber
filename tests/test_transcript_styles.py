"""
Contrast guarantees for the generated transcript's stylesheet.

The palette was audited once by hand and several tokens were darkened to clear
WCAG 2.1 minimums. That audit is worth exactly nothing the moment somebody
nudges a colour "just a little" to taste, which is why it lives here as a test
rather than in a one-off script: the numbers are cheap to recompute and the
failure mode they prevent (Hebrew body text at 4.2:1 that nobody notices) is
invisible in review.

Both colour schemes are checked independently. Dark mode is not the light
palette inverted - it has its own tokens, and a pair that passes in one scheme
routinely fails in the other. The active search highlight is the standing
example: light body text on the mid-brightness amber measured 2.83:1, while the
same pairing in light mode was fine at 11.24:1.
"""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "speech_to_text" / "core" / "assets" / "transcript.css"

# Minimums from WCAG 2.1: 4.5:1 for normal-size text, 3:1 for non-text UI that
# still has to be seen (borders that signal state, the focus ring).
TEXT_MIN = 4.5
UI_MIN = 3.0

# (foreground token, background token, minimum). Only pairs that actually occur
# in the stylesheet - a table of every combination would be noise.
PAIRS = [
    ("--text", "--bg", TEXT_MIN),
    ("--text", "--surface-hover", TEXT_MIN),
    # Timestamps and the save-status label are real content, not decoration,
    # so --muted is held to the text minimum rather than the UI one.
    ("--muted", "--bg", TEXT_MIN),
    ("--muted", "--surface-hover", TEXT_MIN),
    ("--text", "--warn-bg", TEXT_MIN),
    ("--text", "--hit-bg", TEXT_MIN),
    ("--hit-current-text", "--hit-current", TEXT_MIN),
    ("--accent-text", "--accent", TEXT_MIN),
    # Speaker names are coloured text, and they carry a speaker's identity.
    # Eight, not four - added/recoloured speakers can wear any of them, so
    # every slot in SPEAKER_PALETTE_SIZE (core/formatting.py) has to clear
    # the same bar a colour someone just eyeballed never gets checked against.
    ("--spk-0", "--surface-hover", TEXT_MIN),
    ("--spk-1", "--surface-hover", TEXT_MIN),
    ("--spk-2", "--surface-hover", TEXT_MIN),
    ("--spk-3", "--surface-hover", TEXT_MIN),
    ("--spk-4", "--surface-hover", TEXT_MIN),
    ("--spk-5", "--surface-hover", TEXT_MIN),
    ("--spk-6", "--surface-hover", TEXT_MIN),
    ("--spk-7", "--surface-hover", TEXT_MIN),
    # The dotted underline is one of the two carriers of "the model was unsure
    # here" - the tint alone must not be the only signal, so it has to be seen.
    ("--warn-line", "--warn-bg", UI_MIN),
    ("--focus", "--bg", UI_MIN),
]


def _relative_luminance(hex_colour):
    """WCAG 2.1 relative luminance."""
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground, background):
    a, b = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _tokens(block_source):
    """Custom properties in one block, with single-level var() indirection resolved."""
    found = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block_source))
    resolved = {}
    for name, value in found.items():
        value = value.strip()
        reference = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if reference:
            value = found.get(reference.group(1), value).strip()
        resolved[name] = value
    return resolved


def _block(pattern):
    source = CSS.read_text(encoding="utf-8")
    match = re.search(pattern + r"\s*\{(.*?)\n\}", source, re.S | re.M)
    assert match, f"could not find the {pattern!r} block in transcript.css"
    return _tokens(match.group(1))


SCHEMES = {
    "light": _block(r"^:root"),
    "dark": _block(r"^:root\[data-theme=\"dark\"\]"),
}


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
@pytest.mark.parametrize("foreground,background,minimum", PAIRS)
def test_contrast_meets_wcag(scheme, foreground, background, minimum):
    tokens = SCHEMES[scheme]
    fg, bg = tokens.get(foreground), tokens.get(background)
    assert fg and fg.startswith("#"), f"{foreground} missing or not a hex colour in {scheme}"
    assert bg and bg.startswith("#"), f"{background} missing or not a hex colour in {scheme}"

    ratio = contrast_ratio(fg, bg)
    assert ratio >= minimum, (
        f"{scheme}: {foreground} ({fg}) on {background} ({bg}) "
        f"is {ratio:.2f}:1, below the {minimum}:1 minimum"
    )


def _rgb(hex_or_triplet):
    """Accept either "#rrggbb" or a "r, g, b" custom-property value as (r, g, b) ints."""
    value = hex_or_triplet.strip()
    if value.startswith("#"):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(part.strip()) for part in value.split(","))


def _mix(background_hex, pixel_rgb, opacity):
    """Composite `background_hex` under a layer at `opacity`, as hex."""
    bg = _rgb(background_hex)
    mixed = [bg[i] * (1 - opacity) + pixel_rgb[i] * opacity for i in range(3)]
    return "#" + "".join(f"{round(c):02x}" for c in mixed)


# The composited background under text is no longer a fixed token once a photo
# sits behind it - it is bg*(1-a) + p*a for whatever pixel p happens to be
# under a given letter, and the reading column adds a second layer on top of
# that: a translucent panel (--panel-opacity, over --bg-rgb) floating over the
# backdrop rather than masking it out. Text therefore sits on THREE composited
# layers - panel over backdrop over bg - not the two the panel-less design
# had. Auditing every pixel of 32 photos is not the point; bounding the worst
# case is. p=black and p=white are the two extremes any backdrop pixel could
# land on, so a token that clears 4.5:1 against both of them, through the
# panel, clears it against everything in between too.
BACKDROP_PAIRS = [
    # (foreground token, minimum) - backgrounds are the three-layer composited
    # extremes, built below per scheme from --bg, --backdrop-opacity,
    # --bg-rgb and --panel-opacity.
    ("--text", TEXT_MIN),
    # Timestamps and the save-status label render straight over the backdrop,
    # outside the panel (see .toolbar / .player in transcript.css, both
    # transparent-free and outside .source), so --muted has to hold here too,
    # not just against the flat tokens above.
    ("--muted", TEXT_MIN),
]


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
@pytest.mark.parametrize("foreground,minimum", BACKDROP_PAIRS)
@pytest.mark.parametrize("pixel", [(0, 0, 0), (255, 255, 255)], ids=["black", "white"])
def test_backdrop_worst_case_contrast_meets_wcag(scheme, foreground, minimum, pixel):
    tokens = SCHEMES[scheme]
    fg = tokens.get(foreground)
    bg = tokens.get("--bg")
    backdrop_opacity = tokens.get("--backdrop-opacity")
    panel_rgb = tokens.get("--bg-rgb")
    panel_opacity = tokens.get("--panel-opacity")
    assert fg and fg.startswith("#"), f"{foreground} missing or not a hex colour in {scheme}"
    assert bg and bg.startswith("#"), f"--bg missing or not a hex colour in {scheme}"
    assert backdrop_opacity, f"--backdrop-opacity missing in {scheme}"
    assert panel_rgb, f"--bg-rgb missing in {scheme}"
    assert panel_opacity, f"--panel-opacity missing in {scheme}"

    # Layer 1: the backdrop photo pixel over --bg.
    behind_panel = _mix(bg, pixel, float(backdrop_opacity))
    # Layer 2: the translucent panel over that.
    composited = _mix(behind_panel, _rgb(panel_rgb), float(panel_opacity))

    ratio = contrast_ratio(fg, composited)
    assert ratio >= minimum, (
        f"{scheme}: {foreground} ({fg}) on panel-over-backdrop {composited} "
        f"(--bg {bg} at {backdrop_opacity} over {pixel}, panel {panel_rgb} "
        f"at {panel_opacity}) is {ratio:.2f}:1, below the {minimum}:1 minimum"
    )


def test_both_dark_blocks_stay_in_step():
    """
    Dark mode is declared twice - once under prefers-color-scheme for the
    system default, once under [data-theme="dark"] for the in-page toggle. They
    have to hold the same values, or the toggle silently changes the palette
    rather than only changing when it applies.
    """
    media = _block(
        r"@media \(prefers-color-scheme: dark\)\s*\{"
        r"\s*:root:not\(\[data-theme=\"light\"\]\)"
    )
    assert media == SCHEMES["dark"]
