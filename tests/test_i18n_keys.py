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
import pathlib
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


# --- Latin quantities inside Hebrew sentences -------------------------------

_LRI = "\u2066"
_PDI = "\u2069"

# Hebrew strings that embed a Latin number+unit pair, and the substring in
# each that has to be fenced. Keyed by the i18n key so a failure names the
# string rather than an index.
_ISOLATED_HEBREW_QUANTITIES = {
    "file_info": "{size} MB",
    "model_ram_tooltip": "{ram}",
    "model_download_pending": "{size}",
    "model_download_tooltip": "{size}",
    "w_downloading_diarization": "36 MB",
}


def test_latin_quantities_in_hebrew_strings_are_bidi_isolated():
    """
    "145 MB" inside a Hebrew sentence has to be fenced in LRI/PDI or it
    renders as "MB 145".

    The Unicode bidi algorithm has European numbers act as right-to-left for
    the purpose of resolving neighbouring neutrals (rule N1), so the space
    between "145" and "MB" matches neither side, falls back to the RTL
    paragraph direction, and splits one left-to-right run into two reversed
    ones. This shipped in the file list, on every model card's download note
    and in the diarization download message. A non-breaking space does not
    help (same bidi class); an LRE/PDF embedding does, but leaks into
    adjacent Latin text, so isolates are what these strings use.
    """
    for key, quantity in _ISOLATED_HEBREW_QUANTITIES.items():
        hebrew = STRINGS[key]["he"]
        assert _LRI + quantity + _PDI in hebrew, (
            f"{key}: {quantity!r} is not wrapped in LRI/PDI - it will render reversed "
            f"in the Hebrew UI. Got: {hebrew!r}"
        )


def test_filenames_in_hebrew_strings_are_bidi_isolated():
    """
    Same rule, one step further out: a Latin filename followed by " | " and
    a number gets split by the very same neutral-resolution rule, which put
    the minute count to the RIGHT of the filename - i.e. read first - in
    every row of the Hebrew file list.
    """
    for key, placeholder in (("file_info", "{filename}"), ("w_file_progress", "{name}")):
        hebrew = STRINGS[key]["he"]
        assert _LRI + placeholder + _PDI in hebrew, (
            f"{key}: {placeholder} is not wrapped in LRI/PDI. Got: {hebrew!r}"
        )


# --- Dead keys, and lookups of keys that don't exist ------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_I18N_PATH = _SRC / "speech_to_text" / "gui" / "i18n.py"

# The prefix document_strings() strips. Spelled out here rather than imported
# from i18n so this test states the convention it is checking against, and a
# rename of the private constant shows up as a failure to explain rather than
# as a silently different check.
_DOC_PREFIX = "doc_"

# Both halves of the shipped app get searched: the transcript page's own
# behaviour lives in core/assets/js/*.js, so a Python-only scan would call
# every key the page script uses - most of the doc_ family - unreferenced.
_SOURCE_SUFFIXES = (".py", ".js", ".mjs")


def _source_haystack() -> str:
    """
    Every shipped source file except i18n.py itself, concatenated.

    i18n.py is excluded because it is where the keys are DEFINED - leaving it
    in would make every key trivially "referenced" by its own table entry.
    Its own uses of t() are recovered separately by _self_referenced_keys().
    """
    texts = []
    for path in _SRC.rglob("*"):
        if path.suffix not in _SOURCE_SUFFIXES:
            continue
        if path.resolve() == _I18N_PATH.resolve():
            continue
        texts.append(path.read_text(encoding="utf-8"))
    return "\n".join(texts)


def _self_referenced_keys() -> set:
    """
    Keys i18n.py looks up itself, via a t("literal") call in its own body.

    The dur_* family lives and dies here: format_duration() is its only
    caller, so a scan that excluded i18n.py wholesale would report all five
    as dead. Rather than hardcoding a dur_* exemption - which would also
    excuse a genuinely dead dur_ key, and would say nothing about the next
    family that ends up in the same position - the exemption is derived from
    the call sites: an AST walk for t() calls with a string-constant first
    argument. A key is live if something actually calls t() on it, wherever
    that call happens to live.
    """
    tree = ast.parse(_I18N_PATH.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "t" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.add(first.value)
    return keys


def _search_name_for(key: str) -> str:
    """
    The name a key is actually referenced BY elsewhere in the tree.

    document_strings() hands the transcript renderer and the page script the
    doc_ group with the prefix stripped, so doc_help_search_title is spelled
    "help_search_title" at every one of its call sites and a literal search
    for the full key finds nothing. Every other key is referenced verbatim.
    """
    return key[len(_DOC_PREFIX) :] if key.startswith(_DOC_PREFIX) else key


def test_no_string_table_entry_is_referenced_from_nowhere_in_the_shipped_source():
    """
    A key nobody looks up is dead weight that still has to be translated,
    re-read and kept consistent by whoever touches the table next - and the
    doc_ prefix convention makes dead keys unusually easy to accumulate,
    because the obvious check (grep for the full key) reports almost the
    whole doc_ family as unused and is therefore quickly learned to be
    useless. Searching by the stripped name instead makes the answer
    trustworthy, which is the only way a check like this survives.
    """
    haystack = _source_haystack()
    self_referenced = _self_referenced_keys()
    unused = sorted(
        key
        for key in STRINGS
        if _search_name_for(key) not in haystack and key not in self_referenced
    )
    assert not unused, (
        "string table keys nothing in src/ references: "
        + ", ".join(unused)
        + " - delete them, or wire up the call site they were added for"
    )


def _gui_t_call_keys():
    """
    (module_name, key, lineno) for every t("literal", ...) call in gui/.

    Only string-constant keys: a t(key) on a variable is resolved at runtime
    and cannot be checked statically.
    """
    import speech_to_text.gui as gui_package

    modules = [gui_package]
    prefix = gui_package.__name__ + "."
    for info in pkgutil.walk_packages(gui_package.__path__, prefix):
        modules.append(importlib.import_module(info.name))

    found = []
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "t" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((module.__name__, first.value, node.lineno))
    return found


def test_scan_finds_the_known_gui_translation_call_sites():
    """
    Same floor as test_scan_finds_the_known_emission_sites, for the same
    reason: a walk that quietly stopped matching t() calls would leave the
    assertion below vacuously true.
    """
    calls = _gui_t_call_keys()
    assert len(calls) >= 50, (
        f'only found {len(calls)} t("...") call sites in gui/ - the AST walk is '
        "probably broken, not the GUI shrinking"
    )


def test_every_gui_translation_call_site_names_a_key_that_exists():
    """
    The opposite error to a dead key, and a louder one: t() falls back to
    returning the key itself for an unknown key, so a typo'd lookup ships a
    literal "nav_cancle" into the interface instead of raising anywhere.
    """
    unknown = [
        f"{module}:{lineno} looks up unknown key {key!r}"
        for module, key, lineno in _gui_t_call_keys()
        if key not in STRINGS
    ]
    assert not unknown, "\n".join(unknown)
