"""R1 rendering rules (render_md.py; PROTOCOL §12, Deviation 5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v1"))
sys.path.insert(0, str(ROOT))

import ixbrl  # noqa: E402

import render_md  # noqa: E402

HTML = """<html><body><p>CONSOLIDATED STATEMENTS OF INCOME</p><p>(In millions)</p>
<table>
<tr><td></td><td colspan="3">Year Ended December 31,</td></tr>
<tr><td></td><td>2025</td><td></td><td>2024</td></tr>
<tr><td>Net sales</td><td>$</td><td>4,210</td><td></td><td>$</td><td>3,987</td></tr>
<tr><td>Other, net</td><td>(</td><td>35</td><td>)</td><td>12</td></tr>
<tr><td>Margin</td><td>5.2</td><td>%</td><td>4.9</td><td>%</td></tr>
<tr><td></td><td></td></tr>
</table><p>Text after the table.</p></body></html>"""


def test_v1_text_is_unchanged_and_tables_become_markdown():
    out, stats = render_md.render({"doc.htm": HTML})
    v1_pages, r1_pages = out["doc.htm"]
    assert v1_pages == ixbrl.read_filing(HTML).pages  # the v1 rendering, byte for byte
    r1 = r1_pages[0].split("\n")
    assert r1[:2] == ["CONSOLIDATED STATEMENTS OF INCOME", "(In millions)"]  # text outside tables unchanged
    assert r1[-1] == "Text after the table."
    assert "| | Year Ended December 31, |" in r1
    i = r1.index("| | 2025 | 2024 |")
    assert r1[i + 1] == "|---|---|---|"  # separator after the last header row
    assert "| Net sales | $ 4,210 | $ 3,987 |" in r1  # "$" merged into its number, spacers dropped
    assert "| Other, net | (35) | 12 |" in r1  # parentheses merged
    assert "| Margin | 5.2% | 4.9% |" in r1  # percent merged
    assert stats["tables_with_header"] == 1 and stats["header_aligned"] == 1


def test_pages_have_the_same_count_and_split():
    out, _ = render_md.render({"doc.htm": HTML})
    v1_pages, r1_pages = out["doc.htm"]
    assert len(v1_pages) == len(r1_pages)
