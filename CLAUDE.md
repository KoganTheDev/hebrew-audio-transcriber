# Hebrew Audio Transcriber

PyQt5 desktop app: Hebrew audio -> faster-whisper (+ sherpa-onnx diarization) -> HTML transcript.
Architecture: docs/ARCHITECTURE.md. Tests, CI and coverage policy: docs/TESTING.md.

## Commands (always via the project venv - bare `python` is not it)

```
.venv\Scripts\python -m pytest -q --no-cov -m "not slow"   # fast loop, ~10s
.venv\Scripts\python -m pytest                              # full + coverage, ~70s
.venv\Scripts\python -m ruff check src tests tools
.venv\Scripts\python -m ruff format --check src tests tools
.venv\Scripts\python -m mypy -p config -p core -p gui -m hardware_detection   # zero errors, gated in CI
.venv\Scripts\lint-imports                                  # needs PYTHONPATH=src, else it checks nothing
.venv\Scripts\python tools/doc_density.py --baseline docs/doc-density-baseline.json
npm test                                                    # transcript page JS (jsdom)
```

## Architecture rules (enforced by import-linter and tests)

- `core/` never imports `gui/` or PyQt5; transcription runs in a separate worker process.
- `gui/presenters/` is Qt-free logic; put decisions there, widgets only render.

## Gotchas

- Any script that loads both: import `faster_whisper` BEFORE PyQt5 (MSVCP140.dll
  conflict), or the worker dies with err_worker_exited.
- Scripts must call `i18n.set_language(lang, save=False)` - without it they
  overwrite the user's saved language.
- Visual checks: grab SHOWN windows (never-shown grabs garble Hebrew); headless
  virtual time does not advance animations. Prove "no visual change" refactors
  with a pixel diff against the previous commit - font build order can change
  glyph rasterization (see MainWindow._render_title).
- App-wide event filters must be removed on `aboutToQuit`, or exit crashes.
- Real runs offline: set HF_HUB_OFFLINE=1.
- Source files are CRLF; scripted edits must preserve line endings.
- OneDrive locks `.git/worktrees/*`: if `git worktree remove/prune` says
  Permission denied, PowerShell `Remove-Item -Recurse -Force` works.

## Comments

Keep the non-obvious "why"; no history narration ("used to", "a run showed")
or restating the signature. Watch the doc_density ratio, don't game it.
