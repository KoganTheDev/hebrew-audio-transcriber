# Test strategy

What is covered, what is deliberately not, and how to run it. Shaped after
ISO/IEC/IEEE 29119-3's test-plan intent, at the scale a single maintainer can
actually keep true.

## Running

```
pytest                       # everything, with coverage, ~50s
pytest -q --no-cov           # faster when iterating
QT_QPA_PLATFORM=offscreen pytest    # required with no display (CI does this)
```

The package is a src-layout; `pytest.ini` sets `pythonpath = src`, so no install
is needed to run the suite.

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

## Deliberately out of scope

- **`tests/eval/*` are developer scripts, not tests.** `compare_models.py`,
  `compare_transcription.py` and `compare_diarization.py` are argparse CLIs that
  need real audio, real models and minutes to hours of wall clock. pytest does
  not collect them (no `test_*` functions). The thin `test_compare_models.py` /
  `test_diarization_metrics.py` / `test_hebrew_metrics.py` wrappers exist only to
  test those harnesses' plumbing, with the model fully mocked.
- **No test downloads a model or touches the network.** Every heavy dependency
  is mocked. `test_js_behaviour.py` needs Node and skips - never fails - when
  `node_modules/` is absent.
- **Accuracy is not asserted.** Whether a transcript is *correct* Hebrew is
  measured by the eval harnesses against real recordings, by hand, not in CI.

## Coverage

Branch coverage, gated in CI at **76%** against a measured 76.83%. The gate
ratchets upward and must never be lowered to make a change fit.

Coverage is not uniform by design: `core/` carries the logic a wrong answer
actually costs something, and is held higher than `gui/` construction code.
`main.py` sits near 22% because it is process bootstrap that a subprocess test
exercises end to end rather than line by line.

## Markers

`pytest.ini` declares `slow`, `integration` and `unit`. Only `integration` is
actually used, on the six tests in `test_integration.py`; `slow` and `unit` are
declared and applied nowhere, so `-m "not slow"` deselects nothing. Either apply
them or drop them from `pytest.ini` - a declared marker that filters nothing is
worse than no marker, because it reads like a working switch.

    pytest -m integration        # the six that exercise modules together
    pytest -m "not integration"  # everything else

## Conventions

Test names are full sentences describing the behaviour, not the function under
test - `test_a_second_drop_of_the_same_file_does_not_duplicate`, not
`test_add_file_2`. Every test file opens with a docstring explaining why the file
exists. Classes group by scenario (`TestModelSelectStepEstimateLanguage`), not
one class per module.

**A new regression test must be shown to fail against the unfixed code before it
is accepted.** A test that passes both before and after proves nothing, and this
suite has caught itself doing that more than once.
