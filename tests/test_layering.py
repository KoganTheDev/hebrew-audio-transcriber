"""
Layering guard: speech_to_text/core/ runs in the worker process (see
core/__init__.py's module docstring for the MSVCP140.dll conflict that makes
this a hard rule, not a style preference) and must never import PyQt5 or
speech_to_text.gui.i18n - either one would pull Qt, or a module that itself
pulls Qt, into a process that must stay Qt-free.

This used to be checked only for speech_to_text.core.formatting (the package
that grew a help panel and a guided tour with plenty of user-facing text to
be tempted to translate directly), while the same rule was stated in prose,
separately, in roughly eight other core/ modules' own docstrings. That left
every module outside formatting/ with no actual guard - only a sentence
someone could delete without anything failing - and the docstrings themselves
drifting out of sync with each other's wording. This module is the one place
the rule is both stated and enforced, for every module under core/ at any
depth, not only formatting/.

Checked via the AST's actual import nodes, not a substring search on the
source text - several of these modules legitimately *mention* "PyQt5" or
"gui.i18n" in prose (explaining why they have no access to it), which a plain
"not in source" check would misfire on.
"""

import ast
import importlib
import inspect
import pkgutil

import speech_to_text.core as core_package


def _iter_core_modules():
    """
    Every module object under speech_to_text.core, at any depth - the
    package itself first, then each submodule/subpackage found by walking
    the package tree recursively (pkgutil.walk_packages, not iter_modules,
    which only descends one level and would silently stop covering
    formatting/'s own submodules the moment this walk needs to go two
    levels deep again).
    """
    modules = [core_package]
    prefix = core_package.__name__ + "."
    for info in pkgutil.walk_packages(core_package.__path__, prefix):
        modules.append(importlib.import_module(info.name))
    return modules


def _imported_names(module) -> set:
    """
    Every dotted path this module's import statements could plausibly bind a
    name from - both `import a.b.c` and `from a.b import c` forms, the
    latter contributing both the bare module ("a.b", so `from
    speech_to_text.gui import i18n` doesn't need special-casing beyond what
    the caller's own name matching already does) and the fully-qualified
    "a.b.c" (so `from speech_to_text.gui import i18n` is caught even though
    "i18n" alone, as an alias, carries no dots for the caller's
    name.endswith("gui.i18n") check to match against).
    """
    tree = ast.parse(inspect.getsource(module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def test_no_core_module_imports_pyqt5_or_gui_i18n():
    modules = _iter_core_modules()
    # A change to _iter_core_modules() that quietly stopped walking (an
    # empty or near-empty list) would make every assertion below vacuously
    # pass. This floor - comfortably below the current module count, so it
    # does not need bumping every time a file is added - is what turns a
    # broken walk into a loud failure instead of a silent gap in coverage.
    assert len(modules) >= 15, (
        f"only found {len(modules)} modules under core/ - the walk is "
        "probably broken, not the codebase shrinking"
    )

    violations = []
    for module in modules:
        imported = _imported_names(module)
        if any(name == "PyQt5" or name.startswith("PyQt5.") for name in imported):
            violations.append(f"{module.__name__} imports PyQt5")
        if any(
            name.endswith("gui.i18n") or ".gui.i18n" in name or name == "i18n"
            for name in imported
        ):
            violations.append(f"{module.__name__} imports gui.i18n")

    assert not violations, "\n".join(violations)
