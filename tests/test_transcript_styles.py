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

import pytest

from speech_to_text.core.formatting.assets import _asset_dir


def _css_source() -> str:
    """
    The full stylesheet, concatenated from its css/ fragments in load order
    - the same text render_html() actually inlines. transcript.css became a
    directory of numerically-prefixed fragments (see _asset_dir()'s own
    docstring); this is the one place that reassembly happens for every test
    below, so each of them keeps checking exactly what ships rather than a
    single transcript.css file that no longer exists.
    """
    return _asset_dir("css")

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
    # --panel is the flat token now used only by popovers (.swatch-menu,
    # .spk-menu) - a popover reads as MORE raised than the translucent panel
    # it opened from, so it deliberately stays opaque rather than compositing
    # against the backdrop too (see those rules' own comments). .source and
    # .outline themselves moved to rgba(var(--panel-rgb), var(--panel-opacity))
    # once the backdrop photo came back (Phase 5) and are checked by
    # test_backdrop_worst_case_contrast_meets_wcag below instead, which
    # models the actual three-layer stack (panel over backdrop over bg) - a
    # flat-token row here would only prove the popover case, not theirs.
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


def _tokens(block_source, extra=None):
    """
    Custom properties in one block, with one level of var() indirection
    resolved - first against this block's own declarations, then (if
    `extra` is given) against another block's tokens too. The second lookup
    exists for the dark palette: both dark-mode activation rules
    (@media (prefers-color-scheme: dark) and :root[data-theme="dark"]) now
    only ever write `var(--dark-X)` references (see the --dark-* block's
    own comment in css/00-tokens.css) - the actual hex values live once, in
    the plain :root block, so resolving an activation rule's tokens needs
    that block's tokens as a fallback.
    """
    found = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block_source))
    lookup = dict(extra or {})
    lookup.update(found)
    resolved = {}
    for name, value in found.items():
        value = value.strip()
        reference = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if reference:
            value = lookup.get(reference.group(1), value).strip()
        resolved[name] = value
    return resolved


def _raw_block(pattern):
    """The unresolved declaration text of one `selector { ... }` block."""
    source = _css_source()
    match = re.search(pattern + r"\s*\{(.*?)\n\}", source, re.S | re.M)
    assert match, f"could not find the {pattern!r} block in the stylesheet"
    return match.group(1)


def _block(pattern, extra=None):
    return _tokens(_raw_block(pattern), extra=extra)


