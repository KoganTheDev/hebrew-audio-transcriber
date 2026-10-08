"""Reading and editing the user's term list file.

Two writers share this file - the GUI's terms dialog and a person in a text
editor - and one reader, the worker's correction pass. So editing is
line-preserving rather than "parse the terms, write the terms back": comment
lines and blank lines a person added by hand survive every add and remove.

Stdlib and core.hebrew_text only - the worker process imports this through
core.hebrew_corrections, and the GUI imports it directly.
"""

import os
import tempfile

from core.hebrew_text import normalize_word

# Written only when the app creates the file. No example terms: an example
# left in by accident is a live term that can rewrite someone's transcript.
HEADER = (
    "# Hebrew term list - names, places and jargon the model gets wrong.\n"
    "# One term per line. Lines starting with # are ignored.\n"
    "# Edited by the app's Custom terms dialog; editing it by hand works too.\n"
)


def is_term_line(line: str) -> bool:
    """Whether a raw file line holds a term, as opposed to a comment or blank."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def term_key(term: str) -> str:
    """The form two spellings are compared in to decide they are one term.

    normalize_word's rules (nikud, final letters) plus collapsed whitespace,
    so "באר  שבע" and "באר שבע" are one entry, not two that fight each other
    in the matcher's runner-up check.
    """
    return " ".join(normalize_word(term).split())


def _read_lines(path: str) -> list[str]:
    # utf-8-sig, not utf-8: Notepad can save with a byte-order mark, and plain
    # utf-8 would glue it onto the first term, which then never matches.
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read().splitlines()


def read_terms(path: str) -> list[str]:
    """The terms in a list file, in file order. A missing file is an empty list."""
    if not os.path.exists(path):
        return []
    return [line.strip() for line in _read_lines(path) if is_term_line(line)]


def validate_term(term: str) -> str:
    """The term as it would be stored, or ValueError if it cannot be one."""
    cleaned = term.strip()
    if not cleaned:
        raise ValueError("empty term")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError("a term is one line")
    if cleaned.startswith("#"):
        raise ValueError("a term cannot start with #, which marks a comment")
    return cleaned


def add_term(path: str, term: str) -> bool:
    """Append a term, creating the file with a header if needed.

    Returns False, writing nothing, when an equivalent term is already listed.
    Raises ValueError for input that cannot be a term and OSError when the
    file cannot be written.
    """
    cleaned = validate_term(term)
    lines = _read_lines(path) if os.path.exists(path) else HEADER.splitlines()
    key = term_key(cleaned)
    if any(is_term_line(line) and term_key(line) == key for line in lines):
        return False
    _write_atomic(path, lines + [cleaned])
    return True


def remove_term(path: str, term: str) -> bool:
    """Remove every line holding this term. Returns False if none did."""
    if not os.path.exists(path):
        return False
    lines = _read_lines(path)
    key = term_key(term)
    kept = [line for line in lines if not (is_term_line(line) and term_key(line) == key)]
    if len(kept) == len(lines):
        return False
    _write_atomic(path, kept)
    return True


def _write_atomic(path: str, lines: list[str]) -> None:
    """Replace the file in one step.

    A crash or a full disk halfway through a plain overwrite would leave a
    truncated list, and a truncated list fails silently: the correction pass
    just has fewer terms, and nothing says so. Writing a sibling temp file and
    os.replace-ing it over the original means a reader sees the old list or
    the new one, never half of one.
    """
    directory = os.path.dirname(os.path.abspath(path))
    # The per-user fallback location (config.resolve_terms_path) may not
    # exist yet on the first add.
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".hebrew_terms.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
