"""Download SEC EDGAR data: ticker->CIK map, XBRL company facts, submissions, filing documents.

SEC rules: send a descriptive User-Agent with contact info, and stay under 10 requests/second.
https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{name}"

_MIN_INTERVAL = 0.15  # ~6-7 req/s, safely under the SEC limit


class EdgarClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path | None = None,
                 min_interval: float = _MIN_INTERVAL):
        ua = user_agent or os.environ.get("SEC_USER_AGENT")
        if not ua or "@" not in ua:
            raise ValueError("Set SEC_USER_AGENT to 'Company Name email@domain' (SEC requirement)")
        self._http = httpx.Client(headers={"User-Agent": ua}, timeout=60, follow_redirects=True)
        self._last = 0.0
        self.min_interval = min_interval
        self.cache_dir = cache_dir

    def _get(self, url: str) -> httpx.Response:
        """One polite GET: paced to min_interval, backing off on 429/503."""
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self._http.get(url)
            self._last = time.monotonic()
            if resp.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"SEC kept throttling: {url}")

    def _get_json(self, url: str, cache_name: str | None = None) -> dict:
        if self.cache_dir and cache_name:
            cached = self.cache_dir / cache_name
            if cached.exists():
                return json.loads(cached.read_text())
        data = self._get(url).json()
        if self.cache_dir and cache_name:
            (self.cache_dir / cache_name).parent.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / cache_name).write_text(json.dumps(data))
        return data

    def archive_url(self, cik: int, accn: str, name: str) -> str:
        return ARCHIVE_URL.format(cik=cik, accn_nodash=accn.replace("-", ""), name=name)

    def filing_index(self, cik: int, accn: str) -> dict:
        """The file listing of one filing (index.json in its archive folder)."""
        return self._get_json(self.archive_url(cik, accn, "index.json"),
                              f"filings/{cik}/{accn}/index.json")

    def filing_file(self, cik: int, accn: str, name: str) -> bytes:
        """Raw bytes of one file in a filing (e.g. the primary 10-K document); not cached here."""
        return self._get(self.archive_url(cik, accn, name)).content

    def ticker_to_cik(self) -> dict[str, int]:
        raw = self._get_json(TICKERS_URL, "company_tickers.json")
        return {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}

    def company_facts(self, cik: int) -> dict:
        return self._get_json(FACTS_URL.format(cik=cik), f"facts/CIK{cik:010d}.json")

    def submissions(self, cik: int) -> dict:
        return self._get_json(SUBMISSIONS_URL.format(cik=cik), f"submissions/CIK{cik:010d}.json")
