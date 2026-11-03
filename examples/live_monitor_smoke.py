"""Live public SEC CLI acceptance rehearsal. Requires a real SEC_USER_AGENT.

Uses a persistent operator-selected SQLite path; never embeds or exports identity.
"""
import argparse
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
from filing_intel.cli import main
from filing_intel.store import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--db', required=True)
parser.add_argument('--since', required=True)
parser.add_argument('--to', required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()
db = Path(args.db)
def invoke(*args):
    output = StringIO()
    with redirect_stdout(output):
        result = main([*args, '--db', str(db)])
    parsed = json.loads(output.getvalue()) if output.getvalue().strip() else None
    return result, parsed

code, _ = invoke('watchlist', 'add', '--company', '320193', '--name', 'Apple Inc.')
assert code == 0
code, first = invoke('scan', '--since', args.since, '--to', args.to)
print(json.dumps({'phase': 'first_live_scan', 'exit_code': code, 'summary': first}), flush=True)
if code:
    raise SystemExit(code)
assert first['processed'] > first['first_seen'], 'The interval must include a comparable annual filing'
_, first_results = invoke('results')
with Store(db) as store:
    documents_before = [tuple(r) for r in store.conn.execute('SELECT accession,content_sha256 FROM documents ORDER BY accession')]
    assert len(documents_before) >= 2
    for row in store.conn.execute('SELECT raw_content,content_sha256 FROM documents'):
        assert hashlib.sha256(row['raw_content']).hexdigest() == row['content_sha256']
    spans = 0
    for event in first_results['events']:
        for side in ('old', 'new'):
            span = event['evidence'][side]
            if span:
                parsed = store.conn.execute('SELECT normalized_text FROM parses WHERE cik=? AND accession=? AND parser_version=?',
                        (320193, span['accession'], span['parser_version'])).fetchone()[0]
                assert parsed[span['start_offset']:span['end_offset']] == span['quote']
                spans += 1
code, second = invoke('scan', '--since', args.since, '--to', args.to)
print(json.dumps({'phase': 'live_replay', 'exit_code': code, 'summary': second}), flush=True)
if code:
    raise SystemExit(code)
_, second_results = invoke('results')
assert first_results['events'] == second_results['events']
with Store(db) as store:
    documents_after = [tuple(r) for r in store.conn.execute('SELECT accession,content_sha256 FROM documents ORDER BY accession')]
    assert documents_before == documents_after
    assert store.conn.execute('SELECT count(*) FROM attempts WHERE run_id=? AND stage=?', (second['run_id'], 'fetch')).fetchone()[0] == 0
    report = {'issuer_cik':'0000320193', 'window_start':args.since, 'window_end':args.to,
              'first_run':first,'replay_run':second, 'events':len(first_results['events']),
              'verified_normalized_spans':spans, 'idempotent_events':True, 'unchanged_document_hashes':True,
              'replay_document_fetches':0,
              'documents':[dict(r) for r in store.conn.execute('SELECT f.accession,f.source_url,f.filed,f.period_end,d.content_sha256 FROM filings f JOIN documents d USING(cik,accession) ORDER BY f.filed')],
              'comparisons':[dict(r) for r in store.conn.execute('SELECT accession,baseline_accession,baseline_reason,status FROM comparisons WHERE active=1')]}
Path(args.out).write_text(json.dumps(report,indent=2))
print(json.dumps(report), flush=True)
