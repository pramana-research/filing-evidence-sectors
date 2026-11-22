"""Download the benchmark's filings from SEC EDGAR (PROTOCOL.md §3.2) and write the source manifest.

For each company in companies.yaml: the most recent 10-K and 10-Q filed on or before the cutoff. Saves
  - every inline-XBRL document of the filing, as listed in its FilingSummary.xml (most filings have one;
    Wells Fargo's 10-K has two: the 10-K wrapper and the annual report with the financial statements);
  - the labels: the *_lab.xml linkbase, or the .xsd schema when the labels are embedded there;
  - FilingSummary.xml itself,
under <DATA_DIR>/finance/filings/<TICKER>/<accession>/, and records every file's URL and sha256 in
dataset/manifest.json (committed to the repo).

Polite: identifying User-Agent (SEC_USER_AGENT), at most 5 requests per second, each file fetched once.

    uv run python fetch.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from edgar import EdgarClient
from paths import data_dir

HERE = Path(__file__).parent
SOURCE = "SEC EDGAR (sec.gov/Archives), public records"


def latest(recent: dict, form: str, cutoff: str) -> dict | None:
    """Most recent filing of `form` filed on or before `cutoff`, from a submissions 'recent' block."""
    best = None
    for i, f in enumerate(recent["form"]):
        if f == form and recent["filingDate"][i] <= cutoff:
            cand = {"form": f, "accession": recent["accessionNumber"][i], "filed": recent["filingDate"][i],
                    "report_date": recent["reportDate"][i], "primary_document": recent["primaryDocument"][i]}
            if best is None or cand["filed"] > best["filed"]:
                best = cand
    return best


def ixbrl_documents(filing_summary: str) -> list[str]:
    """The inline-XBRL documents of a filing: <File doctype="..."> entries ending in .htm."""
    return [n for attrs, n in re.findall(r"<File([^>]*)>([^<]+)</File>", filing_summary)
            if n.endswith(".htm") and "doctype=" in attrs]


def label_file(names: list[str]) -> str | None:
    """The label linkbase, or the schema when labels are embedded in it."""
    for suffix in ("_lab.xml", ".xsd"):
        found = sorted(n for n in names if n.endswith(suffix))
        if found:
            return found[0]
    return None


def fetch_file(client: EdgarClient, cik: int, accession: str, folder: Path, name: str) -> dict:
    """Download one file once (kept if already present) and describe it for the manifest."""
    path = folder / name
    if not path.exists():
        path.write_bytes(client.filing_file(cik, accession, name))
    data = path.read_bytes()
    return {"name": name, "url": client.archive_url(cik, accession, name),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main() -> int:
    load_dotenv(HERE / ".env")
    spec = yaml.safe_load((HERE / "companies.yaml").read_text())
    cutoff = spec["filed_on_or_before"]
    client = EdgarClient(cache_dir=data_dir() / "finance" / "raw", min_interval=0.2)   # <= 5 req/s
    ciks = client.ticker_to_cik()
    root = data_dir() / "finance" / "filings"
    manifest, problems = [], []

    for group, tickers in spec["groups"].items():
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
                files = {"filing_summary": summary,
                         "documents": [fetch_file(client, cik, acc, folder, n) for n in docs],
                         "labels": fetch_file(client, cik, acc, folder, labels) if labels else None}
                manifest.append({"ticker": t, "group": group, "cik": cik, "company": sub.get("name"),
                                 **fil, "files": files})
                kb = sum(d["bytes"] for d in files["documents"]) // 1024
                print(f"{t:5s} {form:5s} {acc}  {len(docs)} doc(s) {kb:>6d} KB  labels={labels}")

    out = {"created": datetime.now(UTC).isoformat(timespec="seconds"), "cutoff": cutoff, "source": SOURCE,
           "filings": manifest, "problems": problems}
    (HERE / "dataset" / "manifest.json").write_text(json.dumps(out, indent=2))
    print(f"\n{len(manifest)} filings; problems: {problems or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
