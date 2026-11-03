"""Streamlit portfolio demo for SEC Filing Intelligence.

Run: pip install -e '.[ui]'; streamlit run app.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from filing_intel.ai import interpret_changes
from filing_intel.cli import ROOT, sample_pair
from filing_intel.detect import compare
from filing_intel.evaluate import evaluate
from filing_intel.models import Filing
from filing_intel.reporting import to_markdown
from filing_intel.sec import SecClient

st.set_page_config(page_title="SEC Filing Intelligence", page_icon="📑", layout="wide")

# Default to the real persisted fund-and-stock dashboard.
# The original working 10-K comparison demo remains available via this toggle.
if st.sidebar.toggle("Fund + stock intelligence dashboard",value=True):
    from filing_intel.intel_dashboard import render
    render()
    st.stop()

st.markdown("""
<style>
.block-container {max-width: 1120px; padding-top: 2.2rem;}
h1,h2,h3 {letter-spacing: -0.035em;}
.caption-label {font-size:.77rem; letter-spacing:.10em; text-transform:uppercase; color:#64748b; font-weight:700;}
.hero-subtitle {font-size:1.05rem; color:#64748b; margin-bottom:1.5rem;}
.evidence {background:#f4f7fb;border-left:3px solid #4385bd;padding:.9rem 1rem;border-radius:.15rem;white-space:pre-wrap;overflow-wrap:anywhere;}
@media (prefers-color-scheme: dark) { .evidence {background:#132132;} }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="caption-label">Open-source product prototype · Public SEC data</div>', unsafe_allow_html=True)
st.title("SEC Filing Intelligence")
st.markdown('<div class="hero-subtitle">Detect meaningful disclosure wording changes. Inspect exact evidence. Measure failure modes.</div>', unsafe_allow_html=True)

mode = st.radio("Data source", ["Synthetic demo", "Live SEC filings", "Compare your own text"], horizontal=True)
with st.sidebar:
    st.subheader("Controls")
    max_changes = st.slider("Max findings", min_value=5, max_value=50, value=15, step=5)
    use_ai = st.toggle("Optional AI interpretation", value=False,
                       help="Adds LLM-generated commentary to deterministic evidence-based findings. Requires OpenAI API key.")
    if use_ai:
        api_key = st.text_input("OpenAI API key", value=os.getenv("OPENAI_API_KEY", ""), type="password")
        model = st.text_input("Model", value=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    else:
        api_key = ""
        model = None
    st.divider()
    st.caption("Attention tiers are keyword heuristics, not materiality assessments. The demo data is fictional.")

try:
    before = after = None
    if mode == "Synthetic demo":
        before, after = sample_pair()
        st.info("This demonstration uses invented issuer disclosures. No employer materials or customer data.")
    elif mode == "Live SEC filings":
        left, right = st.columns([1, 2])
        with left:
            company = st.text_input("Ticker or CIK", "AAPL")
        with right:
            sec_agent = st.text_input("SEC User-Agent (name + contact email)",
                                      value=os.getenv("SEC_USER_AGENT", ""),
                                      placeholder="Your Name contact@yourdomain.com")
        st.caption("Fetches the latest two Form 10-K filings and compares Item 1A. Live extraction is experimental.")
        if st.button("Fetch and compare 10-Ks", type="primary"):
            with st.spinner("Fetching filings from SEC EDGAR ..."):
                before, after = SecClient(user_agent=sec_agent).fetch_latest_pair(company)
    else:
        st.caption("Paste only Item 1A risk-factor section text. Do not paste private or employer-confidential information.")
        c1, c2 = st.columns(2)
        with c1:
            old_text = st.text_area("Prior disclosure", height=220)
            old_url = st.text_input("Previous source URL (optional)")
        with c2:
            new_text = st.text_area("Current disclosure", height=220)
            new_url = st.text_input("Current source URL (optional)")
        if st.button("Compare disclosures", type="primary"):
            before = Filing("User-provided comparison", "10-K", "previous", old_url or "source not supplied", old_text)
            after = Filing("User-provided comparison", "10-K", "current", new_url or "source not supplied", new_text)

    if before and after:
        report = compare(before, after, max_changes=max_changes)
        if use_ai:
            with st.spinner("Generating optional, evidence-checked AI interpretations ..."):
                interpret_changes(report, api_key=api_key, model=model)
        summary, findings, methodology = st.tabs(["Findings", "Evaluation", "How it works"])
        with summary:
            st.subheader(report.company)
            st.caption(f"{report.old_date}  →  {report.new_date}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Candidates", len(report.changes))
            m2.metric("Added", report.counts["added"])
            m3.metric("Revised", report.counts["revised"])
            m4.metric("Removed", report.counts["removed"])
            st.caption("Evidence links open at the filing level. Use the quoted text to locate the passage within a filing.")
            if not report.changes:
                st.success("No candidate wording changes found under the current matching thresholds.")
            for i, c in enumerate(report.changes, 1):
                with st.expander(f"{i:02d}  |  {c.change_type.upper()}  |  {c.attention.upper()} attention", expanded=(i <= 2)):
                    st.write(c.rationale)
                    if c.old_quote:
                        st.markdown("**Previous text**")
                        st.code(c.old_quote, language=None, wrap_lines=True)
                        if c.old_url.startswith("https://"):
                            st.link_button("Open prior filing", c.old_url)
                    if c.new_quote:
                        st.markdown("**Current text**")
                        st.code(c.new_quote, language=None, wrap_lines=True)
                        if c.new_url.startswith("https://"):
                            st.link_button("Open current filing", c.new_url)
                    if c.ai_interpretation:
                        st.markdown("**AI interpretation (requires human review)**")
                        st.write(c.ai_interpretation)
            for warning in report.warnings:
                st.caption("Note: " + warning)
            st.download_button("Download evidence report (.md)", to_markdown(report),
                               file_name="filing_change_report.md", mime="text/markdown")
            st.download_button("Download structured findings (.json)",
                               json.dumps(report.to_dict(), indent=2),
                               file_name="filing_change_report.json", mime="application/json")
        with findings:
            result = evaluate(ROOT / "examples" / "evaluation_cases.json")
            e1, e2, e3 = st.columns(3)
            e1.metric("Precision", f"{result['precision']:.0%}")
            e2.metric("Recall", f"{result['recall']:.0%}")
            e3.metric("F1", f"{result['f1']:.0%}")
            st.warning("Synthetic regression fixtures only. These numbers do not measure real SEC filing accuracy.")
            st.dataframe(result["details"], hide_index=True, use_container_width=True)
        with methodology:
            st.markdown("""
**Workflow:** SEC filings → Item 1A extraction → paragraph/sentence segmentation → one-to-one
similarity alignment → candidate change classification → verbatim evidence verification → reviewer.

**Limitations:** Reordering, repeated boilerplate, unusual filing HTML, and paraphrases may create
false positives or misses. Attention tiers are not materiality judgments. There are no claims of
production-grade performance. Optional AI commentary is not source evidence.
""")
except Exception as exc:
    st.error(f"Could not complete comparison: {exc}")
    st.caption("If SEC denies access, check your user-agent and try the self-contained synthetic demo.")
