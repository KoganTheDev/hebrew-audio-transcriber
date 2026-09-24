# Test strategy

What is covered, what is deliberately not, and how to run it. Shaped after
ISO/IEC/IEEE 29119-3's test-plan intent, at the scale a single maintainer can
actually keep true.

## Running

```
pytest                       # everything, with coverage, ~40s
pytest -q --no-cov           # faster when iterating
QT_QPA_PLATFORM=offscreen pytest    # required with no display (CI does this)
```

The package is a src-layout; `pytest.ini` sets `pythonpath = src`, so no install
is needed to run the suite.

## CI checks

Four checks run in CI (`.github/workflows/ci.yml`, on Windows - PyQt5, the
PowerShell launcher and a path-resolution branch all target it), alongside pytest:

    ruff check src tests tools                # lint, including a McCabe complexity ceiling of 10
    ruff format --check src tests tools       # formatting
    lint-imports                              # the two architecture contracts - see ARCHITECTURE.md §1
    mypy -p core -p config -p gui.presenters -m hardware_detection

That mypy invocation is deliberately scoped. Those packages are at zero errors
under `disallow_untyped_defs` and CI fails if that changes. The whole-package
run is reported but not gated, because `gui/` still carries errors that are
PyQt5 shipping no type information rather than defects. See Coverage below
for the branch coverage gate.

## Levels

| Level | Where | What it proves |
|---|---|---|
| Unit | most of `tests/` | one module's logic, with every heavy dependency mocked |
| Contract | `test_layering.py`, `test_packaging.py`, `test_asset_order.py`, `test_i18n_keys.py` | structural rules that no single module owns |
| Rendering | `test_formatting.py`, `test_transcript_styles.py` | the generated HTML, including WCAG contrast |
| Front-end | `tests/js/*.mjs` via `test_js_behaviour.py` | the transcript's own JS, in jsdom under `node --test` |
| GUI | `test_gui.py`, `test_gui_theme.py`, `test_checkbox_style.py` | real widgets against a live `QApplication` |

The contract tests are the ones worth understanding, because they encode rules a
reader would otherwise have to be told:

- **`test_layering.py`** - `core/` must never import PyQt5 or `gui.i18n`. Walks
  every module with `pkgutil` and reads the AST's import nodes, so it cannot be
  fooled by a string. `import-linter` checks the same rule at lint time.
- **`test_packaging.py`** - every shipped CSS/JS/webp/ico asset is reached by a
  `package-data` glob, the console script resolves to a real function, `tests/`
  is not shipped, and `requirements*.txt` stay thin pointers at `pyproject.toml`.
  Without it a wheel installs cleanly and only fails later, when a user renders
  an unstyled transcript.
- **`test_asset_order.py`** - the JS fragments share one IIFE scope, so filename
  order is correctness. Guards that `00-preamble.js` sorts first and
  `99-init.js` last, that every fragment is numbered, and that no two share a
  prefix.
- **`test_i18n_keys.py`** - every i18n key `core/` emits exists in `STRINGS`
  with matching placeholders, and Latin quantities inside Hebrew strings are
  BiDi-isolated.

## Front-end (jsdom)

The transcript document's JavaScript - editing, autosave, speaker renaming,
search, audio, export, help panel, guided tour - is covered by a jsdom
behavioural suite at `tests/js/`, run with Node instead of pytest. Install
once with `npm install` (needs Node.js; jsdom is the only dependency), then
run it directly:

    node --test "tests/js/*.test.mjs"

`pytest` runs this suite too (`tests/test_js_behaviour.py`), so plain `pytest`
still catches a JS regression - but it skips with an explicit reason, rather
than failing, when `node` isn't on `PATH` or `node_modules/` hasn't been
installed.

A fragment does still pass `node --check` on its own, which is misleading:
Node treats a `.js` file as CommonJS and wraps it in a function, so even the
top-level `return` in `00-preamble.js` is legal there (as ESM it is an
"Illegal return statement"). Syntax-checking one fragment therefore proves
very little - a fragment references names other fragments define, so only the
concatenation the app renders is meaningful (see ARCHITECTURE.md's
cross-cutting section on why fragment order is load-bearing).
`test_js_behaviour.py` checks that concatenation.

Even with the jsdom suite, one gap remains: jsdom implements no real layout
and no `matchMedia` (the harness stubs it to "no preference"), so responsive
breakpoints, the tour spotlight's on-screen position, and
prefers-contrast/prefers-reduced-motion/dark-mode media queries are still
untested by either suite. That gap is a written checklist:
[transcript-manual-checks.md](transcript-manual-checks.md). Work it before
shipping a change to `core/assets/`.

## Deliberately out of scope

