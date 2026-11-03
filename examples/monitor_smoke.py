"""Offline CLI smoke rehearsal with fictional documents and mocked SEC transport.

Run: python examples/monitor_smoke.py
No network, SEC identity, API key or persistent user database is used.
"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from filing_intel.cli import main
from filing_intel.sec import SecClient

ROOT = Path(__file__).resolve().parent


class FixtureSession(requests.Session):
    def get(self, url, timeout):
        base = "https://www.sec.gov/Archives/edgar/data/1/"
        if url == "https://data.sec.gov/submissions/CIK0000000001.json":
            data = {"filings": {"recent": {
                "form": ["10-K", "10-K"],
                "accessionNumber": ["0000000001-25-000001", "0000000001-24-000001"],
                "filingDate": ["2025-02-01", "2024-02-01"],
                "primaryDocument": ["fictional.htm", "fictional.htm"],
                "reportDate": ["2024-12-31", "2023-12-31"]}, "files": []}}
            content = json.dumps(data)
        elif url in (base + "000000000125000001/fictional.htm", base + "000000000124000001/fictional.htm"):
            filename = "synthetic_after.txt" if "125000001" in url else "synthetic_before.txt"
            content = "Item 1A. Risk Factors " + (ROOT / filename).read_text() + " Item 1B. Comments"
        else:
            raise ValueError("Unexpected fixture URL; network is disabled")
        response = requests.Response()
        response.status_code = 200
        response._content = content.encode()
        response.encoding = "utf-8"
        return response


def invoke(db, *args):
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main([*args, "--db", db])
    if exit_code:
        raise RuntimeError(f"CLI smoke failed with exit code {exit_code}: {output.getvalue()}")
    return json.loads(output.getvalue())


def smoke():
    with TemporaryDirectory() as temp:
        db = str(Path(temp) / "state.sqlite3")
        client = SecClient("Offline Fixture fixture@invalid.test", session=FixtureSession())
        with patch("filing_intel.cli.SecClient", return_value=client):
            invoke(db, "watchlist", "add", "--company", "1", "--name", "Fictional Northstar issuer")
            first = invoke(db, "scan", "--since", "2025-01-01", "--to", "2025-12-31")
            events = invoke(db, "results")["events"]
            second = invoke(db, "backfill", "--from", "2025-01-01", "--to", "2025-12-31")
            replay = invoke(db, "results")["events"]
            status = invoke(db, "status")
        assert events and replay == events
        assert first["status"] == second["status"] == "completed"
        return {"fixture_kind": "fictional; mocked SEC transport; URLs are illustrative, not real filings",
                "first_run": first, "replay_run": second,
                "unique_events": len(events), "idempotent_replay": replay == events,
                "checkpoint": status["watchlist"][0]["checkpoint"], "events": events}


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))
