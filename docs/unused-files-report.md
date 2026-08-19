# Unused Files Report

**Date:** 2026-08-18
**Branch:** `feature/transcript-help-and-tour`
**Scope:** tracked source tree (`git ls-files`, 137 files) plus untracked/ignored on-disk clutter. `.claude/worktrees/` was excluded from all greps - it is a stale duplicate checkout and doubles every hit.

The tracked source tree is clean: every Python module is imported somewhere (checked all 24 non-test, non-`__init__` modules by grepping for `import`/`from` references), all 60 vista images are consumed via a directory glob in `formatting.py`, and there are no `*_old`, `*.bak`, or "copy" files anywhere in the tracked set - only the word "copy" appearing in prose (UI strings, comments, LICENSE boilerplate). The real deletable/reclaimable material lives outside git: a stale agent worktree, multi-gigabyte model/asset caches, and test artifacts. On the tracked side, the only genuine candidates are a shadowed pytest config block and a `docs/mockups/` design-history folder that nothing in the shipped app touches.

## Verdict summary

- **Tracked deletion candidates:** ~288 KB across 7 mockup files + a ~6-line dead config block in `pyproject.toml`. Trivial in size, but real config drift risk.
- **Untracked/ignored clutter, reclaimable:** roughly **6.36 GB** total - `whisper_models/` (5.9 GB) + `vistas_source/` (110 MB) + `diarization_models/` (36 MB) + `mp3_test/` (305 MB, privacy issue) + `.claude/worktrees/` (7.1 MB) + coverage/cache/log artifacts (~2.7 MB).
- **Privacy flag:** `mp3_test/` (305 MB of real recordings) is not excluded by directory name in `.gitignore`, only its file extensions are - confirmed still true.

---

## Actions taken (2026-08-18)

Three of the recommendations below have been carried out; the rest are left as recommendations.

- **Done - `docs/mockups/` deleted** (7 files, ~288 KB). The four comments in `transcript.css` that named those files by path (the design register, the palette choice, the backdrop opacity, the squircle control style) were rewritten first, so each still records *why* the decision went the way it did without pointing at a file that no longer exists. The originals remain in git history.
- **Done - `mp3_test/` added to `.gitignore` by directory name**, beside `mp4a_test/`. The extension rules alone only caught the formats someone remembered to list; naming the directory closes the hole for anything inside it. Verified: `git add` now refuses the path outright, and nothing from it was ever tracked.
- **Done - the `[tool.pytest.ini_options]` block removed from `pyproject.toml`** (recommendation 5). No folding was needed: `pytest.ini` was already a strict superset, carrying `--strict-markers` and the `markers` table the shadowed block lacked.
- **Done - `setup.py` folded into `pyproject.toml` and deleted** (recommendation 7, in the order this report insisted on). Its `package_data`, `entry_points`, classifiers and package discovery moved across first; only then was the file removed. Verified by building a real wheel from `pyproject.toml` alone and installing it into a clean venv: all 60 vistas, the stylesheet, the script and the icon resolve from `site-packages`, the `speech-to-text` console script is generated, and no `tests/` or `docs/` content leaks in. `tests/test_packaging.py` is new and guards the whole arrangement - it was confirmed to actually fail when a `package-data` glob is removed, rather than passing vacuously.
- **Done - `requirements.txt` / `requirements-dev.txt` collapsed to pointers** (`-e .` and `-e .[dev]`). `pyproject.toml` is now the single source of truth for dependencies. The lists had already drifted before anyone noticed: `pytest>=7.0` against `pytest>=7.0.0`, and the same one-digit difference across `black`, `flake8` and `isort`.
- Suite green throughout at **344 passed, 1 skipped**.

---

## Tracked files - candidates

