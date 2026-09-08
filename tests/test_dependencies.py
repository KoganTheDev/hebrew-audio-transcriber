"""
Tests for dependency management.
"""

from speech_to_text.core.dependencies import ensure_dependencies


class TestDependencies:
    """Test dependency management."""

    def test_ensure_dependencies_all_installed(self):
        """Test when all dependencies are already installed."""
        packages = {
            "pytest": "pytest",
            "setuptools": "setuptools",
        }

        result = ensure_dependencies(packages)
        assert result is True

    def test_a_missing_package_is_reported_rather_than_installed(self):
        """
        The check must never install anything, and must say False.

        It used to pip install into sys.executable with the output captured,
        which on a launcher-picked system Python meant minutes of invisible
        work mutating the user's GLOBAL interpreter, followed by a crash
        anyway. Installing belongs to the installer.
        """
        packages = {"definitely_not_installed_xyz": "ghost-package"}
        assert ensure_dependencies(packages) is False

    def test_the_check_does_not_import_the_packages_it_checks(self):
        """
        Availability is decided with find_spec, never by importing.

        main.py imports faster_whisper BEFORE PyQt5 deliberately, because the
        two ship conflicting MSVCP140.dll copies on Windows and whichever
        loads first wins. A check that imported its way down the dict would
        hand that decision to dict insertion order and silently undo the fix.
        """
        import sys

        for name in ("PyQt5", "faster_whisper"):
            sys.modules.pop(name, None)

        assert ensure_dependencies({"PyQt5": "PyQt5", "faster_whisper": "faster-whisper"}) is True
        assert "PyQt5" not in sys.modules, "the check imported PyQt5"
        assert "faster_whisper" not in sys.modules, "the check imported faster_whisper"

    def test_ensure_dependencies_returns_true_for_installed(self):
        """Test that True is returned for installed dependencies."""
        packages = {"os": "os"}  # built-in module
        result = ensure_dependencies(packages)
        assert result is True
