"""Reading the inlined stylesheet, script and backdrop photos off disk.

Tests patch _ASSETS and _VISTAS_DIR on this module directly; patching a
re-export on the package would not reach the globals these functions read.
"""

import base64
import random
from functools import cache
from pathlib import Path

# Inlined, never linked: the transcript must work fully offline.
_ASSETS = Path(__file__).parent.parent / "assets"


@cache
def _asset(name: str) -> str:
    """Read an asset kept as a real .css/.js file (lintable); cached because a
    batch re-renders once per file.
    """
    return (_ASSETS / name).read_text(encoding="utf-8")


@cache
def _asset_dir(name: str) -> str:
    """Concatenate an assets subdirectory's fragments in filename order.

    The two-digit prefix is the order, as a file browser shows it. For JS it
    is correctness: the fragments share one IIFE scope, so 00-preamble.js (its
    `return` guard) must come first and 99-init.js last.
    """
    directory = _ASSETS / name
    fragments = sorted(p for p in directory.iterdir() if p.is_file())
    return "\n".join(fragment.read_text(encoding="utf-8") for fragment in fragments)


_VISTAS_DIR = _ASSETS / "vistas"


@cache
def _vista_names() -> tuple:
    """The landscape backdrop photos, one per photo, sorted.

    Portrait crops (vista-NN-portrait.webp) sit beside them and are excluded,
    or they would count as extra photos and could be picked as the main
    backdrop. Empty when the directory is missing: no backdrop, not an error.
    """
    if not _VISTAS_DIR.is_dir():
        return ()
    return tuple(
        sorted(p.name for p in _VISTAS_DIR.glob("*.webp") if not p.stem.endswith("-portrait"))
    )


def _vista_portrait_name(landscape_name: str) -> str | None:
    """The portrait crop for a landscape backdrop (vista-07.webp ->
    vista-07-portrait.webp), or None when there is none - render_html() then
    skips the portrait swap.
    """
    candidate = f"{Path(landscape_name).stem}-portrait.webp"
    if (_VISTAS_DIR / candidate).is_file():
        return candidate
    return None


@cache
def _asset_bytes(name: str) -> bytes:
    """Binary counterpart to _asset(), for the WebP photos."""
    return (_ASSETS / name).read_bytes()


@cache
def _data_uri(name: str) -> str:
    """One vistas/ file as a data:image/webp URI. Cached on the name alone,
    which is the whole input (shipped package data), since a batch re-renders
    the document after every file.
    """
    encoded = base64.b64encode(_asset_bytes(f"vistas/{name}")).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _vista_data_uris(vista: str | None) -> tuple | None:
    """(landscape_uri, portrait_uri or None) for a backdrop, or None when no
    photos exist - a transcript without a backdrop still works.

    vista=None picks at random; a filename pins it (tests, and the worker,
    which keeps one photo across a batch's re-renders).
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