- **`tests/eval/*` are developer scripts, not tests.** `compare_models.py`,
  `compare_transcription.py` and `compare_diarization.py` are argparse CLIs that
  need real audio, real models and minutes to hours of wall clock. pytest does
  not collect them (no `test_*` functions). The thin `test_compare_models.py` /
  `test_diarization_metrics.py` / `test_hebrew_metrics.py` wrappers exist only to
  test those harnesses' plumbing, with the model fully mocked. To compare models
  on your own audio:

      python -m tests.eval.compare_models path/to/audio.m4a --models medium ivrit-turbo

  `compare_diarization.py` also takes `--engine sherpa|powerset|both`,
  `--num-speakers 0` (infer the count), and `--cluster-threshold` (repeatable
  or comma-separated) to sweep DIARIZATION_CLUSTER_THRESHOLD. `--audio`/`--rttm`
  accept any real recording, not just the AMI fixture: run `tests/eval/
  transcript_to_rttm.py <exported.html> <out.rttm>` on a hand-corrected export
  from this app's own editor to turn its speaker corrections into an RTTM
  reference (see `tests/eval/fixtures/diarization/hebrew_2spk.rttm`'s header
  for what it does and does not measure).

  This writes both transcripts side by side for reading, plus speed and
  confidence metrics. Without a reference transcript there is no accuracy
  percentage to report: confidence figures correlate with quality but do not
  measure it, and a confidently wrong model scores well. Hand-correct a few
  minutes of transcript and pass it with `--reference` to get a real word
  error rate, computed with Hebrew-appropriate normalization (nikud, final
  letters, and the app's own timestamps and speaker labels are all discounted).
- **No test downloads a model or touches the network.** Every heavy dependency
  is mocked. `test_js_behaviour.py` needs Node and skips - never fails - when
  `node_modules/` is absent.
- **Accuracy is not asserted.** Whether a transcript is *correct* Hebrew is
  measured by the eval harnesses against real recordings, by hand, not in CI.

## Coverage

Branch coverage, gated in CI at **83%** against a measured 83.47%. The gate
ratchets upward and must never be lowered to make a change fit.

It had drifted three ways at once: CI enforced 80, this line said 76, and the
suite measured 83. Worse, `pytest.ini` was missing `--cov-branch` while CI
passed it, so a local run reported 86% for the same code CI scored 83% - a
number that looked like headroom and was not. The flag now lives in
`pytest.ini`, so running `pytest` locally reports exactly what CI enforces, and
the ratchet has one number to move.

Coverage is not uniform by design: `core/` carries the logic a wrong answer
actually costs something, and is held higher than `gui/` construction code.
`app.py` sits near 22% because it is process bootstrap that a subprocess test
exercises end to end rather than line by line.

## Markers

`pytest.ini` declares `slow`, `integration` and `unit`. Only `integration` is
actually used, on the six tests in `test_integration.py`; `slow` and `unit` are
declared and applied nowhere, so `-m "not slow"` deselects nothing. Either apply
them or drop them from `pytest.ini` - a declared marker that filters nothing is
worse than no marker, because it reads like a working switch.

    pytest -m integration        # the six that exercise modules together
    pytest -m "not integration"  # everything else

## The shared QApplication

GUI tests take pytest-qt's built-in `qapp` fixture. **Do not define a local
`qapp` fixture in a test module.** A local definition shadows pytest-qt's, and
unless it is session-scoped it reintroduces a bug this suite has already been
bitten by once.

pytest-qt's `qapp` is session-scoped *and* stores the application it creates in
a module-level global (`pytestqt.plugin._qapp_instance`), so a Python reference
to it is held for the life of the whole run. That is exactly the property that
matters here.

**The incident.** Qt allows one `QApplication` per process, and
`QApplication.instance()` hands back whatever currently exists. A module-scoped
fixture that constructed the application and then tore down at the end of its
module dropped the only Python reference to it. `QApplication.instance()` then
came back as a fresh, distinct application for the next module, and every
QObject implicitly tied to the original was left invalid - including
`i18n.language_manager`, a module-level singleton constructed once at import
time. Symptom, reproduced and confirmed by bisection: `RuntimeError: wrapped
C/C++ object of type LanguageManager has been deleted`, raised deep inside
*unrelated* tests in `test_gui.py`. The fix was session scope.

The bug is ordering-dependent, which is why it hid for a while:
`test_checkbox_style.py` collects and tears its fixtures down before
`test_gui.py` alphabetically, so it was the file that happened to construct the
application first and destroy it first. A green single-file run proves nothing
about it - re-run the full suite, and `test_checkbox_style.py` followed by
`test_gui.py` in that order.

The same reference-lifetime trap applies to anything Qt takes C++ ownership of
while leaving the Python wrapper's lifetime to you - see the `painted_style`
fixture in `tests/test_checkbox_style.py` for the `QProxyStyle` version of the
same story.

`qapp` is a *bare* `QApplication`: it does not run `configure_application`, so
there is no stylesheet, no saved-language load and no process-wide keyboard
focus tracker. Tests needing any of those install them themselves.

**Binding pin.** `pytest.ini` sets `qt_api = pyqt5`. Left to guess, pytest-qt
picks the first binding it can import in the order PySide6, PyQt6, PyQt5 - and
PyQt6 is installed in the usual dev environment even though this app is PyQt5.
Unpinned, `qapp` builds a PyQt6 `QApplication` inside a PyQt5 process and the
interpreter aborts, mid-run, with no traceback. Do not remove that line.

## Conventions

Test names are full sentences describing the behaviour, not the function under
test - `test_a_second_drop_of_the_same_file_does_not_duplicate`, not
`test_add_file_2`. Every test file opens with a docstring explaining why the file
exists. Classes group by scenario (`TestModelSelectStepEstimateLanguage`), not
one class per module.

**A new regression test must be shown to fail against the unfixed code before it
is accepted.** A test that passes both before and after proves nothing, and this
suite has caught itself doing that more than once.