_LIGHT = _block(r"^:root")
SCHEMES = {
    "light": _LIGHT,
    # extra=_LIGHT: see _tokens()'s own docstring for why the dark
    # activation rule's tokens only resolve with the plain :root block's
    # tokens (where the --dark-* canonical values actually live) in scope.
    "dark": _block(r"^:root\[data-theme=\"dark\"\]", extra=_LIGHT),
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
    """Composite `pixel_rgb` at `opacity` over `background_hex`, as hex."""
    bg = _rgb(background_hex)
    mixed = [bg[i] * (1 - opacity) + pixel_rgb[i] * opacity for i in range(3)]
    return "#" + "".join(f"{round(c):02x}" for c in mixed)


# The composited background under text is no longer a fixed token once a photo
# sits behind it - it is bg*(1-a) + p*a for whatever pixel p happens to be
# under a given letter, and the reading column adds a second layer on top of
# that: a translucent panel (--panel-opacity, over --panel-rgb) floating over
# the backdrop rather than masking it out. Text therefore sits on THREE
# composited layers - panel over backdrop over bg - not the two the panel-less
# design had. --panel-rgb, NOT --bg-rgb: Anuppuccin (Phase 0) gave the panel
# its own elevation token, one step above --bg, so compositing against --bg
# here would model a surface nothing text-bearing actually sits on any more.
#
# Auditing every pixel of 32 photos is not the point; bounding the worst case
# is. p=black and p=white are the two extremes any backdrop pixel could land
# on - genuinely, not hypothetically: several of the shipped vistas contain
# pure-black or pure-white pixels (see docs/transcript-manual-checks.md) - so
# a token that clears 4.5:1 against both of them, through the panel, clears it
# against everything in between too.
BACKDROP_PAIRS = [
    # (foreground token, minimum) - backgrounds are the three-layer composited
    # extremes, built below per scheme from --bg, --backdrop-opacity,
    # --panel-rgb and --panel-opacity.
    ("--text", TEXT_MIN),
    # --muted is the tighter of the two (timestamps and the file-position
    # label are real content rendered inside the translucent .source/.file-bar
    # panel, not decoration), which is why it is the number quoted when this
    # test's result is discussed rather than --text.
    ("--muted", TEXT_MIN),
]


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
@pytest.mark.parametrize("foreground,minimum", BACKDROP_PAIRS)
@pytest.mark.parametrize("pixel", [(0, 0, 0), (255, 255, 255)], ids=["black", "white"])
def test_backdrop_worst_case_contrast_meets_wcag(scheme, foreground, minimum, pixel):
    """
    The single most important test in this file: it is the only thing
    standing between a future opacity tweak and unreadable text over a photo.
    If this fails, the fix is a different treatment (a stronger panel, a
    different device entirely) - never nudging the minimum to match whatever
    the current numbers happen to be.
    """
    tokens = SCHEMES[scheme]
    fg = tokens.get(foreground)
    bg = tokens.get("--bg")
    backdrop_opacity = tokens.get("--backdrop-opacity")
    panel_rgb = tokens.get("--panel-rgb")
    panel_opacity = tokens.get("--panel-opacity")
    assert fg and fg.startswith("#"), f"{foreground} missing or not a hex colour in {scheme}"
    assert bg and bg.startswith("#"), f"--bg missing or not a hex colour in {scheme}"
    assert backdrop_opacity, f"--backdrop-opacity missing in {scheme}"
    assert panel_rgb, f"--panel-rgb missing in {scheme}"
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


def test_dark_activation_rules_reference_shared_canonical_tokens():
    """
    Dark mode has to be reachable two ways - the system default, under
    @media (prefers-color-scheme: dark), and an explicit in-page toggle,
    under :root[data-theme="dark"] - and those two conditions cannot be
    joined into one selector (one only applies inside a media query, the
    other has to apply regardless of the system preference). That used to
    mean the same 38 hex values were typed out twice, independently, in the
    two activation blocks - caught only by this test comparing the two
    blocks value for value, which is exactly the kind of check that is easy
    to forget to run in your head while hand-editing a colour.

    Each hex value now lives exactly once, as a --dark-* token in :root
    (see css/00-tokens.css); both activation blocks below only ever write
    `var(--dark-X)` references to it. That makes the two blocks impossible
    to disagree about a *value* - there is only one value left to disagree
    about - so what is left to check is the structural guarantee itself:
    every declaration in both blocks has to be a var(--dark-*) reference,
    and the two blocks have to name the same set of variables. A future
    edit that typed a raw hex into either block again, instead of adding a
    new --dark-* token and referencing it, would fail here immediately.
    """
    media_raw = _raw_block(
        r"@media \(prefers-color-scheme: dark\)\s*\{"
        r"\s*:root:not\(\[data-theme=\"light\"\]\)"
    )
    toggle_raw = _raw_block(r"^:root\[data-theme=\"dark\"\]")

    def declared_vars(raw):
        decls = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", raw))
        assert decls, "no custom properties found in the activation block"
        for name, value in decls.items():
            match = re.fullmatch(r"var\((--dark-[\w-]+)\)", value.strip())
            assert match, (
                f"{name} does not resolve through a --dark-* token: {value!r} "
                "- every declaration in a dark-mode activation rule must be "
                "a var(--dark-X) reference into the canonical block in "
                "css/00-tokens.css, never a literal value"
            )
        return decls

    media_vars = declared_vars(media_raw)
    toggle_vars = declared_vars(toggle_raw)
    assert media_vars == toggle_vars, (
        "the two dark-mode activation rules reference different --dark-* "
        "tokens (or different sets of properties) - see this test's own "
        "docstring for why they must name exactly the same ones"
    )


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
    source = _css_source()
    assert "--layout-columns:" in source

    layout = _rule_block(source, ".layout")
    toolbar = _rule_block(source, ".toolbar")
    assert _property(layout, "grid-template-columns") == "var(--layout-columns)"
    assert _property(toolbar, "grid-template-columns") == "var(--layout-columns)"
    # Same max-width formula, not merely "some max-width" - a value that
    # happens to equal the same number today but is spelled differently
    # would still pass a looser check and still be free to drift apart.
    assert _property(layout, "max-width") == _property(toolbar, "max-width")


def test_toolbar_row_sits_across_both_tracks():
    """.tb-row spans both tracks (grid-column: 1 / -1), not just track 1 -
    see the comment on .tb-row in transcript.css for why. Confined to a
    single track the toolbar would only have the reading column to lay its
    controls out in, leaving the whole rail column empty above the sidebar;
    spanning hands it the rail's width too while the row's own inline-start
    edge still shares an edge with the reading column, same as before."""
    source = _css_source()
    tb_row = _rule_block(source, ".tb-row")
    assert _property(tb_row, "grid-column") == "1 / -1"


def test_rail_is_fixed_and_main_is_the_flexible_track():
    """
    The two-track layout (main / rail, no third empty flank - see
    --layout-columns's own comment for why the flank is gone) deliberately
    inverts which track is allowed to shrink, compared to the three-track
    layout it replaced. That old layout made the FLANKS flexible
    (minmax(0, var(--rail))) and kept the centre track (main) rigid
    (var(--measure) alone), because a fixed flank couldn't give width back
    to main as the viewport narrowed - main was the one thing that must
    never shrink out of its comfortable reading width.

    That reasoning still holds, but it was pointed at the wrong track once
    the empty flank was gone: the rail carries a real functional floor of
    its own (a colour swatch plus a name input, ~140px), while body text
    reflows perfectly well. So now main is the flexible track
    (minmax(0, var(--measure))) and the rail is fixed - a bare var(--rail),
    not wrapped in minmax() - which is the reverse of the old assertion,
    not a variation on it.
    """
    source = _css_source()
    match = re.search(r"--layout-columns:\s*([^;]+);", source)
    assert match, "--layout-columns not found in transcript.css"
    columns = match.group(1)
    assert "minmax(0, var(--measure))" in columns
    # var(--rail) alone (not wrapped in minmax) is what keeps the rail
    # track rigid - never shrinking below its functional floor is the
    # entire point of this reversal.
    assert re.search(r"(?<!minmax\()\bvar\(--rail\)", columns)
    # No third track: the old empty flank that used to sit ahead of main is
    # gone outright, not just made non-flexible.
    assert columns.count("var(--rail)") == 1


def test_stacking_breakpoint_matches_the_two_column_reading_measure():
    """
    819px/820px, not the retired 1200px overlay breakpoint. That number
    doesn't carry over: it was measured against a FLEXIBLE flank being
    squeezed thin enough to break .speaker-name, a failure mode that no
    longer exists now the rail is a rigid 16rem (see
    test_rail_is_fixed_and_main_is_the_flexible_track) - a rigid track
    never gets squeezed, so there is nothing left to time a breakpoint
    against that way.

    819/820 was chosen instead by looking at a real render: at 820px the
    two-column layout still leaves 468px of reading measure with the
    toolbar holding one line, and below that the measure starts
    compressing faster than the rigid rail can give width back. See the
    @media (max-width: 819px) block's own comment in transcript.css for
    the full reasoning, including why max-width and not min-width (this
    file is desktop-first throughout, matching every other breakpoint in
    it).
    """
    source = _css_source()
    assert "@media (max-width: 819px)" in source
    assert "@media (max-width: 1200px)" not in source
    assert "@media (max-width: 900px)" not in source


def test_two_column_layout_is_the_unconditional_default():
    """
    This file is desktop-first: the two-column template (main / rail, no
    upper bound) is the value --layout-columns has with no media query
    involved at all, and the max-width: 819px block is what narrows it
    down for small screens - not the other way around. If a later edit
    wraps the two-column value in a min-width query instead, .layout and
    .toolbar would go back to the old three-track default (or nothing)
    below that width until the min-width query kicked in, which is exactly
    the kind of accidental gap this checks for.
    """
    source = re.sub(r"/\*.*?\*/", "", _css_source(), flags=re.S)
    root_block = _rule_block(source, ":root")
    assert _property(root_block, "--layout-columns") == (
        "minmax(0, var(--measure)) var(--rail)"
    )
    assert "@media (min-width:" not in source


def test_toolbar_fluid_tokens_top_out_at_the_shipped_values():
    """
    Every clamp() backing --tb-font/--tb-pad/--tb-gap/--tb-row-gap has to
    top out at exactly the value that shipped before the fluid toolbar -
    0.9rem type, 0.6rem padding, 0.4rem gap, 1.25rem row-gap - so that
    nothing changes at the widest screens at all; the scale only engages as
    the toolbar loses room. A clamp() that drifted from these on a later
    edit would silently resize the toolbar on every existing wide-screen
    render, which is the one case this feature was explicitly not supposed
    to touch.
    """
    source = _css_source()
    root_block = _rule_block(source, ":root")
    tops = {
        "--tb-font": "0.9rem",
        "--tb-pad": "0.6rem",
        "--tb-gap": "0.4rem",
        "--tb-row-gap": "1.25rem",
    }
    for token, top in tops.items():
        value = _property(root_block, token)
        assert value.startswith("clamp(") and value.endswith(")"), (
            f"{token} is no longer a clamp(): {value!r}"
        )
        args = [part.strip() for part in value[len("clamp("):-1].split(",")]
        assert len(args) == 3, f"{token} clamp() does not have three arguments: {value!r}"
        assert args[2] == top, f"{token} tops out at {args[2]!r}, expected {top!r}"


def test_outline_never_fully_hidden_at_any_width():
    """
    The old design hid the sidebar behind a toggle below 1200px
    (display: none, revealed only by #outline-toggle, which no longer
    exists anywhere in the markup or this stylesheet). The whole point of
    this layout is that the outline is always part of the page's own flow -
    a rail beside <main> down to the stacking breakpoint, then a band above
    it - so `display: none` must never appear anywhere .outline is styled,
    at any width.
    """
    source = re.sub(r"/\*.*?\*/", "", _css_source(), flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
        selector, body = match.group(1).strip(), match.group(2)
        # Only the rightmost compound - the actual element a rule targets,
        # not an ancestor named earlier in a descendant selector. E.g.
        # ".outline.js-ready .outline-speakers .speakers:not(.active)" sets
        # display: none on .speakers (a per-file panel, filtered down to the
        # current file - see that rule's own comment in transcript.css),
        # not on the aside itself, and must not trip this check.
        subject = re.split(r"[\s>+~]+", selector)[-1] if selector else ""
        if re.search(r"\.outline(?![\w-])", subject):
            assert "display: none" not in body, (
                f"{selector} sets display: none, hiding the outline entirely"
            )
    assert "#outline-toggle" not in source


def test_only_the_shared_rule_declares_layout_grid_columns():
    """
    The narrow-screen media query's first draft overrode
    `.layout { grid-template-columns: ... }` directly instead of redefining
    the --layout-columns token, which collapsed .layout to a single track
    while .toolbar kept its two - reintroducing, inside the very media
    query meant to fix the layout, the exact kind of divergence
    --layout-columns exists to prevent (see that token's own comment, and
    the @media (max-width: 819px) comment in transcript.css). This checks
    the whole file, not just the base rules: grid-template-columns must be
    declared for .layout, and separately for .toolbar, in exactly one place
    each - the shared base rule reading var(--layout-columns) - never as a
    direct property override anywhere else, including inside a media query.
    """
    source = re.sub(r"/\*.*?\*/", "", _css_source(), flags=re.S)

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
    source = _css_source()
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
    .source and .outline are the translucent reading surfaces the backdrop
    photo shows through (Phase 5) - rgba(var(--panel-rgb), var(--panel-opacity)),
    not the flat --panel. If either silently fell back to --panel or --bg
    instead, the panel would stop being see-through - the whole point of the
    backdrop coming back - and nothing else in this file would notice, since
    the contrast pairs above check colour values, not which token a rule
    actually resolves through.

    Popovers (.swatch-menu, .spk-menu) are the deliberate opposite case: they
    stay on the flat --panel because a popover reads as MORE raised than its
    translucent container, not equally see-through - see those rules' own
    comments. Checked here too, so a future edit can't quietly blur the two
    surfaces' roles back together.
    """
    source = _css_source()
    for selector in (".source", ".outline", ".file-bar"):
        block = _rule_block(source, selector)
        assert _property(block, "background") == "rgba(var(--panel-rgb), var(--panel-opacity))", (
            f"{selector} must declare background: rgba(var(--panel-rgb), var(--panel-opacity))"
        )
    for selector in (".swatch-menu", ".spk-menu"):
        block = _rule_block(source, selector)
        assert _property(block, "background") == "var(--panel)", (
            f"{selector} must stay on the flat background: var(--panel)"
        )


def test_no_blur_declarations():
    """
    Blur was measured (Phase 5, see the --panel-opacity comment) to buy zero
    contrast headroom over the backdrop photo - the worst-case composite is
    exactly as tight blurred as it is sharp, because a blur radius redistributes
    a pixel's neighbours' colour without changing the extremes any single pixel
    under text can land on. The panel opacity is what protects contrast; blur
    was tried and dropped. This guards the decision, not merely today's file:
    a live `backdrop-filter` or `filter: blur(` declaration must not reappear,
    on `.backdrop` or anywhere else, even though a comment is free to keep
    talking about why it was rejected (several already do).
    """
    source = _css_source()
    # Strip /* ... */ comments before scanning, so a comment that merely
    # *mentions* backdrop-filter or blur() to explain why it was rejected
    # (several currently do, deliberately) doesn't trip this guard - only a
    # live declaration should.
    without_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    assert "backdrop-filter" not in without_comments, (
        "a live backdrop-filter declaration reappeared - blur was measured to "
        "buy zero contrast headroom (see the --panel-opacity comment) and the "
        "user does not want it back"
    )
    assert "filter: blur(" not in without_comments, (
        "a live filter: blur( declaration reappeared - see the backdrop-filter "
        "assertion above for why"
    )


def test_focus_ring_gated_behind_keyboard_flag():
    """
    Phase 7: .body and .plain-body are the two elements the user reported the
    ring lighting up on for a plain mouse click (a Chromium quirk - it matches
    :focus-visible on a contenteditable element for mouse focus too). The fix
    is transcript.js's own tracked modality flag, html[data-kbd], not
    :focus-visible alone - see the STATED EXCEPTION in this file's standing
    rules comment at the top. Every other control keeps plain :focus-visible,
    including #search's existing outline: none exemption and .speaker-name,
    which is explicitly out of scope.
    """
    source = _css_source()
    assert re.search(r"html\[data-kbd\]\s+\.body:focus\s*\{", source), (
        ".body's focus ring must be gated behind html[data-kbd] .body:focus"
    )
    assert re.search(r"html\[data-kbd\]\s+\.plain-body:focus\s*\{", source), (
        ".plain-body's focus ring must be gated behind html[data-kbd] .plain-body:focus"
    )
    # Bare :focus-visible on either element would re-admit the mouse-click bug
    # this phase exists to fix.
    assert not re.search(r"(?<![-\w])\.body:focus-visible\s*\{", source)
    assert not re.search(r"(?<![-\w])\.plain-body:focus-visible\s*\{", source)
    # #search's own exemption (out of scope for Phase 7) must survive intact.
    assert "#search:focus-visible { outline: none; }" in source


def test_tour_classes_exist_and_stack_above_the_help_panel():
    """
    The guided tour's three overlay elements (.tour-scrim, .tour-ring,
    .tour-card) are built entirely by transcript.js - there is no
    server-rendered markup to check the way there is for .help-panel - so
    this is the CSS side's only guard: the classes exist, and their z-index
    clears .help-panel's own 70 (the tour is launched FROM inside that
    panel - see .help-panel's own z-index comment for the rest of the
    stack this has to stay ordered against).
    """
    source = _css_source()
    scrim = _rule_block(source, ".tour-scrim")
    ring = _rule_block(source, ".tour-ring")
    card = _rule_block(source, ".tour-card")

    assert int(_property(scrim, "z-index")) > 70
    assert int(_property(ring, "z-index")) > int(_property(scrim, "z-index"))
    assert int(_property(card, "z-index")) > int(_property(ring, "z-index"))


def test_tour_scrim_lets_the_ring_pass_clicks_through_to_it():
    """
    Non-destructive is the hard requirement on this feature (see
    docs/transcript-manual-checks.md): the scrim, not the ring, has to be
    what actually intercepts a click on the page underneath - including a
    click squarely on the very control a step is describing (a .ts
    timestamp button, say), which is what stops the tour from being able to
    start audio, open a menu, or flip a toggle it is merely narrating. That
    only works if the ring itself is transparent to clicks, letting them
    fall through to the scrim beneath it rather than swallowing them itself
    with nothing behind that reacts.
    """
    source = _css_source()
    ring = _rule_block(source, ".tour-ring")
    assert _property(ring, "pointer-events") == "none"


def test_tour_card_reuses_the_popover_surface_not_the_translucent_panel():
    """
    Same "a floating overlay reads as MORE raised than the page it sits
    over" reasoning test_panel_token_is_actually_used above checks for
    .swatch-menu/.spk-menu - the tour's caption card is the same kind of
    surface (built by script, detached from the document's normal flow),
    so it has to stay on the flat --panel token too, not the translucent
    rgba(var(--panel-rgb), var(--panel-opacity)) .source/.outline use.
    """
    source = _css_source()
    card = _rule_block(source, ".tour-card")
    assert _property(card, "background") == "var(--panel)"


def test_high_contrast_overrides_are_all_present():
    """
    Asserts the three high-contrast overrides exist, without caring which
    block each sits in or in what order.

    The previous version of this test searched from ".tour-scrim" onward and
    required ".tour-card" to be the literally-first selector inside a
    prefers-contrast block. That pinned an accident of layout rather than a
    guarantee, and it constrained the very cleanup that was needed: the
    overrides used to be three separate blocks scattered beside whatever
    each one touched, which is how .backdrop's - the only one that removes
    an element rather than thickening a border - went missing entirely
    during the split into fragments with nothing noticing. They now live
    together in css/92-contrast.css, so this checks for the declarations
    themselves.
    """
    source = _css_source()
    blocks = re.findall(
        r"@media \(prefers-contrast: more\)\s*\{(.*?)^\}", source, re.S | re.M
    )
    assert blocks, "no prefers-contrast: more block found at all"
    combined = "\n".join(blocks)

    # The load-bearing one: a photo behind the text is the opposite of what
    # "more contrast" asks for. docs/transcript-manual-checks.md checks this
    # by eye; this is the automated half.
    assert re.search(r"\.backdrop\s*\{[^}]*display:\s*none", combined), (
        "the backdrop must be hidden under prefers-contrast: more"
    )
    for selector in (".help-sheet", ".tour-card"):
        assert re.search(re.escape(selector) + r"\s*\{[^}]*border-width", combined), (
            f"{selector} should thicken its border under prefers-contrast: more"
        )
    assert re.search(r"\.tour-ring\s*\{[^}]*outline-width", combined), (
        ".tour-ring should thicken its outline under prefers-contrast: more"
    )


def test_tour_skip_is_separated_from_back_and_next():
    """
    Skip is an escape hatch, not a peer of Back/Next - see .tour-actions'
    own comment for why an auto margin (rather than
    justify-content: space-between, which would leave a visible gap where
    Back used to sit once [hidden] removes it on step 1) is what keeps it
    visually apart from the step controls.
    """
    source = _css_source()
    block = _rule_block(source, ".tour-actions .tour-skip")
    assert _property(block, "margin-inline-end") == "auto"


def test_hover_dim_is_phase_8_value():
    """
    Phase 8: non-focused cards dim to 0.5 (from the original 0.72) while a
    section is hovered - see the rule's own comment for why, and for the
    accepted contrast trade-off that comes with dimming text toward the panel.
    """
    source = _css_source()
    block = _rule_block(source, ".source:hover .turn:not(:hover)")
    assert _property(block, "opacity") == "0.5"


def test_bubble_sizes_to_its_content_rather_than_the_column():
    """
    What makes a bubble read as a message rather than as a row.

    The first version of 52-bubble.css gave .bubble p a flex-basis of 100%,
    which forced the number, the sentence and the time onto three separate
    lines and left every bubble full-width and three rows tall - a list of
    boxes, not a conversation. It passed every test in the suite, because
    nothing here described the shape. This is that description: a bubble is
    as wide as it needs to be, and no wider than a comfortable reading
    measure.
    """
    source = _css_source()
    block = _rule_block(source, ".bubble")
    assert _property(block, "width") == "fit-content"
    max_width = _property(block, "max-width")
    assert max_width.startswith("min("), max_width
    assert "ch" in max_width, (
        "the cap needs a reading-measure component, not only a percentage - "
        f"a percentage alone runs the full column on a wide window: {max_width}"
    )
    assert "flex: 1 1 100%" not in source, (
        "a full-basis paragraph is what broke the shape the first time"
    )


def test_bubble_has_a_visible_edge_against_the_card():
    """
    --surface-hover sits a couple of percent off --panel, which is enough for
    a hover state on a full-width card and not enough for a bubble: rendered,
    the fill alone left the bubbles nearly invisible against the card behind
    them. The hairline is what carries the shape, so it is not decoration.
    """
    block = _rule_block(_css_source(), ".bubble")
    assert "var(--rule)" in _property(block, "border")


def test_bubble_dim_matches_the_cluster_dim_it_nests_inside():
    """
    Two dim rules now exist: 48-turn.css dims whole clusters the pointer is
    not on, and 52-bubble.css dims sentences inside the cluster it IS on.
    They must carry the same value. Different values would be arbitrary, and
    if the bubble rule ever escaped its .turn:hover scope the two would
    compound - 0.5 * 0.5 is 0.25, far below any readable contrast. Pinning
    them equal is cheaper than re-deriving that argument later.
    """
    source = _css_source()
    cluster = _rule_block(source, ".source:hover .turn:not(:hover)")
    bubble = _rule_block(source, ".turn:hover .bubble:not(:hover)")
    assert _property(bubble, "opacity") == _property(cluster, "opacity")
    # Scope guard: the bubble rule must stay nested under a hovered cluster,
    # which is precisely the cluster the rule above is NOT dimming.
    assert ".turn:hover .bubble:not(:hover)" in source
    assert "\n.bubble:not(:hover)" not in source, (
        "unscoped bubble dim would compound with the cluster dim"
    )