| Path | Size | Last commit | Referenced by | Verdict | Reasoning |
|---|---|---|---|---|---|
| `pyproject.toml` `[tool.pytest.ini_options]` (lines 74-79) | ~6 lines of a 1.9 KB file | 2026-08-12 `be1080c` | Nothing - pytest resolves `pytest.ini` first when both exist | **UNUSED** | Confirmed shadowed: `pytest.ini` exists at repo root and pytest always prefers it over `pyproject.toml`. Confirmed drifted: `pytest.ini`'s `addopts` has `--strict-markers` and a `markers =` table (`slow`, `integration`, `unit`); the `pyproject.toml` block has neither. A stray `[tool.pytest.ini_options]` edit here silently does nothing while looking authoritative - a live trap. |
| `docs/mockups/transcript-mockup.html` | 19.2 KB | 2026-08-13 `e7b94c3` | Nothing outside `docs/mockups/` | **UNUSED** | Zero inbound references from any tracked file outside the mockups folder. |
| `docs/mockups/style-document.css` | 11.9 KB | 2026-08-13 `e7b94c3` | Nothing outside `docs/mockups/` | **UNUSED** | Same - no references found anywhere. |
| `docs/mockups/mockup.js` | 18.8 KB | 2026-08-13 `e7b94c3` | Nothing outside `docs/mockups/` | **UNUSED** | Same - no references found anywhere. |
| `docs/mockups/style-console.css` | 13.0 KB | 2026-08-13 `e7b94c3` | Prose comment in `speech_to_text/core/assets/transcript.css:13` | **LIKELY UNUSED** | Cited once, in a comment explaining where a design register originated. Not loaded or built from. Design provenance only. |
| `docs/mockups/control-styles.html` | 18.9 KB | 2026-08-16 `0723b71` | Prose comment in `transcript.css:252-253`; cross-referenced by `palette-and-chrome.html:8,333` | **LIKELY UNUSED** | Line numbers have moved since the prior audit (was ~202/~490, now 252-253) but the finding holds: comment-only citation, not a build input. |
| `docs/mockups/palette-and-chrome.html` | 50.5 KB | 2026-08-16 `0723b71` | Prose comment in `transcript.css:41`; cross-referenced by `backdrop-and-chrome.html:6,153` | **LIKELY UNUSED** | Same pattern - cited by comment only. |
| `docs/mockups/backdrop-and-chrome.html` | 149.0 KB | 2026-08-16 `af8010c` | Prose comment in `transcript.css:165` | **LIKELY UNUSED** | Same pattern. Largest file in the folder; the whole `docs/mockups/` directory is also absent from the README's "Project Structure" tree (README.md:141-175 lists only `docs/architecture.drawio` and `docs/architecture.jpg`). |
| `run.bat` | 743 B | 2026-07-19 `f8266f9` | Not referenced in README or any tracked file | **USED, undocumented** | Still functionally correct: it runs `python -m speech_to_text.main`, which matches the current entry point (`speech_to_text/main.py:38` defines `main()`, `speech_to_text/main.py:144` has the `if __name__` guard). About 30 days older than the newest tracked files (last touched `f8266f9`, 2026-07-19; most of the tree was last touched 2026-08-16/17/18) - consistent with being the original delivery path for non-technical Windows users that nobody has needed to revisit. Recommendation is a README mention, not deletion. |
| `run.ps1` | 2.6 KB | 2026-07-19 `f8266f9` | Not referenced in README or any tracked file | **USED, undocumented** | Same commit as `run.bat`, same reasoning; also still points at `speech_to_text.main` correctly and has its own Python-resolution fallback logic (Store-alias detection, `%LOCALAPPDATA%` search) that is more robust than `run.bat`'s. |
| `requirements.txt` | 226 B | 2026-08-12 `04021a8` | `setup.py:8-9` reads it for `install_requires`; README:110 references `requirements-dev.txt` | **USED, but duplicated** | `setup.py` actually parses this file at build time, so it is not dead - but its contents (`faster-whisper`, `sherpa-onnx`, `PyQt5`, `tqdm`, `psutil`) duplicate `pyproject.toml`'s `dependencies` list verbatim. Two sources of truth that can silently drift apart. |
| `requirements-dev.txt` | 141 B | 2026-06-03 `d4152e6` (unchanged since initial commit) | README.md:110 (`pip install -r requirements-dev.txt`) | **USED, but duplicated** | Duplicates `pyproject.toml`'s `[project.optional-dependencies].dev` list. Same drift risk as above. |

