"""The transcript's CSS and JS fragments are concatenated in filename order.

That order is correctness, not tidiness, and nothing checked it before this
file existed. core/formatting/assets.py joins every fragment in a directory by
plain `sorted()`, and __init__.py wraps the whole JS concatenation in a single
IIFE. So the fragments are bare statement bodies sharing one function scope:
00-preamble.js opens with a `return` guard that has to run first or the guard
never fires, and 99-init.js is the epilogue that has to run last or it
initialises against a page whose handlers are not defined yet.

A fragment misnamed so it sorts out of place breaks the transcript silently at
render time - the page just stops working, with no error anyone could trace
back to a filename. These tests turn that into a failure here instead.
"""

import re

import pytest

from speech_to_text.core.formatting.assets import _ASSETS

CSS = _ASSETS / "css"
JS = _ASSETS / "js"

# NN-name.ext, where NN is what decides concatenation order.
NUMBERED = re.compile(r"^(\d{2})-[a-z0-9-]+\.(css|js)$")


def _fragments(directory):
    return sorted(p for p in directory.iterdir() if p.is_file())


@pytest.mark.parametrize("directory", [CSS, JS], ids=["css", "js"])
def test_every_fragment_is_numbered(directory):
    """An unnumbered file sorts unpredictably against the numbered ones."""
    bad = [p.name for p in _fragments(directory) if not NUMBERED.match(p.name)]
    assert not bad, (
        f"these fragments in {directory.name}/ do not match NN-name.ext, so their "
        f"position in the concatenation is not pinned: {bad}"
    )


@pytest.mark.parametrize("directory", [CSS, JS], ids=["css", "js"])
def test_no_two_fragments_share_a_prefix(directory):
    """Two files with the same prefix order by their name, which nobody chose."""
    seen = {}
    for p in _fragments(directory):
        prefix = NUMBERED.match(p.name).group(1)
        seen.setdefault(prefix, []).append(p.name)
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not clashes, f"duplicate prefixes in {directory.name}/: {clashes}"


def test_the_js_preamble_sorts_first():
    """00-preamble.js opens the IIFE and holds the `return` guard."""
    assert _fragments(JS)[0].name == "00-preamble.js"


def test_the_js_init_epilogue_sorts_last():
    """99-init.js runs against handlers every earlier fragment defined."""
    assert _fragments(JS)[-1].name == "99-init.js"


def test_the_css_token_sheet_sorts_first():
    """Custom properties have to be declared before any rule reads them."""
    assert _fragments(CSS)[0].name == "00-tokens.css"
