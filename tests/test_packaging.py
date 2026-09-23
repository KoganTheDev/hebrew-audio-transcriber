"""
Guards on how this project is laid out and installed.

These exist because this part fails *quietly*. The stylesheet, script and
backdrop images are read from disk at render time rather than imported, so a
tree missing them starts and imports fine, then produces an unstyled
transcript with no error anyone could trace back to a moved directory.

The project installs no modules of its own (see pyproject's
[tool.setuptools]), so the assets are found by walking from __file__ and what
needs guarding is whether those directories are still where the code reaches.
"""

from pathlib import Path

import pytest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SRC = ROOT / "src"

# Extensions, not paths: the point is to catch a NEW asset of a known kind
# landing somewhere nothing reaches.
ASSET_SUFFIXES = {".css", ".js", ".webp", ".ico"}

# Stated independently of the code that resolves them, so moving one without
# the other fails a test rather than a user's transcript.
ASSET_DIRS = (
    SRC / "core" / "assets",
    SRC / "assets",
)

pytestmark = pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")


def _config():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


class TestAssetsAreWhereTheCodeLooks:
    def test_the_asset_directories_exist(self):
        """An asset directory moved without the __file__ walk that finds it."""
        for directory in ASSET_DIRS:
            assert directory.is_dir(), (
                f"{directory.relative_to(ROOT)} is read at render time by a "
                "__file__-relative walk - if it moved, the walk in "
                "core/formatting/assets.py has to move with it"
            )

    def test_assets_module_resolves_to_the_real_directory(self):
        """Against the module's own resolution, not a repeat of the literal."""
        from core.formatting import assets

        assert Path(assets._ASSETS).resolve() == (SRC / "core" / "assets").resolve()

    def test_every_shipped_asset_sits_under_a_directory_the_code_reaches(self):
        """A new asset added somewhere the render-time walks never look."""
        found = [p for p in SRC.rglob("*") if p.is_file() and p.suffix.lower() in ASSET_SUFFIXES]
        assert found, "no assets found - the discovery glob itself is wrong"

        stranded = sorted(
            str(p.relative_to(SRC)) for p in found if not any(d in p.parents for d in ASSET_DIRS)
        )
        assert not stranded, (
            "these files are read at render time but sit outside every "
            "directory the code walks to, so they would silently never be "
            "found: " + ", ".join(stranded)
        )

    def test_the_render_time_assets_are_present(self):
        """The three kinds the renderer cannot do without, in case the sweep above is relaxed."""
        core_assets = SRC / "core" / "assets"
        assert list(core_assets.glob("css/*.css")), "no stylesheet fragments"
        assert list(core_assets.glob("js/*.js")), "no script fragments"
        assert list(core_assets.glob("vistas/*.webp")), "no vista backdrops"


class TestNothingIsPublished:
    def test_no_top_level_packages_are_declared(self):
        """`import config` from any other project would otherwise resolve to this app's."""
        setuptools_config = _config()["tool"]["setuptools"]
        assert setuptools_config["packages"] == [], (
            "this project installs its dependencies and no modules of its "
            "own; declaring packages here would publish generic top-level "
            "names into site-packages"
        )

    def test_no_console_script_promises_an_importable_entry_point(self):
        """A console script imports an installed module; this project installs none."""
        assert "scripts" not in _config()["project"], (
            "a console script needs an installed module to import; this "
            "project installs none - the launchers are the way in"
        )

    def test_the_entry_point_module_exists(self):
        """What the launchers run - renaming it without updating them fails here."""
        assert (SRC / "app.py").is_file()


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
            "configurations is how the layout drifts out of sync again"
        )
