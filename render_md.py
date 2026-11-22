"""R1 table rendering (PROTOCOL.md §12, rules fixed in Deviation 5 before any R1 run).

Renders a filing exactly as v1's reader does (v1/ixbrl.py, unchanged), except that table rows become Markdown:
  1. one line per table row: `| cell | cell | cell |`;
  2. fragment cells are merged into their number: "$" and "(" join the next non-empty cell ("$ 512", "(35,027"),
     ")" and "%" (and ")%", "%)") join the previous one ("35,027)", "5.2%");
  3. empty spacer cells are dropped, except the row's first cell, which keeps the label column; a row whose
     cells are all empty is dropped (as in v1, where it renders as an empty line);
  4. header rows come first, followed by a `|---|` separator line: the header is the rows of a table above its
     first data row (a row whose first cell is not empty and that has a numeric cell, such as "$ 512", "(35,027)",
     "5.2%" or "1.5", a bare year such as "2025" not counting) that have at least two cells; the separator follows
     the last of them, with as many columns as the widest;
  5. everything outside tables is character for character the v1 text, and pages are split at the same lines as
     v1's, so page numbers and ids are unchanged.

`render(html_docs)` returns, per document, the v1 pages and the R1 pages side by side; build_r1.py checks that the
v1 pages equal the frozen ones byte for byte.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "v1"))
import ixbrl  # noqa: E402
from ixbrl import _MARKER, _SPACES, _ZERO_WIDTH, CELL_TAGS, _Reader, _split_lines  # noqa: E402

CELL, TABLE = "", ""  # private-use marks: a cell starts / a table starts (removed from the output)
PREFIX = {"$", "("}
SUFFIX = {")", "%", ")%", "%)"}
NUMERIC = re.compile(r"^[($\s]*\d[\d,]*(\.\d+)?\)?%?\)?$")
YEAR = re.compile(r"^(19|20)\d\d$")


class _MarkedReader(_Reader):
    """v1's reader, plus a mark where each table cell and each table starts."""

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if not self.hidden:
            if tag in CELL_TAGS:
                self.buf.append(CELL)
            elif tag == "table":
                self.buf.append(TABLE)


def _clean(s: str) -> str:
    """v1's line cleaning (ixbrl._render_page), fact markers removed."""
    return _SPACES.sub(" ", _ZERO_WIDTH.sub("", _MARKER.sub("", s))).strip()


def _row(raw_line: str) -> list[str]:
    parts = raw_line.split(CELL)
    cells = [_clean(c.replace(TABLE, "")) for c in parts[1:]]
    lead = _clean(parts[0].replace(TABLE, ""))
    if lead:  # text inside the row but before its first cell: part of the first cell
        cells = [f"{lead} {cells[0]}".strip(), *cells[1:]] if cells else [lead]
    # merge fragments: prefixes onto the next non-empty cell, suffixes onto the previous non-empty one
    out: list[str] = []
    pending = ""
    for i, c in enumerate(cells):
        if c in PREFIX:
            pending = f"{pending}{c}" if c == "(" else f"{pending}{c} "
            continue
        if c in SUFFIX and any(out):
            j = max(k for k, x in enumerate(out) if x)
            out[j] += c
            continue
        if c:
            c, pending = pending + c, ""
        out.append(c if c or i == 0 else "")
    if pending.strip():
        out.append(pending.strip())
    first, rest = out[0] if out else "", [c for c in out[1:] if c]
    return [first, *rest] if (first or rest) else []


def _md(cells: list[str]) -> str:
    return _SPACES.sub(" ", "| " + " | ".join(cells) + " |")


def _is_data(cells: list[str]) -> bool:
    return bool(cells and cells[0] and any(NUMERIC.match(c) and not YEAR.match(c) for c in cells[1:]))


def _render_raw_page(raw: str, stats: dict) -> tuple[list[str], list[str]]:
    """One raw page -> (v1 lines, R1 lines), the same length: line i of R1 is line i of v1 re-rendered (a header
    separator is appended to the last header row's line, so the counts stay equal)."""
    v1_lines, r1_lines = [], []
    header: list[tuple[int, list[str]]] | None = None  # (line index, cells) of the current table's header rows
    for raw_line in raw.split("\n"):
        if TABLE in raw_line:
            if header:
                stats["tables_without_data_rows"] += 1
            header = []
            stats["tables"] += 1
        c1 = _clean(raw_line.replace(CELL, "").replace(TABLE, ""))
        if not c1:
            continue
        if CELL not in raw_line:
            v1_lines.append(c1)
            r1_lines.append(c1)
            continue
        cells = _row(raw_line)
        line = _md(cells)
        if header is not None and _is_data(cells):
            if header:
                last, _ = header[-1]
                width = max(len(h) for _, h in header)
                r1_lines[last] += "\n|" + "---|" * width
                stats["tables_with_header"] += 1
                stats["header_aligned"] += len(header[-1][1]) == len(cells)
            header = None
        elif header is not None and len(cells) >= 2:
            header.append((len(r1_lines), cells))
        v1_lines.append(c1)
        r1_lines.append(line)
    return v1_lines, r1_lines


def render(docs: dict[str, str]) -> tuple[dict[str, tuple[list[str], list[str]]], dict]:
    """{document name: (v1 pages, R1 pages)} for one filing's documents, plus rendering statistics."""
    stats = {"tables": 0, "tables_with_header": 0, "header_aligned": 0, "tables_without_data_rows": 0}
    out = {}
    for name, html in docs.items():
        r = _MarkedReader()
        r.feed(html)
        r.close()
        v1_pages, r1_pages = [], []
        for raw in r.pages:
            v1_lines, r1_lines = _render_raw_page(raw, stats)
            n = 0
            for part in _split_lines(v1_lines):  # v1's split, applied to both
                v1_pages.append("\n".join(part))
                r1_pages.append("\n".join(r1_lines[n : n + len(part)]))
                n += len(part)
        out[name] = (v1_pages, r1_pages)
    return out, stats


assert ixbrl.MAX_PAGE_CHARS == 12_000  # the split rule this module relies on is v1's
