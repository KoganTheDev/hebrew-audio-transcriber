"""
Shells out to `node --test` for the jsdom behavioural suite covering
transcript.js (tests/js/*.test.mjs, built on tests/js/harness.mjs) - see that
directory's own docstrings for what is covered and why it exists (Stage 1 of
the transcript-page test rewrite: exact source-text greps replaced by real
DOM behaviour).

This is one pytest test, not forty-plus: `pytest`'s job here is only to make
`py -3 -m pytest` a single command that also catches a JS regression, not to
re-implement node's own test runner or its reporting. node --test's full
per-test output is captured and surfaced verbatim on failure (see
pytest.fail below) so a CI log or a local run shows exactly which assertion
broke, in the same shape `npm test` would print it directly.

Skipped, not failed, when the toolchain is unavailable - a machine with no
Node installed, or one where `npm install` was never run, must still be able
to run the Python suite. This mirrors the "verified present" note in the
Stage 1 task itself: Node/npm are a real dependency of transcript.js's own
tests, but not of the Python package, and pytest failing outright on a
clean checkout with no node_modules/ would be a worse failure mode than a
loud, explicit skip.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NODE_MODULES = _REPO_ROOT / "node_modules"


def _node_executable():
    return shutil.which("node")


@pytest.mark.skipif(
    _node_executable() is None,
    reason="node is not on PATH - the tests/js/ jsdom suite needs Node.js (see package.json)",
)
@pytest.mark.skipif(
    not _NODE_MODULES.is_dir(),
    reason="node_modules/ is missing - run `npm install` at the repo root to fetch jsdom first",
)
def test_transcript_js_behaviour_suite():
    result = subprocess.run(
        [_node_executable(), "--test", "tests/js/**/*.test.mjs"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        # Windows needs the shell to expand the glob for node --test; on
        # POSIX shells this is a no-op since node itself accepts the literal
        # argument just as well when a shell has already expanded it.
        shell=sys.platform == "win32",
    )
    if result.returncode != 0:
        pytest.fail(
            "node --test tests/js/**/*.test.mjs failed "
            f"(exit {result.returncode}):\n\n--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
