"""Keep presentation fixtures honest and evidence internally reproducible."""
import json
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / 'docs' / 'index.html'

def test_demo_evidence_and_scope():
    html = PAGE.read_text()
    match = re.search(r'<script id="demo-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, 'The offline demo must embed its fixture data'
    data = json.loads(match.group(1))
    assert data['synthetic'] is True
    assert data['scope'] == {'stock_target': 500, 'fund_target': 50, 'live_verified': 0}
    assert {e['track'] for e in data['events']} == {'stock', 'fund'}
    assert len({e['id'] for e in data['events']}) == len(data['events'])
    for event in data['events']:
        for side in ['before', 'after']:
            evidence = event[side]
            doc = data['documents'][evidence['document']]
            assert doc['synthetic'] is True
            assert doc['text'][evidence['start']:evidence['end']] == evidence['quote']
            assert not doc.get('accession'), 'Never invent an SEC accession'
    assert 'Real SEC F1' in html and 'Not measured' in html
    assert 'Illustrative pipeline' in html
    assert 'Start 3-minute tour' in html
