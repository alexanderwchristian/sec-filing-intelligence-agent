"""Minimal SEC EDGAR client, bounded and compliant with fair-access guidance."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .models import Filing
from .parser import extract_risk_section


@dataclass(frozen=True)
class FilingRecord:
    accession: str
    filed: str
    document: str
    form: str


class SecClient:
    """Public filings only. Uses a contactable user agent and max 2 requests/second."""

    def __init__(self, user_agent: str | None = None, *, session: requests.Session | None = None):
        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        # Require real identification, not the placeholder in .env.example.
        if ("@" not in self.user_agent or "example.com" in self.user_agent.lower()
                or len(self.user_agent.split()) < 2):
            raise ValueError("Set SEC_USER_AGENT to your name and a real contact email for SEC fair access")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json,text/html,*/*"})
        self.last_request_at = 0.0

    def _get(self, url: str) -> requests.Response:
        if not (url.startswith("https://data.sec.gov/")
                or url.startswith("https://www.sec.gov/")):
            raise ValueError("Only official SEC HTTPS URLs are permitted")
        for attempt in range(3):
            gap = 0.55 - (time.monotonic() - self.last_request_at)
            if gap > 0:
                time.sleep(gap)
            self.last_request_at = time.monotonic()
            try:
                response = self.session.get(url, timeout=25)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RuntimeError(f"SEC request failed: {exc}") from exc
                time.sleep(attempt + 1)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(min(5, 2 ** attempt))
                continue
            if response.status_code in (401, 403):
                raise RuntimeError("SEC blocked the request. Verify your SEC_USER_AGENT and retry later")
            response.raise_for_status()
            return response
        raise RuntimeError("SEC request failed after retries")

    def resolve_cik(self, identifier: str) -> int:
        identifier = identifier.strip()
        if identifier.isdigit():
            cik = int(identifier)
            if cik <= 0:
                raise ValueError("CIK must be positive")
            return cik
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", identifier):
            raise ValueError("Enter a numeric CIK or ticker, such as 320193 or AAPL")
        records = self._get("https://www.sec.gov/files/company_tickers.json").json()
        for record in records.values():
            if record["ticker"].upper() == identifier.upper():
                return int(record["cik_str"])
        raise ValueError(f"Could not resolve ticker '{identifier}' in the SEC ticker list")

    def _filings_from_data(self, data: dict, *, form: str) -> list[FilingRecord]:
        entries = data.get("filings", {}).get("recent", data)
        items: list[FilingRecord] = []
        for row in range(len(entries.get("form", []))):
            if entries["form"][row] == form:
                items.append(FilingRecord(entries["accessionNumber"][row],
                                          entries["filingDate"][row],
                                          entries["primaryDocument"][row], form))
        return items

    def fetch_latest_pair(self, identifier: str, *, form: str = "10-K") -> tuple[Filing, Filing]:
        """Return preceding and latest filing in chronological order."""
        if form != "10-K":
            raise ValueError("Prototype currently supports form 10-K only")
        cik = self.resolve_cik(identifier)
        data = self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        entries = self._filings_from_data(data, form=form)
        if len(entries) < 2:
            for older in data.get("filings", {}).get("files", []):
                url = f"https://data.sec.gov/submissions/{quote(older['name'], safe='')}"
                historical = self._get(url).json()
                entries.extend(self._filings_from_data(historical, form=form))
                if len(entries) >= 2:
                    break
        if len(entries) < 2:
            raise ValueError(f"Only {len(entries)} filings of form {form} available for {identifier}")
        entries.sort(key=lambda row: (row.filed, row.accession), reverse=True)
        name = data.get("name", identifier)

        def build(record: FilingRecord) -> Filing:
            # A real SEC archive URL, not a constructed third-party mirror.
            # URL quote protects anomalous document names from injection.
            acc = record.accession.replace("-", "")
            if not re.fullmatch(r"\d{18}", acc):
                raise ValueError("Unexpected SEC accession number")
            if "/" in record.document or "\\" in record.document or record.document.startswith("."):
                raise ValueError("Unexpected SEC primary-document path")
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
                   f"{quote(record.document, safe='')}" )
            response = self._get(url)
            if len(response.content) > 20_000_000:
                raise ValueError("Filing exceeds the 20 MB prototype size limit")
            section = extract_risk_section(response.text)
            return Filing(name, form, record.filed, url, section, record.accession)

        return build(entries[1]), build(entries[0])
