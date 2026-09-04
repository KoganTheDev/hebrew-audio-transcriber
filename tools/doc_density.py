"""Measure how much of the codebase is prose rather than code.

The refactor that introduced this found the package was 51% prose - 5,808
lines of docstrings and comments against 5,631 of code, 1.03 lines of
commentary per line of code - with the extremes in tiny modules behind large
preambles (progress_scale.py was 5 lines of code and 80 of prose).

The point is not to minimise prose. This codebase explains why things are the
way they are, and that reasoning is why the awkward parts survive contact with
a later reader. The point is that restatement and history crowd it out, and a
reader cannot tell which is which. So this reports a ratio to argue with, not
a threshold to enforce - there is no exit code, and no linter can make this
judgement.

    python tools/doc_density.py [path ...] [--baseline FILE] [--save FILE]
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import pathlib
import sys
import tokenize
from typing import NamedTuple


class Counts(NamedTuple):
    """Line counts for one file, split by what each line actually carries."""

    total: int
    code: int
    doc: int
    comment: int
    blank: int

    @property
    def prose(self) -> int:
        """Docstring and comment lines together."""
        return self.doc + self.comment

    @property
    def ratio(self) -> float:
        """Lines of prose per line of code."""
        return self.prose / self.code if self.code else 0.0


def measure(path: pathlib.Path) -> Counts:
    """Split one module's lines into code, docstring, comment and blank."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    # Docstrings are counted by AST span rather than by looking for triple
    # quotes: a module can hold plenty of ordinary triple-quoted strings, and
    # only the ones in docstring position are documentation.
    doc_lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                span = first.value
                doc_lines.update(range(span.lineno, (span.end_lineno or span.lineno) + 1))

    comment = sum(
        1
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    )
    blank = sum(1 for line in lines if not line.strip())
    doc = len(doc_lines)
    # max(0, ...): a docstring line that also ends in a comment is counted by
    # both tallies, which can drive a docstring-only module below zero.
    code = max(0, len(lines) - blank - doc - comment)
    return Counts(len(lines), code, doc, comment, blank)


def collect(paths: list[str]) -> dict[str, Counts]:
    """Measure every .py file under each given path."""
    out: dict[str, Counts] = {}
    for raw in paths:
        root = pathlib.Path(raw)
        files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for f in files:
            if "__pycache__" in f.parts:
                continue
            try:
                out[f.as_posix()] = measure(f)
            except (SyntaxError, UnicodeDecodeError) as exc:
                print(f"skipped {f}: {exc}", file=sys.stderr)
    return out


def main() -> int:
    """Report prose-to-code ratios, worst first, optionally against a baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["src"], help="files or directories")
    parser.add_argument("--baseline", help="JSON from an earlier --save, to diff against")
    parser.add_argument("--save", help="write this run's numbers as JSON")
    args = parser.parse_args()

    results = collect(args.paths or ["src"])
    if not results:
        print("no Python files found", file=sys.stderr)
        return 1

    base = {}
    if args.baseline:
        base = json.loads(pathlib.Path(args.baseline).read_text(encoding="utf-8"))

    header = f"{'code':>6} {'prose':>6} {'ratio':>6} {'prose%':>7}"
    print(f"{header}  {'delta' if base else '':>7}  file")
    for name, c in sorted(results.items(), key=lambda kv: -kv[1].ratio):
        pct = c.prose / (c.prose + c.code) * 100 if (c.prose + c.code) else 0
        delta = ""
        if base and name in base:
            before = base[name]["prose"]
            if before != c.prose:
                delta = f"{c.prose - before:+d}"
        print(f"{c.code:6} {c.prose:6} {c.ratio:6.2f} {pct:6.0f}%  {delta:>7}  {name}")

    code = sum(c.code for c in results.values())
    prose = sum(c.prose for c in results.values())
    print(f"\nTOTAL  code {code}  prose {prose}  ratio {prose / code:.2f}", end="")
    if base:
        before = sum(v["prose"] for v in base.values())
        print(f"  (prose {prose - before:+d} against baseline {before})", end="")
    print()

    if args.save:
        payload = {k: v._asdict() | {"prose": v.prose} for k, v in results.items()}
        pathlib.Path(args.save).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"saved to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
