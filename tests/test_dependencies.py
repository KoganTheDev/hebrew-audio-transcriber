"""
Tests for dependency management.
"""

import pytest
from unittest.mock import MagicMock, patch, call
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
    
    @patch('builtins.__import__')
    def test_ensure_dependencies_missing(self, mock_import):
        """Test when dependencies are missing."""
        def import_side_effect(name, *args, **kwargs):
            if name in ["pytest", "setuptools"]:
                raise ImportError(f"No module named '{name}'")
            return MagicMock()
        
        mock_import.side_effect = import_side_effect
        
        with patch('speech_to_text.core.dependencies.subprocess.run') as mock_subprocess:
            packages = {"pytest": "pytest", "setuptools": "setuptools"}
            result = ensure_dependencies(packages)
            
            # Should attempt to install missing packages
            assert mock_subprocess.call_count == 2
    
    def test_ensure_dependencies_returns_true_for_installed(self):
        """Test that True is returned for installed dependencies."""
        packages = {"os": "os"}  # built-in module
        result = ensure_dependencies(packages)
        assert result is True
