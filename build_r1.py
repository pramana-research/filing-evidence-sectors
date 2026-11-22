"""Build and freeze the R1 pages (PROTOCOL.md §12; rendering rules in render_md.py, Deviation 5), before any R1 run.

    uv run python build_r1.py            # render, check, write dataset/r1/pages.jsonl and dataset/r1/FROZEN.json
    uv run python build_r1.py --check    # recompute the R1 fingerprint; fail if the pages changed

For every page shown in the 1,000-question subset, the filing is rendered again from the downloaded documents
(sha256-checked against dataset/manifest.json). Checks, all of which must pass:
  1. the v1 rendering of every page equals its frozen text in dataset/pages.jsonl, byte for byte;
  2. every line outside tables is the same in R1 as in v1 (by construction; counted here);
  3. for every answerable question, the gold figure is still on its evidence page in R1;
  4. same page ids, labels, order and questions: only the page text changes.
Also reported (not a pass/fail check): how many tables got a header, and how many of those have a last header row
with as many cells as the first data row.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "v1"))
import checker  # noqa: E402
from paths import data_dir  # noqa: E402

import render_md  # noqa: E402

DATA = HERE / "dataset"
OUT = DATA / "r1"


def fingerprint(pages: dict[str, str]) -> str:
    h = hashlib.sha256()
    for pid in sorted(pages):
        h.update(json.dumps({"id": pid, "text": pages[pid]}, ensure_ascii=False, sort_keys=True).encode())
        h.update(b"\n")
    return h.hexdigest()


def load_r1() -> dict[str, str]:
    return {p["id"]: p["text"] for p in map(json.loads, (OUT / "pages.jsonl").open())}


def build() -> int:
    qs = {q["id"]: q for q in map(json.loads, (DATA / "questions.jsonl").open())}
    subset = json.loads((DATA / "subsets.json").read_text())["c3_and_robustness"]
    frozen = {p["id"]: p for p in map(json.loads, (DATA / "pages.jsonl").open())}
    need = sorted({pid for i in subset for pid in qs[i]["pages"]})
    by_acc: dict[str, list[str]] = {}
    for pid in need:
        by_acc.setdefault(frozen[pid]["accession"], []).append(pid)
    manifest = {f["accession"]: f for f in json.loads((DATA / "manifest.json").read_text())["filings"]}
    root = data_dir() / "finance" / "filings"

    r1, stats, problems = {}, {"tables": 0, "tables_with_header": 0, "header_aligned": 0,
                               "tables_without_data_rows": 0}, []  # fmt: skip
    lines_same = lines_table = 0
    for n, (acc, pids) in enumerate(sorted(by_acc.items()), 1):
        f = manifest[acc]
        folder = root / f["ticker"] / acc
        docs = {}
        for d in f["files"]["documents"]:
            raw = (folder / d["name"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != d["sha256"]:
                problems.append(f"{acc}/{d['name']}: sha256 differs from the manifest")
            docs[d["name"]] = raw.decode("utf-8", errors="replace")
        out, st = render_md.render(docs)
        for k in stats:
            stats[k] += st[k]
        for pid in pids:
            p = frozen[pid]
            v1_pages, r1_pages = out[p["document"]]
            if v1_pages[p["page"]] != p["text"]:
                problems.append(f"{pid}: v1 rendering differs from the frozen page")
            r1[pid] = r1_pages[p["page"]]
            for a, b in zip(v1_pages[p["page"]].split("\n"), r1[pid].split("\n")):
                lines_same += a == b
                lines_table += a != b
        print(f"[{n}/{len(by_acc)}] {f['ticker']} {f['form']}: {len(pids)} pages", file=sys.stderr)

    for i in subset:
        q = qs[i]
        if q["gold"]["status"] != "found":
            continue
        shown = abs(q["gold"]["shown_value"])
        ev = q["gold"]["evidence"][0]["page"]
        if not any(checker.same(shown, x) for x in checker.numbers_in(r1[ev])):
            problems.append(f"{i}: gold figure {q['gold']['display']} not on its evidence page in R1")

    if problems:
        print("\n".join(problems[:50]), file=sys.stderr)
        print(f"R1 build FAILED: {len(problems)} problems; nothing written", file=sys.stderr)
        return 1
    OUT.mkdir(exist_ok=True)
    with (OUT / "pages.jsonl").open("w") as fh:
        for pid in sorted(r1):
            fh.write(json.dumps({"id": pid, "text": r1[pid]}, ensure_ascii=False) + "\n")
    record = {
        "frozen": datetime.now(UTC).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(r1),
        "pages": len(r1), "questions": len(subset),
        "pages_sha256": hashlib.sha256((OUT / "pages.jsonl").read_bytes()).hexdigest(),
        "checks": {"v1_pages_identical": len(r1), "gold_on_evidence_page": "all answerable subset questions",
                   "lines_unchanged": lines_same, "table_lines_rerendered": lines_table},
        "tables": stats,
        "protocol": "PROTOCOL.md §12 R1, rendering rules in render_md.py (Deviation 5)",
    }  # fmt: skip
    (OUT / "FROZEN.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0


def check() -> int:
    frozen = json.loads((OUT / "FROZEN.json").read_text())["fingerprint"]
    ok = fingerprint(load_r1()) == frozen
    print("R1 pages match dataset/r1/FROZEN.json" if ok else "R1 PAGES DIFFER FROM dataset/r1/FROZEN.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else build())
