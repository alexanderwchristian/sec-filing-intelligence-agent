"""Operator-run live SEC acceptance check for BOTH fund and stock filings.

Requires official CIKs, a real contactable SEC_USER_AGENT, and network access.
Never hardcode private keys or email into the repository. Real-world category
accuracy still requires manual labeling and review.
"""
from __future__ import annotations

import argparse
from datetime import date,timedelta
import json
import sys

from filing_intel.intel_store import IntelStore
from filing_intel.intel_monitor import scan_intelligence
from filing_intel.intel_evaluation import verify_grounding
from filing_intel.sec import SecClient


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--stock-cik",type=int,required=True)
    p.add_argument("--fund-cik",type=int,required=True)
    p.add_argument("--stock-name",default="Public stock issuer")
    p.add_argument("--fund-name",required=True)
    p.add_argument("--series-id")
    p.add_argument("--class-id")
    p.add_argument("--since",default=(date.today()-timedelta(days=365)).isoformat())
    p.add_argument("--to",default=date.today().isoformat())
    p.add_argument("--db",default=".filing-intel/live-dual-acceptance.sqlite3")
    args=p.parse_args(argv)
    with IntelStore(args.db) as store:
        sw=store.add_watch("stock",args.stock_cik,args.stock_name)
        fw=store.add_watch("fund",args.fund_cik,args.fund_name,
                           series_id=args.series_id,class_id=args.class_id)
        result=scan_intelligence(store,SecClient(),since=args.since,until=args.to,
                                 mode="on_demand")
        docs={w:store.filings(w,limit=1000) for w in (sw,fw)}
        events=store.events()
        grounding=verify_grounding(store,events)
        report={"run":result,"documents":{"stock":len(docs[sw]),"fund":len(docs[fw])},
                "events":{"stock":len([e for e in events if e["kind"]=="stock"]),
                          "fund":len([e for e in events if e["kind"]=="fund"])},
                "source_grounding":grounding,
                "fund_identity_statuses":sorted(set(e["identity_status"] for e in events
                                                    if e["kind"]=="fund")),
                "forms":{"stock":sorted(set(f["form"] for f in docs[sw])),
                         "fund":sorted(set(f["form"] for f in docs[fw]))},
                "source_urls":{"stock":[f["source_url"] for f in docs[sw]][:5],
                               "fund":[f["source_url"] for f in docs[fw]][:5]},
                "note":"Operational smoke only; no claims of labeled recall, precision or financial materiality."}
        print(json.dumps(report,indent=2))
        if result["status"]!="completed" or not all(len(docs[w]) for w in (sw,fw)):
            return 2
        if grounding["failures"]:
            return 2
        return 0


if __name__=="__main__":
    sys.exit(main())
