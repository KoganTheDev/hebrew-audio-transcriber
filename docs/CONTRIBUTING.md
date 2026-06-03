# Contributing Guide

## Welcome Contributors! 👋

This document provides guidelines for contributing to the Speech-to-Text Transcriber project.

## Code of Conduct

- Be respectful and inclusive
- Ask questions when unsure
- Help others learn and grow
- Focus on the code, not the person

## Getting Started

### 1. Set Up Development Environment

```bash
# Clone the repository
git clone <repository-url>
cd speech-to-text-transcriber

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Unix/macOS

# Install in development mode with all tools
pip install -e .
pip install -r requirements-dev.txt
```

### 2. Create Feature Branch

```bash
# Create branch from main/develop
git checkout -b feature/your-feature-name

# Branch naming conventions:
# - feature/add-new-language
# - bugfix/fix-segment-spacing
# - docs/update-readme
# - test/add-integration-tests
```

## Development Workflow

### 1. Make Your Changes

- Keep changes focused and minimal
- Follow PEP 8 style guide
- Add docstrings to functions
- Add type hints where possible

### 2. Write Tests

```bash
# Add tests in tests/ directory
# Test file naming: test_<module>.py
# Test function naming: test_<feature>()

# Example:
# tests/test_transcriber.py::test_transcribe_adds_spaces_between_segments()
```

### 3. Run Quality Checks

```bash
# Format code
black speech_to_text/

# Sort imports
isort speech_to_text/

# Lint code
flake8 speech_to_text/

# Type checking
mypy speech_to_text/

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=speech_to_text --cov-report=html
```

### 4. Commit Changes

```bash
# Use descriptive commit messages
git commit -m "feature: add language selection dropdown"

# Commit message format:
# <type>: <description>
# 
# <optional longer description>
#
# Types: feature, bugfix, docs, test, refactor, perf
```

### 5. Submit Pull Request

- Push to your fork/branch
- Create PR with clear description
- Link related issues
- Wait for review and CI checks
- Address feedback
- Squash commits if requested

## Code Style Guide

### Python Style

```python
# Good: Clear variable names
hardware_info = detector.get_hardware_info()

# Bad: Unclear abbreviations
hw_info = detector.get_hw_info()

# Good: Type hints
def estimate_time(duration_minutes: float, model: str, device: str) -> dict:
    pass

# Good: Docstrings
def transcribe(self, audio_file: str) -> str:
    """
    Transcribe audio file to text.
    
    Args:
        audio_file: Path to audio file
        
    Returns:
        Transcribed text
        
    Raises:
        FileNotFoundError: If audio file not found
    """
```

### Module Structure

```python
"""Module docstring explaining purpose."""

import standard_library
import third_party
from . import local_imports

# Constants
DEFAULT_VALUE = "value"

# Classes
class MyClass:
    """Class docstring."""
    pass

# Functions
def my_function():
    """Function docstring."""
    pass

# Main execution
if __name__ == "__main__":
    pass
```

## Testing Requirements

### Test Coverage

- Minimum 80% coverage for new code
- 100% for critical paths (time estimation, transcription)
- Mock external dependencies (faster-whisper, PyQt5)

### Test Structure

```python
import pytest
from unittest.mock import patch, MagicMock

class TestFeature:
    """Test feature functionality."""
    
    def test_happy_path(self):
        """Test normal operation."""
        pass
    
    def test_edge_case(self):
        """Test boundary condition."""
        pass
    
    def test_error_handling(self):
        """Test error scenario."""
        pass
```

## Documentation Standards

### Docstrings

Use Google-style docstrings:

```python
def function(arg1: str, arg2: int) -> bool:
    """Brief description.
    
    Longer description if needed, explaining the function's
    purpose and behavior in more detail.
    
    Args:
        arg1: Description of arg1
        arg2: Description of arg2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When value is invalid
        
    Example:
        >>> result = function("test", 42)
        >>> result
        True
    """
```

### README Updates

Update README.md when adding:
- New features
- New modules
- New dependencies
- Breaking changes

## Common Contribution Areas

### 1. Bug Fixes
- Identify issue from issues list
- Write test that reproduces bug
- Fix bug
- Verify test passes
- Submit PR

### 2. New Features
- Discuss in issues first
- Design clear API
- Implement feature
- Add comprehensive tests
- Update documentation

### 3. Tests
- Increase coverage
- Add edge case tests
- Add integration tests
- Test error scenarios

### 4. Documentation
- Improve existing docs
- Add usage examples
- Add architecture diagrams
- Fix typos

### 5. Performance
- Profile code
- Identify bottlenecks
- Optimize with benchmarks
- Submit PR with results

## Review Process

### What Reviewers Look For

- Code quality and style
- Test coverage
- Documentation
- Performance impact
- Security considerations

### Feedback Handling

1. Thank reviewer for feedback
2. Discuss if unclear
3. Make requested changes
4. Request re-review
5. Iterate until approved

## Release Process

Maintainers only:

```bash
# Update version in config.py and setup.py
# Update CHANGELOG.md
# Create git tag: v2.0.0
# Build: python setup.py sdist bdist_wheel
# Upload: twine upload dist/*
```

## Reporting Issues

Include in issue report:

- Clear title
- Detailed description
- Steps to reproduce
- Expected behavior
- Actual behavior
- Python version
- Platform (Windows/Linux/macOS)
- Relevant code/error messages

## Questions?

- Check [Architecture Guide](ARCHITECTURE.md)
- Review [existing issues](../../issues)
- Look at test examples in `tests/`
- Read docstrings in source code

---

**Thank you for contributing!** 🙏
