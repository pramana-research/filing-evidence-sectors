"""Automatic checks on the built sectors set before it is frozen (PROTOCOL.md §13, "before any run").

    uv run python sets/sectors/validate.py

Fails (exit 1) on any problem; prints a summary either way.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from build import PER_SECTOR, fact_key, v1_exclusions  # noqa: E402

import checker  # noqa: E402

DATA = HERE / "dataset"
MAX_TOKENS = 3000


def main() -> int:
    qs = [json.loads(line) for line in (DATA / "questions.jsonl").open()]
    pages = {p["id"]: p for p in map(json.loads, (DATA / "pages.jsonl").open())}
    subset = json.loads((DATA / "subsets.json").read_text())["c3_and_robustness"]
    v1_keys, v1_texts = v1_exclusions()
    problems: list[str] = []

    def check(ok: bool, msg: str):
        if not ok:
            problems.append(msg)

    ids = [q["id"] for q in qs]
    check(len(qs) == 10 * PER_SECTOR, f"{len(qs)} questions, expected {10 * PER_SECTOR}")
    check(len(set(ids)) == len(ids), "duplicate question ids")
    texts = Counter(q["question"] for q in qs)
    check(
        all(n == 1 for n in texts.values()), f"{sum(n > 1 for n in texts.values())} repeated question texts"
    )
    for sector, n in Counter(q["sector"] for q in qs).items():
        check(n == PER_SECTOR, f"{sector}: {n} questions")

    overlap_text = overlap_fact = 0
    for q in qs:
        g = q["gold"]
        overlap_text += q["question"] in v1_texts
        if g["status"] == "found":
            overlap_fact += fact_key(q["accession"], g) in v1_keys
            ev = g["evidence"][0]
            check(ev["page"] in q["pages"], f"{q['id']}: evidence page not among the shown pages")
            text = pages[ev["page"]]["text"] if ev["page"] in pages else ""
            lines = {checker.norm_ws(x) for x in text.split("\n")}
            check(checker.norm_ws(ev["line"]) in lines, f"{q['id']}: evidence line not on its page")
            check("tags" in q and "units_location" in q["tags"], f"{q['id']}: difficulty tags missing")
        else:
            check(q["slice"] == "S8" or g["status"] == "not_found", f"{q['id']}: bad not_found question")
        for pid in q["pages"]:
            check(pid in pages, f"{q['id']}: page {pid} missing")
            check(
                pages.get(pid, {}).get("tokens", 0) <= MAX_TOKENS,
                f"{q['id']}: page {pid} over {MAX_TOKENS} tokens",
            )
        check(len(q["pages"]) == 3, f"{q['id']}: {len(q['pages'])} pages shown")
    check(overlap_text == 0, f"{overlap_text} question texts reused from v1")
    check(overlap_fact == 0, f"{overlap_fact} facts reused from v1")

    sub_sector = Counter(next(q["sector"] for q in qs if q["id"] == i) for i in subset)
    check(len(subset) == 1000 and len(set(subset)) == 1000, f"subset has {len(subset)} ids")
    check(all(n == 100 for n in sub_sector.values()), f"subset per sector: {dict(sub_sector)}")
    check(set(subset) <= set(ids), "subset contains unknown ids")

    print(f"{len(qs):,} questions · {len(pages):,} pages · subset {len(subset):,}")
    print(f"reused from v1: {overlap_text} question texts, {overlap_fact} facts")
    print("problems:", "none" if not problems else f"{len(problems)}")
    for p in problems[:30]:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
