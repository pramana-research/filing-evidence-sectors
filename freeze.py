"""Freeze the Filing-Evidence Sectors dataset (PROTOCOL.md §13) after the automatic checks pass.

    uv run python freeze.py            # validate, then write dataset/FROZEN.json
    uv run python freeze.py --check    # recompute the fingerprint; fail if the data changed

The fingerprint is computed exactly as v1's (v1's freeze.py): sha256 over the questions sorted by id,
each contributing its id, its gold (status, value, unit, scale, period, dims, evidence) and the texts of the
pages it shows. Every result cites it. The human audit is non-blocking (§13): errors it finds lead to a new
version with a new fingerprint, logged in §14.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "dataset"
FILES = ["questions.jsonl", "pages.jsonl", "subsets.json", "manifest.json"]


def fingerprint() -> str:
    qs = sorted((json.loads(line) for line in (DATA / "questions.jsonl").open()), key=lambda q: q["id"])
    pages = {p["id"]: p["text"] for p in map(json.loads, (DATA / "pages.jsonl").open())}
    h = hashlib.sha256()
    for q in qs:
        g = q["gold"]
        record = {
            "id": q["id"],
            "gold": {k: g.get(k) for k in ("status", "value", "unit", "scale", "period", "dims", "evidence")},
            "pages": [pages[p] for p in q["pages"]],
        }
        h.update(json.dumps(record, sort_keys=True, ensure_ascii=False).encode())
        h.update(b"\n")
    return h.hexdigest()


def main() -> int:
    if "--check" in sys.argv:
        frozen = json.loads((DATA / "FROZEN.json").read_text())["fingerprint"]
        ok = fingerprint() == frozen
        print("dataset matches FROZEN.json" if ok else "DATASET DIFFERS FROM FROZEN.json")
        return 0 if ok else 1
    if subprocess.run([sys.executable, str(HERE / "validate.py")]).returncode != 0:
        print("validation failed: not freezing")
        return 1
    out = {
        "frozen": datetime.now(UTC).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(),
        "files": {f: hashlib.sha256((DATA / f).read_bytes()).hexdigest() for f in FILES},
        "protocol": "PROTOCOL.md v1.0 with deviation 1 (§14)",
        "human_audit": "non-blocking (§13); recorded in review/sectors/, reported with the dataset",
    }
    (DATA / "FROZEN.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"frozen: {out['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
