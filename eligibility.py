"""Check every company of the sectors set against PROTOCOL.md §4.2, before anything is built.

    uv run python eligibility.py

A company is eligible when SEC EDGAR lists a 10-K and a 10-Q filed on or before the cutoff, both flagged as
inline XBRL, and recent enough to be current (10-K period within 15 months of the cutoff, 10-Q within 6).
Reads only the SEC submissions API (one request per company, identifying User-Agent, at most 5 per second);
downloads no filings.

Writes eligibility.json: per company, the filings found and the reason if ineligible; per sector,
the final list after replacing ineligible companies with reserves in order.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE
sys.path.insert(0, str(HERE / "v1"))  # v1 modules, frozen copies
from edgar import EdgarClient  # noqa: E402

MAX_AGE_DAYS = {"10-K": 456, "10-Q": 183}


def latest(recent: dict, form: str, cutoff: str) -> dict | None:
    """Most recent filing of `form` filed on or before `cutoff` (fetch.latest, plus the inline-XBRL flag)."""
    best = None
    for i, f in enumerate(recent["form"]):
        if f == form and recent["filingDate"][i] <= cutoff:
            cand = {
                "accession": recent["accessionNumber"][i],
                "filed": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "primary_document": recent["primaryDocument"][i],
                "inline_xbrl": bool(recent.get("isInlineXBRL", [0] * len(recent["form"]))[i]),
            }
            if best is None or cand["filed"] > best["filed"]:
                best = cand
    return best


def check(client: EdgarClient, ciks: dict[str, int], ticker: str, spec: dict) -> dict:
    cutoff = spec["filed_on_or_before"]
    out = {"ticker": ticker, "cik": ciks.get(ticker), "filings": {}, "problems": [], "eligible": False}
    if not out["cik"]:
        out["problems"].append("ticker not in the SEC ticker map")
        return out
    sub = client.submissions(out["cik"])
    out["name"] = sub.get("name")
    for form in spec["forms"]:
        f = latest(sub["filings"]["recent"], form, cutoff)
        if f is None:
            out["problems"].append(f"no {form} filed on or before {cutoff}")
            continue
        out["filings"][form] = f
        if not f["inline_xbrl"]:
            out["problems"].append(f"{form} {f['accession']} is not inline XBRL")
        if f["report_date"]:
            age = (date.fromisoformat(cutoff) - date.fromisoformat(f["report_date"])).days
            if age > MAX_AGE_DAYS[form]:
                out["problems"].append(f"latest {form} is stale (period ended {f['report_date']})")
    out["eligible"] = not out["problems"]
    return out


def main() -> int:
    load_dotenv(ROOT / ".env")
    spec = yaml.safe_load((HERE / "companies.yaml").read_text())
    client = EdgarClient(min_interval=0.2)  # fresh data (no cache), <= 5 requests per second
    ciks = client.ticker_to_cik()
    results, final = {}, {}
    for sector, tickers in spec["sectors"].items():
        reserves = list(spec["reserves"].get(sector, []))
        chosen = []
        for t in tickers + reserves:
            results[t] = check(client, ciks, t, spec)
        for t in tickers:
            if results[t]["eligible"]:
                chosen.append(t)
        replacements = []
        for r in reserves:
            if len(chosen) >= len(tickers):
                break
            if results[r]["eligible"]:
                chosen.append(r)
                replacements.append(r)
        final[sector] = {
            "companies": chosen,
            "ineligible": [t for t in tickers if not results[t]["eligible"]],
            "replacements": replacements,
            "short_by": max(0, len(tickers) - len(chosen)),
        }
    out = {
        "cutoff": spec["filed_on_or_before"],
        "checked": date.today().isoformat(),
        "sectors": final,
        "companies": results,
    }
    (HERE / "eligibility.json").write_text(json.dumps(out, indent=2) + "\n")
    for sector, f in final.items():
        bad = ", ".join(f"{t} ({'; '.join(results[t]['problems'])})" for t in f["ineligible"]) or "none"
        print(
            f"{sector}: {len(f['companies'])}/10 · ineligible: {bad}"
            + f" · replacements: {f['replacements'] or 'none'}"
            + (f" · SHORT BY {f['short_by']}" if f["short_by"] else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
