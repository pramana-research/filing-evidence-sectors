"""Download the sectors set's filings from SEC EDGAR (PROTOCOL.md §4.2) and write its source manifest.

Same rules and code as the v1 downloader (../../fetch.py): for each company in companies.yaml, the most
recent 10-K and 10-Q filed on or before the cutoff; every inline-XBRL document listed in FilingSummary.xml,
the label linkbase (or the schema), and FilingSummary.xml itself, under
<DATA_DIR>/finance/filings/<TICKER>/<accession>/. Files already present (e.g. filings shared with v1) are
kept, not downloaded again. Every file's URL and sha256 goes to sets/sectors/dataset/manifest.json. A company
whose filings fail is reported, not replaced: replacements follow PROTOCOL.md §4.2 and are logged in §14.

    uv run python sets/sectors/fetch.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from edgar import EdgarClient  # noqa: E402
from fetch import SOURCE, fetch_file, ixbrl_documents, label_file, latest  # noqa: E402
from paths import data_dir  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    spec = yaml.safe_load((HERE / "companies.yaml").read_text())
    cutoff = spec["filed_on_or_before"]
    cache = data_dir() / "finance" / "raw-sectors"  # fresh submissions (v1's cache is from 2026-11-15)
    client = EdgarClient(cache_dir=cache, min_interval=0.2)  # <= 5 requests per second
    ciks = client.ticker_to_cik()
    root = data_dir() / "finance" / "filings"
    manifest, problems = [], []

    for sector, tickers in spec["sectors"].items():
        for t in tickers:
            cik = ciks[t]
            sub = client.submissions(cik)
            for form in spec["forms"]:
                fil = latest(sub["filings"]["recent"], form, cutoff)
                if fil is None:
                    problems.append(f"{t}: no {form} on or before {cutoff}")
                    continue
                acc = fil["accession"]
                folder = root / t / acc
                folder.mkdir(parents=True, exist_ok=True)
                names = [it["name"] for it in client.filing_index(cik, acc)["directory"]["item"]]
                summary = fetch_file(client, cik, acc, folder, "FilingSummary.xml")
                summary_text = (folder / "FilingSummary.xml").read_text(encoding="utf-8", errors="replace")
                docs = ixbrl_documents(summary_text)
                labels = label_file(names)
                if not docs:
                    problems.append(f"{t} {form} {acc}: no inline-XBRL documents listed in FilingSummary.xml")
                if not labels:
                    problems.append(f"{t} {form} {acc}: no label linkbase or schema")
                files = {
                    "filing_summary": summary,
                    "documents": [fetch_file(client, cik, acc, folder, n) for n in docs],
                    "labels": fetch_file(client, cik, acc, folder, labels) if labels else None,
                }
                entry = {"ticker": t, "sector": sector, "cik": cik, "company": sub.get("name")}
                manifest.append({**entry, **fil, "files": files})
                kb = sum(d["bytes"] for d in files["documents"]) // 1024
                print(f"{t:5s} {form:5s} {acc}  {len(docs)} doc(s) {kb:>6d} KB  labels={labels}", flush=True)

    out = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "cutoff": cutoff,
        "source": SOURCE,
        "filings": manifest,
        "problems": problems,
    }
    (HERE / "dataset").mkdir(exist_ok=True)
    (HERE / "dataset" / "manifest.json").write_text(json.dumps(out, indent=2))
    print(f"\n{len(manifest)} filings; problems: {problems or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
