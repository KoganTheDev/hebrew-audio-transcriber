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
    # The speaker chip is FILLED now (Phase 4), not coloured text on a
    # transparent chip - the pairing that actually renders on the page is
    # --spk-N-chip-text on ITS OWN --spk-N fill, not --spk-N as text against
    # --surface-hover. That old pairing is asserted nowhere in the
    # stylesheet any more (the same reasoning this file already applies to
    # excluding .toast from the surface sweep below: check the pairing that
    # is real, not the one that used to be), so it is replaced rather than
    # kept alongside the new one - keeping both would mean re-imposing the
    # old outlined-chip design's contrast requirement on a component that no
    # longer has that design, which could fail a palette that is actually
    # fine.
    ("--spk-0-chip-text", "--spk-0", TEXT_MIN),
    ("--spk-1-chip-text", "--spk-1", TEXT_MIN),
    ("--spk-2-chip-text", "--spk-2", TEXT_MIN),
    ("--spk-3-chip-text", "--spk-3", TEXT_MIN),
    ("--spk-4-chip-text", "--spk-4", TEXT_MIN),
    ("--spk-5-chip-text", "--spk-5", TEXT_MIN),
    ("--spk-6-chip-text", "--spk-6", TEXT_MIN),
    ("--spk-7-chip-text", "--spk-7", TEXT_MIN),
    # The dotted underline is one of the two carriers of "the model was unsure
    # here" - the tint alone must not be the only signal, so it has to be seen.
    ("--warn-line", "--warn-bg", UI_MIN),
    ("--focus", "--bg", UI_MIN),
    # --control-border is load-bearing now, not decoration: the squircle
    # redesign made a control's resting border its primary "this is a
    # control" signal (see the token's own definition in transcript.css for
    # why --rule, at 1.26:1, was the wrong token to reuse for that job).
    # WCAG 1.4.11 wants >= 3:1 for a boundary a component is identified by -
    # checked against both backgrounds a resting or hovered control sits on.
    ("--control-border", "--bg", UI_MIN),
    ("--control-border", "--surface-hover", UI_MIN),
    # The backdrop photo used to be the thing that separated a panel (.source,
    # .outline, menus) from the page ground - text on a panel sat on a
    # composited photo-under-translucent-paper background that could only be
    # bounded by worst-case pixel simulation (the sweep this file used to run,
    # see git history). With the backdrop removed the panel is a flat token
    # like any other, so "every text-bearing surface is proven legible"
    # becomes ordinary rows here instead of a separate composite sweep - one
    # row per surface (--bg, --panel, --surface-hover) for every foreground
    # that actually renders on it: body text, muted/content text, the
    # control-border boundary, the focus ring, and the accent colour (turn
    # accent bars, links, active states). --surface-hover's own rows above
    # already cover --text/--muted/--control-border against it, so only the
    # two new surfaces plus the two new foregrounds are added below.
    ("--text", "--panel", TEXT_MIN),
    ("--muted", "--panel", TEXT_MIN),
    ("--control-border", "--panel", UI_MIN),
    ("--focus", "--panel", UI_MIN),
    ("--focus", "--surface-hover", UI_MIN),
    ("--accent", "--bg", UI_MIN),
    ("--accent", "--panel", UI_MIN),
    ("--accent", "--surface-hover", UI_MIN),
    # Tier 1 (see .tb-btn.primary in transcript.css): the primary button's
    # own text colour has to stay legible on both its hover/active fill
    # (--accent-hover), not just its resting one (--accent, already checked
    # via --accent-text/--accent above).
    ("--accent-text", "--accent-hover", TEXT_MIN),
    # Tier 3 (see .tb-btn[aria-pressed="true"]): a toggle's own label is real
    # content sitting on its --accent-tint fill once it is "on", so --text
    # has to hold there too; the inset box-shadow border is non-text UI, held
    # to the 3:1 floor against the same fill it sits on.
    ("--text", "--accent-tint", TEXT_MIN),
    ("--accent", "--accent-tint", UI_MIN),
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


def _rule_block(source, selector):
    """The raw declaration text of one top-level `selector { ... }` rule -
    unlike _block()/_tokens() above, this keeps ordinary properties
    (grid-template-columns, max-width), not just --custom-properties."""
    pattern = r"^" + re.escape(selector) + r"\s*\{(.*?)\n\}"
    match = re.search(pattern, source, re.S | re.M)
    assert match, f"could not find {selector} {{ ... }} in transcript.css"
    return match.group(1)


def _property(block, name):
    match = re.search(r"(?<![-\w])" + re.escape(name) + r"\s*:\s*([^;]+);", block)
    assert match, f"{name!r} not found in block: {block!r}"
    return match.group(1).strip()


