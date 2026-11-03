import pytest

from filing_intel.sec import SecClient


class DummyResponse:
    status_code = 200

    def __init__(self, payload, as_text=False):
        self.payload = payload
        self.text = payload if as_text else ""
        self.content = self.text.encode()

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class DummySession:
    def __init__(self, data):
        self.data = data
        self.headers = {}
        self.requested = []

    def get(self, url, timeout):
        self.requested.append(url)
        return self.data[url]


def test_cik_pair_from_official_sec_routes():
    old_doc = "Old risks to our cloud systems can affect market demand and retention. " * 12
    new_doc = "New cyber threats can affect data confidentiality, revenue, and operations. " * 12

    def html(section):
        return f"<html><body><p>Item 1A. Risk Factors</p><p>{section}</p><p>Item 1B. Comments</p></body></html>"

    base = "https://www.sec.gov/Archives/edgar/data/320193/"
    urls = {
        "https://data.sec.gov/submissions/CIK0000320193.json": DummyResponse({
            "name": "Example SEC Issuer", "filings": {"recent": {
                "form": ["10-K", "10-K", "8-K"],
                "accessionNumber": ["0000320193-25-000001", "0000320193-24-000001", "0000320193-25-000002"],
                "filingDate": ["2025-10-01", "2024-10-01", "2025-11-01"],
                "primaryDocument": ["current.htm", "prior.htm", "event.htm"]}}}),
        base + "000032019325000001/current.htm": DummyResponse(html(new_doc), as_text=True),
        base + "000032019324000001/prior.htm": DummyResponse(html(old_doc), as_text=True),
    }
    session = DummySession(urls)
    client = SecClient(user_agent="Example Research research@somewhere.org", session=session)
    before, after = client.fetch_latest_pair("320193")
    assert "Old risks" in before.text
    assert "New cyber threats" in after.text
    assert before.filing_date == "2024-10-01"
    assert after.filing_date == "2025-10-01"
    assert len(session.requested) == 3
    assert all(url.startswith("https://") for url in session.requested)


def test_user_agent_is_required():
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        SecClient(user_agent="bot")


def test_ticker_resolver():
    url = "https://www.sec.gov/files/company_tickers.json"
    session = DummySession({url: DummyResponse({"0":{"ticker":"AAPL","cik_str":320193}})})
    client = SecClient(user_agent="Research Admin research@somewhere.org", session=session)
    assert client.resolve_cik("aapl") == 320193


def test_invalid_ticker_fails():
    client = SecClient(user_agent="Research Admin research@somewhere.org")
    with pytest.raises(ValueError, match="ticker"):
        client.resolve_cik("../../secrets")