## Tracked files - confirmed used

- **All 30 `speech_to_text` core Python modules** (`config.py`, `hardware_detection.py`, `main.py`, `core/*.py`, `gui/*.py`, `gui/steps/*.py`) - each has at least one inbound `import`/`from` reference elsewhere in the tracked tree; verified with a per-module grep. `speech_to_text/__main__.py` shows 0 grep hits because it is invoked via `python -m speech_to_text`, not imported - expected for a package entry-point marker, not evidence of dead code.
- **All 16 test modules under `tests/`** plus `tests/conftest.py` - standard pytest discovery picks these up via `pytest.ini`'s `testpaths = tests`.
- **`tests/eval/` harness** (`compare_models.py`, `hebrew_metrics.py`, `__init__.py`) - documented and used from the README (README.md:195-203, `python -m tests.eval.compare_models`), and `tests/test_hebrew_metrics.py:11` imports `hebrew_metrics` directly. `__init__.py` is 0 bytes but load-bearing as the package marker that makes `-m tests.eval.compare_models` resolvable.
- **All 60 `speech_to_text/core/assets/vistas/*.webp`** (30 landscape + 30 matching `-portrait` crops) - `formatting.py:309` globs the directory (`_VISTAS_DIR.glob("*.webp")`) rather than naming files, so every file present is reachable at render time; none is individually dead. Re-counted at 60, matching the prior audit.
- **`speech_to_text/assets/icon.ico`, `speech_to_text/core/assets/transcript.css`, `transcript.js`** - packaged via `setup.py`'s `package_data` and inlined into every generated transcript by `formatting.py`.
- **`tools/build_vistas.py`** - not imported by the app (it's a one-off asset pipeline script, run manually), but actively referenced by comments in `formatting.py` (lines 287, 321, 525, 544) explaining vista-cropping conventions it enforces. Keep - it is the tool that (re)produces the tracked `.webp` files.
- **`setup.py`** - do not delete (see below).
- **Docs, license, screenshots**: `docs/architecture.drawio`/`.jpg` (embedded in README:91), the four `docs/screenshot-*.png` (README:84-87), `docs/transcript-manual-checks.md` (README:190), `hebrew_terms.example.txt` (README:75), `LICENSE` (README:207) - all directly linked from README.md.

## Untracked / ignored clutter

| Path | Size | Status |
|---|---|---|
| `.claude/worktrees/agent-ae356780d22b30f13/` | 7.1 MB | Stale agent worktree on branch `worktree-agent-ae356780d22b30f13`, confirmed still present via `git worktree list`. Pollutes every grep across the repo if not excluded. |
| `mp3_test/` | **305 MB** | **Privacy issue.** Holds real recordings. `.gitignore` excludes `*.mp3` and other extensions, and separately names `mp4a_test/` and `eval_output/` by directory - but `mp3_test/` itself is not named anywhere in `.gitignore`. Confirmed: `mp4a_test/` no longer exists on disk (already cleaned up or renamed to `mp3_test/`), so `mp3_test/` is the only real-audio fixture directory left unprotected. `.gitignore`'s own comment block (media section) states the repo is public. |
| `whisper_models/` | 5.9 GB | Regenerable - downloaded on first use per the README's "First-use download" table. |
| `vistas_source/` | 110 MB | Regenerable - full-size vista originals; `.gitignore` already excludes this directory by name, with a comment explaining only the processed WebP output is tracked. |
| `diarization_models/` | 36 MB | Regenerable - sherpa-onnx speaker-ID model weights, downloaded on first use (README:69). |
| `htmlcov/` | 2.3 MB | Pure test artifact (`pytest --cov-report=html`). |
| `.pytest_cache/` | 47 KB | Pure test artifact. |
| `__pycache__/` (root) | 12 KB | Pure bytecode cache. |
| `.coverage` | 52 KB | Pure test artifact. |
| `eval_output/` | 28 KB | Ignored via `.gitignore`; output of the `tests/eval/` harness. |
| `speech_to_text.log` | 323 KB | Runtime log, ignored via `*.log`. |
| `eval_run.log` | 3.3 KB | Runtime log, ignored via `*.log`. |
| `server.log` | 435 B | Runtime log, ignored via `*.log`. |

## Recommended actions, ordered by safety

1. **Remove the stale worktree.**
   ```
   git worktree remove .claude/worktrees/agent-ae356780d22b30f13
   git branch -D worktree-agent-ae356780d22b30f13
   ```
   Risk: none - it's a duplicate checkout, not unique work. Do not `rm -rf` it directly; that leaves the worktree registered in `.git/worktrees/` and git will complain on the next `worktree` command.

2. **Delete pure build/test artifacts.**
   ```
   rm -rf htmlcov .pytest_cache __pycache__ .coverage eval_output speech_to_text.log eval_run.log server.log
   ```
   Risk: none - all regenerated by the next `pytest` run or app launch.

3. **Delete regenerable model/asset caches** (only if disk space is needed; re-downloading `whisper_models/` costs bandwidth and `vistas_source/` requires re-running `tools/build_vistas.py` against original source images if you still have them).
   ```
   rm -rf whisper_models diarization_models vistas_source
   ```
   Risk: low but not free - `whisper_models/` and `diarization_models/` redownload automatically on next run; `vistas_source/` only regenerates if you still have the original photos elsewhere (it is not derivable from anything else in the repo).

4. **DONE - Add `mp3_test/` to `.gitignore` by name** (privacy fix, not just an extension rule):
   ```
   mp3_test/
   ```
   Add this line near the existing `mp4a_test/` entry in `.gitignore`. This does not delete the 305 MB of recordings - it only stops them from ever being staged. Deleting the recordings themselves is a separate, human call (they may still be needed for eval work).

5. **DONE - Fold `pyproject.toml`'s `[tool.pytest.ini_options]` into `pytest.ini`, then delete the block.** Since `pytest.ini` already wins and is more complete (`--strict-markers`, `markers` table), just remove lines 74-79 from `pyproject.toml`. Risk: none - the block currently does nothing at all.

6. **Move `run.bat` / `run.ps1` into the README** as the documented Windows launch path, rather than deleting them. They are correct and still match the current entry point. Risk of deleting: real - they are plausibly how less technical users actually run the app, and nothing else provides that experience.

7. **DONE - Consolidate dependency lists.** Make `requirements.txt` and `requirements-dev.txt` the single source (or generate them from `pyproject.toml` with a small script / `pip-compile`), since `setup.py` already reads `requirements.txt` directly. Until `setup.py`'s dependency-loading is migrated into `pyproject.toml`, do not delete either requirements file - `setup.py` needs `requirements.txt` to build at all.

8. **DONE - Deleting `docs/mockups/`** once its design-provenance comments in `transcript.css` (lines 13, 41, 165, 252-253) are either removed or rewritten to not depend on the files existing. Not urgent - 288 KB total, does no harm sitting in the tree - but it's dead weight for anyone cloning the repo, and it's already invisible in the README's structure diagram. Lowest priority because it's the only candidate with any historical/design value.

## Do not delete

- ~~**`setup.py`**~~ - RESOLVED, see "Actions taken" above. It was the only place declaring `package_data` (`assets/*.ico`, `speech_to_text.core`'s `assets/*.css`, `assets/*.js`, `assets/vistas/*.webp`, confirmed at `setup.py:38-41`) and the `speech-to-text` console entry point (`setup.py:44-47`). Deleting it before migrating those two blocks into `pyproject.toml` ships transcripts with no CSS/JS/backdrops, silently.
- **`tests/eval/__init__.py`** - 0 bytes, but load-bearing as the package marker that makes `python -m tests.eval.compare_models` resolvable. Confirmed still 0 bytes.
- **`speech_to_text/core/assets/vistas/*.webp` (all 60)** - consumed via `_VISTAS_DIR.glob("*.webp")` in `formatting.py:309`, so no individual file can be identified as unused by static reference-counting; the whole directory is the unit of use. Count re-verified at 60 (30 landscape + 30 portrait).