def test_layout_and_toolbar_share_the_same_grid_columns():
    """
    The 156px toolbar/column misalignment this replaced came from .toolbar
    and .layout each computing their own centred max-width independently -
    two boxes of different widths, centred separately, cannot line up. The
    fix is a single --layout-columns (and matching max-width formula) both
    grids read, which this checks structurally: if either rule drifts back
    to its own hand-written grid-template-columns or max-width, the two
    boxes stop being guaranteed to agree, even if today's numbers happen to
    match by coincidence.
    """
    source = CSS.read_text(encoding="utf-8")
    assert "--layout-columns:" in source

    layout = _rule_block(source, ".layout")
    toolbar = _rule_block(source, ".toolbar")
    assert _property(layout, "grid-template-columns") == "var(--layout-columns)"
    assert _property(toolbar, "grid-template-columns") == "var(--layout-columns)"
    # Same max-width formula, not merely "some max-width" - a value that
    # happens to equal the same number today but is spelled differently
    # would still pass a looser check and still be free to drift apart.
    assert _property(layout, "max-width") == _property(toolbar, "max-width")


def test_toolbar_row_sits_in_the_shared_main_column():
    """.tb-row (not .toolbar itself) is what's actually placed in track 2 -
    see the comment on .tb-row in transcript.css for why the controls
    couldn't be grid items of .toolbar directly."""
    source = CSS.read_text(encoding="utf-8")
    tb_row = _rule_block(source, ".tb-row")
    assert _property(tb_row, "grid-column") == "2"


def test_flanks_are_flexible_not_fixed():
    """
    minmax(0, var(--rail)), not a bare var(--rail) - a fixed flank can't
    give width back to main as the viewport narrows, which is what forced
    main below its own reading measure well before the layout had to
    collapse. See --layout-columns's own comment for the full reasoning.
    """
    source = CSS.read_text(encoding="utf-8")
    match = re.search(r"--layout-columns:\s*([^;]+);", source)
    assert match, "--layout-columns not found in transcript.css"
    assert "minmax(0, var(--rail))" in match.group(1)
    # var(--measure) alone (not wrapped in minmax) is what keeps the centre
    # track rigid - main holding its full width, rather than main shrinking
    # in step with the flanks, is the entire point of this layout.
    assert re.search(r"(?<!minmax\()\bvar\(--measure\)", match.group(1))


def test_outline_toggle_breakpoint_matches_the_measured_flank_minimum():
    """
    1200px, not the pre-Phase-2 900px - that number was measured against a
    fixed 18rem sidebar and stopped being correct the moment the flanks
    became flexible (they get squeezed well before 900px). See the
    @media (max-width: 1200px) comment in transcript.css for how 1200 was
    actually measured (a same-origin iframe at that width, real Chrome
    layout, not a formula) rather than picked as a round number.
    """
    source = CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 1200px)" in source
    assert "@media (max-width: 900px)" not in source


def test_only_the_shared_rule_declares_layout_grid_columns():
    """
    The narrow-screen media query's first draft overrode
    `.layout { grid-template-columns: ... }` directly instead of redefining
    the --layout-columns token, which collapsed .layout to a single track
    while .toolbar kept its three - reintroducing, inside the very media
    query meant to fix the layout, the exact 156px divergence
    --layout-columns exists to prevent (see that token's own comment, and
    the @media (max-width: 1200px) comment in transcript.css). This checks
    the whole file, not just the base rules: grid-template-columns must be
    declared for .layout, and separately for .toolbar, in exactly one place
    each - the shared base rule reading var(--layout-columns) - never as a
    direct property override anywhere else, including inside a media query.
    """
    source = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)

    def rules_declaring_gtc_for(class_name):
        hits = []
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
            selector, body = match.group(1).strip(), match.group(2)
            if "grid-template-columns" not in body:
                continue
            if re.search(r"\." + class_name + r"\b", selector):
                hits.append(selector)
        return hits

    for class_name in ("layout", "toolbar"):
        hits = rules_declaring_gtc_for(class_name)
        assert hits == ["." + class_name], (
            f".{class_name}'s grid-template-columns must be declared in exactly one "
            f"place (the shared base rule reading var(--layout-columns)); any other "
            f"occurrence bypasses the shared token. Found: {hits}"
        )


def test_speaker_row_reacts_to_hover_and_focus():
    """
    .speaker-row used to have no :hover rule at all, so it read as inert
    beside .turn and .outline-files a, both of which react - this is the bug
    the user reported directly. :focus-within has to be paired with :hover
    (not :hover alone), because the row contains a real <input>
    (.speaker-name) and a keyboard user tabbing into it needs the same
    grouping cue a mouse user hovering the row already gets.
    """
    source = CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.speaker-row:hover,\s*\.speaker-row:focus-within\s*\{([^}]*)\}", source
    )
    assert match, (
        ".speaker-row:hover, .speaker-row:focus-within rule not found in transcript.css"
    )
    assert re.search(r"background\s*:", match.group(1)), (
        ".speaker-row's hover/focus-within rule must set a background"
    )


def test_panel_token_is_actually_used():
    """
    --panel is the raised reading surface that replaced "translucent paper
    over a photo" once the backdrop was removed (Phase 3.5). If .source or
    .outline silently fell back to --bg (the page ground) instead, a panel
    would be visually indistinguishable from the page behind it - the whole
    elevation ramp would be invisible - and nothing else in this file would
    notice, since the contrast pairs above check colour values, not which
    token a rule actually resolves through.
    """
    source = CSS.read_text(encoding="utf-8")
    for selector in (".source", ".outline"):
        block = _rule_block(source, selector)
        assert _property(block, "background") == "var(--panel)", (
            f"{selector} must declare background: var(--panel)"
        )
