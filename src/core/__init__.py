"""Core transcription, run in the worker process.

Nothing under core/, at any depth, may import PyQt5 or gui.i18n: PyQt5 and
faster-whisper/ctranslate2 bundle conflicting copies of MSVCP140.dll on
Windows, and loading both in one process crashes intermittently.
tests/test_layering.py enforces this.
"""
