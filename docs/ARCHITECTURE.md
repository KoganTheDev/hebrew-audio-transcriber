# Architecture

An arc42-shaped sketch, kept to the four sections that earn their place on a
project this size. It exists so module docstrings do not each have to re-narrate
the whole system: the narrative lives here, once, and the code explains only
what is local to it.

## 1. Constraints

**`core/` must never import PyQt5, and never `speech_to_text.gui.i18n`.**

This is the one rule that shapes everything else, and it is not a style
preference. On Windows, PyQt5 and faster-whisper/ctranslate2 each bundle a
conflicting copy of `MSVCP140.dll`. Loading both into one process causes an
intermittent native crash - the kind that produces no Python traceback and looks
like a hardware fault. So transcription runs in a **separate process** that
never imports Qt at all.

Two mechanisms enforce it, deliberately at different times:

| Mechanism | When it fires |
|---|---|
| `tests/test_layering.py` | test time; walks every module under `core/` with `pkgutil` and inspects the AST's import nodes |
| `import-linter` contract in `pyproject.toml` | lint time; `lint-imports` in CI |

Consequences that look arbitrary until you know the rule: `core/` cannot use
`QStandardPaths` for per-user directories, so `config` resolves them with plain
`os.path`; and duration formatting exists twice, because the half that renders
translated units belongs to the GUI and the half that estimates belongs to
`hardware_detection`.

**Everything runs locally.** No audio leaves the machine, no account is needed,
and the generated transcript loads nothing over the network - fonts, styles,
scripts and backdrop photos are all inlined into the single HTML file.

## 2. Building blocks

```
src/speech_to_text/
  main.py              process entry: logging, dependency check, Qt import ORDER
  config.py            model table, tuned constants, path resolution
  hardware_detection.py CPU/RAM/GPU probe, model recommendation, time estimates
  core/                everything that runs in the worker process. No Qt, ever.
    worker.py            the batch pipeline: load model, per file decode ->
                         transcribe -> diarize -> correct, checkpoint, render
    transcriber.py       wraps faster-whisper; emits Segment objects
    audio_source.py      PyAV decode; detects true-stereo two-party recordings
    diarization.py       sherpa-onnx model lifecycle and engine dispatch
    speaker_attribution.py  deciding which speaker each word belongs to
    diarization_powerset.py opt-in second engine, decodes the model itself
    segmentation.py      pure-numpy powerset decode maths
    hebrew_correct.py    term-list correction of low-confidence Hebrew words
    hebrew_text.py       Hebrew normalization and BiDi isolation
    segments.py          Word / Segment / TranscriptDocument - shared vocabulary
    formatting/          renders those into the self-contained HTML transcript
    assets/css|js        the transcript's own front-end, concatenated in order
  gui/                 PyQt5. Runs in the main process.
    presenters/          decisions, with NO Qt import - see below
    main_window.py       the 3-step wizard shell, navigation, thread wiring
    steps/               file select, model select, transcription
    widgets.py           DropZone, IconTextButton, and the make_label factory
    theme.py             Catppuccin palette + QSS builders
    i18n.py              English/Hebrew strings and RTL handling
    threads.py           QThread wrappers that own the worker subprocess
```

The dependency direction is one-way: `gui/` may import `core/`, never the
reverse. `core/segments.py` is the shared vocabulary both sides agree on, and it
depends on nothing.

**`gui/presenters/` extends that rule one layer outward.** It holds the
decisions a view has to make - what the file summary should say, which device
to run on, what options to build - as pure functions over a frozen dataclass,
and it imports no Qt at all. That is what makes those decisions testable
without a `QApplication`: `tests/test_presenters.py` runs in 0.2s with no
display and no platform plugin. Note that `gui/i18n.py` DOES import PyQt5
(`QObject`/`QSettings`/`pyqtSignal` back the language state), so a presenter
takes a `translate` callable rather than importing `t` directly. A second
import-linter contract pins the rule.

## 3. Runtime: one transcription

The process boundary is the interesting part.

```
GUI process                          │  worker process (no Qt)
─────────────────────────────────────┼──────────────────────────────────────
MainWindow._start_transcription      │
  builds TranscriptionOptions        │
  TranscriptionThread (QThread)      │
    multiprocessing.Process ─────────┼──> run_transcription_process
    polls progress_queue             │      load model (once, for the batch)
   <─ ("progress", key, params, pct) ┼      for each file:
   <─ ("status", key, params) ───────┼        decode audio (PyAV)
    emits Qt signals to the UI       │        transcribe (faster-whisper)
                                     │        diarize (overlapped thread)
                                     │        correct Hebrew terms
                                     │        write HTML checkpoint
   <─ ("finished", output_file) ─────┼      render final document
   <─ ("error", key, params) ────────┼      on failure
```

Two details worth knowing:

- **Progress crosses three coordinate systems** - the transcriber's own absolute
  scale, one file's local 0-100, and the batch-wide scale the progress bar
  actually shows. `core/progress_scale.py` names every boundary so the remapping
  arithmetic is not bare integers retyped at each site.
- **The output file is rewritten after every file**, not once at the end. A crash
  at file 9 of 10 still leaves nine transcripts on disk.

## 4. Cross-cutting

**Internationalisation.** The UI is English/Hebrew with a full RTL mirror.
`gui/i18n.py` holds the strings; `core/` emits *keys and parameters*, never
rendered text, which is why `tests/test_i18n_keys.py` can AST-scan `core/` for
emitted keys and check each one exists with matching placeholders. Latin
quantities embedded in Hebrew strings are wrapped in BiDi isolates (U+2066 /
U+2069), because rule N1 otherwise lets a digit run reorder the punctuation
around it.

**Logging.** Configured once, in `main.py`, before anything else runs. The
console handler uses `VisualOrderFormatter` so Hebrew log lines read correctly
in a terminal that does no BiDi of its own; the file handler does not.

**The transcript's own front-end.** `core/assets/css/*.css` and
`core/assets/js/*.js` are concatenated in plain filename order and inlined. The
numeric prefixes are therefore load-bearing: the JS fragments are bare statement
bodies sharing one IIFE scope, so `00-preamble.js` must sort first (it holds a
`return` guard) and `99-init.js` must sort last. `tests/test_asset_order.py`
enforces this. Gaps in the numbering (00, 08, 16 ...) are insertion headroom.

**Failure policy.** An optional or partial failure costs only itself.
Diarization failing leaves an unlabelled but complete transcript; one bad file
in a batch does not cost the other nine. This is why `core/` carries 23
`except Exception` sites, each with a written justification at the call site.
