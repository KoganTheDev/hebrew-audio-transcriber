"""
Validates every i18n key speech_to_text/core/ emits across the process
boundary (see core/worker.py's module docstring: progress_queue and
result_queue carry (kind, key, params, ...) tuples, never rendered text,
because the worker process cannot import gui.i18n to render them itself).

Nothing on either side of that boundary previously checked the key actually
exists in gui.i18n.STRINGS, or that the params dict a call site builds
actually matches the {placeholder} names the English string declares. A
typo in a key reaches the user as the raw key text (t()'s fallback for an
unknown key), and a missing or extra param either leaves a "{name}" literal
in the displayed string or raises KeyError inside t()'s own
`text.format(**fmt)` - both bugs that only show up mid-transcription, in
whichever language the reader has selected, which is exactly the kind of
thing worth catching at collection time instead.

Found via a structural AST scan for the shape every emission site actually
takes: a tuple literal containing a string constant immediately followed by
a dict literal - (key, params) or (kind, key, params[, percent]) alike. This
catches every emission site in core/ as of this writing (worker.py's direct
queue.put(...) calls, transcriber.py's progress_callback(...) calls, and the
_RETRY_LOG_PATTERNS lambdas in worker.py) without hardcoding which function
or queue name does the emitting - a new emission site anywhere in core/,
however it's spelled, is picked up automatically the next time this test
walks the package.
"""

import ast
import importlib
import inspect
import pkgutil
import re

import speech_to_text.core as core_package
from speech_to_text.gui.i18n import STRINGS

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _iter_core_modules():
    modules = [core_package]
    prefix = core_package.__name__ + "."
    for info in pkgutil.walk_packages(core_package.__path__, prefix):
        modules.append(importlib.import_module(info.name))
    return modules


def _dict_literal_keys(node: ast.Dict):
    """
    The dict's own string-constant keys, or None if any key is not a plain
    string literal (a computed key means this call site can't be checked
    statically - skipped rather than guessed at).
    """
    keys = []
    for k in node.keys:
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            return None
        keys.append(k.value)
    return set(keys)


def _find_key_param_pairs(tree):
    """
    Every (key, params-dict) pair found anywhere in the module: a tuple
    literal in which some element is a string constant and the very next
    element is a dict literal. Matches both the 2-tuple message shape
    ("w_foo", {...}) and the 3/4-tuple queue-payload shape
    ("progress", "w_foo", {...}, percent) - the kind label ("progress",
    "status", "error") is itself a string constant but is never
    dict-adjacent, so it is never mistaken for a key.
    """
    pairs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple):
            continue
        elts = node.elts
        for i in range(len(elts) - 1):
            key_node, dict_node = elts[i], elts[i + 1]
            if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                continue
            if not isinstance(dict_node, ast.Dict):
                continue
            pairs.append((key_node.value, dict_node, node.lineno))
    return pairs


# Kind labels themselves are string constants that happen to sit next to a
# key in these tuples, never next to a dict - excluded so a coincidental
# future ("progress", {}) shape (kind directly followed by an empty params
# dict, skipping the key) can't be misread as a key named "progress".
_KIND_LABELS = {"progress", "status", "error", "finished", "ok"}


def _emitted_key_param_pairs():
    """
    (module_name, key, param_names, lineno) for every emission site found
    across core/, skipping kind labels and any dict with a non-literal key.
    """
    found = []
    for module in _iter_core_modules():
        tree = ast.parse(inspect.getsource(module))
        for key, dict_node, lineno in _find_key_param_pairs(tree):
            if key in _KIND_LABELS:
                continue
            param_names = _dict_literal_keys(dict_node)
            if param_names is None:
                continue
            found.append((module.__name__, key, param_names, lineno))
    return found


def test_scan_finds_the_known_emission_sites():
    """
    Floor, not a full inventory: guards against the AST scan silently
    finding nothing (a refactor of _find_key_param_pairs that stopped
    matching anything would otherwise leave every assertion below
    vacuously true).
    """
    pairs = _emitted_key_param_pairs()
    assert len(pairs) >= 15, (
        f"only found {len(pairs)} emitted (key, params) pairs in core/ - "
        "the AST scan is probably broken, not the codebase shrinking"
    )


def test_every_emitted_key_exists_in_strings():
    missing = [
        f"{module}:{lineno} emits unknown key {key!r}"
        for module, key, _params, lineno in _emitted_key_param_pairs()
        if key not in STRINGS
    ]
    assert not missing, "\n".join(missing)


def test_every_emitted_params_dict_matches_the_english_placeholders():
    mismatches = []
    for module, key, param_names, lineno in _emitted_key_param_pairs():
        entry = STRINGS.get(key)
        if entry is None:
            continue  # already reported by test_every_emitted_key_exists_in_strings
        placeholders = set(_PLACEHOLDER.findall(entry["en"]))
        if param_names != placeholders:
            missing = placeholders - param_names
            extra = param_names - placeholders
            detail = []
            if missing:
                detail.append(f"missing {sorted(missing)}")
            if extra:
                detail.append(f"extra {sorted(extra)}")
            mismatches.append(f"{module}:{lineno} key {key!r}: {', '.join(detail)}")
    assert not mismatches, "\n".join(mismatches)
