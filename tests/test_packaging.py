"""
Guards on how this project is packaged.

These exist because packaging fails *quietly* here. The stylesheet, the
script and the backdrop images are read from disk at render time rather than
imported, so a wheel built without them installs fine, imports fine, and only
misbehaves later - at the moment a user renders a transcript, which comes out
unstyled and backdrop-less with no error anyone could trace back to a missing
package-data glob. Nothing else in the suite would notice, because every other
test runs against the source tree, where the files are simply there.

setup.py used to be the only place these declarations lived. It has been
folded into pyproject.toml; this module is what stops that consolidation from
silently regressing.
"""

import fnmatch
from pathlib import Path

import pytest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
# src-layout: package-data globs are relative to the package root setuptools is
# pointed at, so paths are compared against SRC, not the repo root.
SRC = ROOT / "src"
PACKAGE = SRC / "speech_to_text"

# Everything that ships but is never imported. Extensions, not paths: the
# point of the check below is to catch a *new* asset of a known kind landing
# in a directory whose glob does not cover it.
ASSET_SUFFIXES = {".css", ".js", ".webp", ".ico"}


pytestmark = pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")


def _config():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _package_data():
    return _config()["tool"]["setuptools"]["package-data"]


def _covered(rel_path: Path) -> bool:
    """
    Whether pyproject's package-data globs actually reach this file.

    package-data is keyed by package name with patterns relative to that
    package's own directory, so "speech_to_text.core" + "assets/*.css" means
    speech_to_text/core/assets/*.css - reconstructed here rather than assumed,
    since getting that mapping wrong is precisely the mistake being guarded
    against.
    """
    for package, patterns in _package_data().items():
        package_dir = Path(*package.split("."))
        try:
            inside = rel_path.relative_to(package_dir)
        except ValueError:
            continue
        for pattern in patterns:
            if _glob_match(inside.as_posix(), pattern):
                return True
    return False


def _glob_match(path: str, pattern: str) -> bool:
    """
    Segment-wise match, because fnmatch alone gets this wrong in the one
    direction that matters.

    fnmatch's `*` happily matches across a `/`, so fnmatch("assets/js/a.js",
    "assets/*.js") is True - while setuptools' own package-data globbing
    treats `*` as within-one-segment and does not match it. Using fnmatch
    directly therefore reports an asset as covered when a real wheel build
    would silently omit it, which is precisely the failure this module
    exists to catch, inverted into a false negative. It did exactly that
    when the stylesheet and script were split into assets/css/ and
    assets/js/: the sweep stayed green while the fragments shipped in no
    wheel at all.
    """
    parts, globs = path.split("/"), pattern.split("/")
    if len(parts) != len(globs):
        return False
    return all(fnmatch.fnmatch(part, glob) for part, glob in zip(parts, globs))


class TestPackageData:
    def test_every_shipped_asset_is_covered_by_a_glob(self):
        """
        The regression that matters: a new asset kind, or a new asset
        directory, added without a matching package-data entry.
        """
        assets = [
            p for p in PACKAGE.rglob("*") if p.is_file() and p.suffix.lower() in ASSET_SUFFIXES
        ]
        assert assets, "no assets found - the discovery glob itself is wrong"

        uncovered = sorted(
            str(p.relative_to(SRC)) for p in assets if not _covered(p.relative_to(SRC))
        )
        assert not uncovered, (
            "these files ship at render time but no package-data glob in "
            "pyproject.toml reaches them, so a wheel would omit them "
            "silently: " + ", ".join(uncovered)
        )

    def test_the_render_time_assets_are_named_explicitly(self):
        """
        A narrower belt-and-braces check on the three the renderer cannot do
        without, in case the sweep above is ever relaxed.
        """
        patterns = _package_data()["speech_to_text.core"]
        assert "assets/*.css" in patterns
        assert "assets/*.js" in patterns
        assert "assets/vistas/*.webp" in patterns


class TestEntryPointAndDiscovery:
    def test_console_script_points_at_something_real(self):
        script = _config()["project"]["scripts"]["speech-to-text"]
        module_path, _, attr = script.partition(":")

        module = SRC / Path(*module_path.split(".")).with_suffix(".py")
        assert module.exists(), f"{script} names a module that does not exist"
        assert f"def {attr}(" in module.read_text(encoding="utf-8"), (
            f"{script} names a callable that does not exist in {module_path}"
        )

    def test_tests_are_not_shipped(self):
        include = _config()["tool"]["setuptools"]["packages"]["find"]["include"]
        assert include == ["speech_to_text*"], (
            "discovery is an explicit include so that tests/ (which has its "
            "own __init__.py, as does tests/eval/) can never be swept into a "
            "wheel by a flat-layout scan"
        )


class TestSingleSourceOfTruth:
    """
    requirements*.txt duplicated pyproject's dependency lists until they
    drifted (pytest>=7.0 against pytest>=7.0.0). They are pointers now, and
    these tests are what stops someone helpfully "restoring" the lists.
    """

    @pytest.mark.parametrize(
        "name, expected",
        [("requirements.txt", "-e ."), ("requirements-dev.txt", "-e .[dev]")],
    )
    def test_requirements_files_only_point_at_pyproject(self, name, expected):
        lines = [
            line.strip()
            for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert lines == [expected], (
            f"{name} should contain only '{expected}' - dependencies belong "
            "in pyproject.toml, which is the one place that is actually read"
        )

    def test_setup_py_has_not_come_back(self):
        assert not (ROOT / "setup.py").exists(), (
            "setup.py was folded into pyproject.toml; two build "
            "configurations is how package_data drifts out of sync again"
        )
