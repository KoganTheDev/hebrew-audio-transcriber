"""Core transcription module.

Runs in the worker process (see core/worker.py for why: PyQt5 and
faster-whisper/ctranslate2 each bundle a conflicting copy of MSVCP140.dll on
Windows, and loading both in one process causes an intermittent native
crash). Every module under speech_to_text/core/ - this package and its
submodules, at any depth - must therefore never import PyQt5, and never
import speech_to_text.gui.i18n (gui/i18n.py's own docstring states the same
rule from the other side: nothing in core/ may import it). This is the one
place that rule is stated in prose; individual modules used to restate it
themselves, which meant eight near-identical sentences to keep in sync
instead of one. tests/test_layering.py enforces it by walking every module's
AST, so a violation fails a test rather than depending on someone re-reading
this paragraph.
"""
