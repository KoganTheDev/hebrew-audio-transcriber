"""
Pytest configuration shared by the whole suite.

The two environment guards below run when pytest loads this file - before any
test module is imported - because both act at import time of the code they
guard: Qt reads its platform plugin when PyQt5 is first imported, and app.py
decides whether to re-launch itself the moment it is imported.
"""

import os

import pytest

# No window ever opens during a run, locally or in CI (where there is no
# display at all). setdefault: a developer who wants to watch a GUI test can
# still export QT_QPA_PLATFORM=windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# app.py re-launches itself on the project's .venv when imported on any other
# interpreter (see _reexec_into_project_venv), and waits for that child to
# exit. Under pytest that child is the whole app: `pytest` run from a global
# Python hung in collection, on test_main.py's `import app`, until the timeout.
# The marker is the guard app.py already has against re-launching twice; the
# tests that exercise the re-launch itself clear it with monkeypatch.
os.environ.setdefault("SPEECH_TO_TEXT_REEXEC", "1")


@pytest.fixture(autouse=True)
def never_download_model_weights(monkeypatch):
    """No unit test may fetch model weights over the network.

    Transcriber.load_model() calls _fetch_weights() to run the download itself
    rather than leaving it to WhisperModel, so that it can report progress -
    see that method's docstring. Tests mock WhisperModel, which used to be
    enough to keep the suite offline; it no longer is, and without this fixture
    a single load_model() in a unit test pulls 1.6 GB and takes the suite from
    50 seconds to three and a half minutes.

    Returning None is exactly the documented fallback, so the code under test
    takes the same path it did before _fetch_weights existed: WhisperModel
    receives the repo id. A test that wants to exercise the download itself
    should undo this with its own monkeypatch.
    """
    monkeypatch.setattr(
        "core.transcriber.Transcriber._fetch_weights",
        lambda self: None,
    )
