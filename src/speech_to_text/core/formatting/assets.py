"""Reading the inlined stylesheet, script and backdrop photos off disk.

_ASSETS and _VISTAS_DIR are deliberately read by the cached functions below
through THIS module's own globals, not through a copy re-exported elsewhere:
tests monkeypatch speech_to_text.core.formatting.assets._ASSETS (and
_VISTAS_DIR) directly, because patching a name re-exported on the package's
__init__ would only rebind that alias - it would not touch the global these
functions actually close over, and the patch would silently do nothing. See
tests/test_formatting.py's TestVistaBackdrop for the tests this matters to.
"""

import base64
import random
from functools import cache
from pathlib import Path
from typing import Optional

# Inlined rather than linked because the app's premise is offline operation:
# nothing here ever references an external URL, font or script. The only src
# the document carries is a relative path to the audio sitting beside it.
_ASSETS = Path(__file__).parent.parent / "assets"


@cache
def _asset(name: str) -> str:
    """Read an inlined asset.

    Kept as real .css/.js files rather than Python string literals so they
    stay lintable and syntax-highlighted; cached because a batch render would
    otherwise re-read them once per document for no reason.
    """
    return (_ASSETS / name).read_text(encoding="utf-8")


@cache
def _asset_dir(name: str) -> str:
    """Read every fragment in an assets subdirectory and concatenate them, in
    sorted filename order.

    The two-digit prefix on each fragment's filename IS the ordering, on
    purpose, rather than a separate manifest file that could name fragments
    in one order while they actually concatenate in another: sorting the
    directory listing is exactly what a human editor sees in a file browser
    too. On the JS side that order is correctness, not tidiness - the
    fragments are bare statement bodies sharing one IIFE scope, so
    00-preamble.js must sort first (it holds a `return` guard) and 99-init.js
    must sort last. Plain CSS concatenation carries no such constraint.

    Cached for the same reason _asset() is: a batch render would otherwise
    re-read and re-join the same fragments once per document.
    """
    directory = _ASSETS / name
    fragments = sorted(p for p in directory.iterdir() if p.is_file())
    return "\n".join(fragment.read_text(encoding="utf-8") for fragment in fragments)


_VISTAS_DIR = _ASSETS / "vistas"


@cache
def _vista_names() -> tuple:
    """Available LANDSCAPE backdrop photos, sorted so vista-01.webp always sorts
    first.

    Excludes *-portrait.webp: tools/build_vistas.py writes a portrait art-
    direction crop of every photo (vista-NN-portrait.webp) next to its
    landscape original (vista-NN.webp) in the same directory, for the
    @media (max-aspect-ratio) swap in render_html(). Without this filter the
    glob below would treat both crops of the same photo as two independent
    photos, so random.choice() in _vista_data_uris() could pick a bare
    "-portrait" file as the MAIN backdrop - and worse, doubling the pool
    biases selection toward whichever photos happen to have shipped a
    portrait crop. The contract is one entry per photo, always the landscape
    one, with the portrait crop reached separately by _vista_portrait_name().

    An empty tuple - whether because the directory is missing (an installed
    copy that lost its package data) or simply has nothing in it - is not an
    error here: render_html() reads it as "no backdrop".
    """
    if not _VISTAS_DIR.is_dir():
        return ()
    return tuple(
        sorted(p.name for p in _VISTAS_DIR.glob("*.webp") if not p.stem.endswith("-portrait"))
    )


def _vista_portrait_name(landscape_name: str) -> Optional[str]:
    """The portrait art-direction crop for a chosen landscape backdrop, e.g.
    "vista-07.webp" -> "vista-07-portrait.webp", or None if that photo has no
    portrait crop on disk.

    A missing portrait file is not an error: build_vistas.py's byte budget
    can in principle skip writing a variant, and an installed copy of the
    package may carry landscape crops only. render_html() reads None as "no
    portrait swap for this document", the same "missing asset degrades
    gracefully" contract _vista_data_uris() has for a missing backdrop.
    """
    candidate = f"{Path(landscape_name).stem}-portrait.webp"
    if (_VISTAS_DIR / candidate).is_file():
        return candidate
    return None


@cache
def _asset_bytes(name: str) -> bytes:
    """Binary counterpart to _asset(): the vista photos are WebP, not text, so
    they cannot go through _asset()'s read_text/utf-8 path. Cached for the
    same reason.
    """
    return (_ASSETS / name).read_bytes()


def _data_uri(name: str) -> str:
    """base64-encode one file under vistas/ as a data:image/webp;... URI."""
    encoded = base64.b64encode(_asset_bytes(f"vistas/{name}")).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _vista_data_uris(vista: Optional[str]) -> Optional[tuple]:
    """Choose a backdrop and return (landscape_uri, portrait_uri_or_None).

    vista=None (the default) picks uniformly at random from whatever exists.
    A caller passing a specific filename - the "vista" parameter on
    render_html() - gets exactly that one back instead, which is how tests
    (and worker.py's per-run pin, so the photo does not change mid-batch on
    every checkpoint rewrite) get a deterministic document. Returns None,
    never raises, when there is nothing to embed: a missing or empty vistas/
    directory must still produce a working transcript, just without a
    backdrop.

    The second element is None, not a duplicate of the landscape URI, when
    the chosen photo has no portrait crop on disk: render_html() then emits
    only the landscape rule and no @media swap.
    """
    names = _vista_names()
    if not names:
        return None

    chosen = vista if vista is not None else random.choice(names)
    if chosen not in names:
        raise ValueError(f"unknown vista {chosen!r}; available: {', '.join(names)}")

    portrait_name = _vista_portrait_name(chosen)
    portrait_uri = _data_uri(portrait_name) if portrait_name else None
    return _data_uri(chosen), portrait_uri
