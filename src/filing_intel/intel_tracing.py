"""Opt-in OpenAI Agents SDK spans. No key or raw SEC text is placed in span metadata.

Normal offline runs do not import the Agents SDK. A traced live run must
explicitly set ENABLE_OPENAI_TRACING=1 and install the 'tracing' extra.
"""
from __future__ import annotations

from contextlib import contextmanager
import os


def enabled() -> bool:
    return os.getenv("ENABLE_OPENAI_TRACING", "0") == "1"


@contextmanager
def workflow(name: str, metadata: dict | None = None):
    if not enabled():
        yield
        return
    try:
        from agents import trace
    except ImportError as exc:
        raise RuntimeError("Tracing enabled but openai-agents is not installed") from exc
    with trace(name, metadata=metadata or {}):
        yield


@contextmanager
def step_span(name: str, data: dict | None = None):
    if not enabled():
        yield
        return
    try:
        from agents import custom_span
    except ImportError as exc:
        raise RuntimeError("Tracing enabled but openai-agents is not installed") from exc
    # Metadata should contain only identifiers, phase names and small counters.
    with custom_span(name, data=data or {}):
        yield


def capture_response(response) -> None:
    """Attach a response ID and token counts without embedding the model's text."""
    if not enabled():
        return
    usage = getattr(response, "usage", None)
    data = {"response_id": getattr(response, "id", "") or ""}
    if usage:
        data["input_tokens"] = int(getattr(usage, "input_tokens", 0) or 0)
        data["output_tokens"] = int(getattr(usage, "output_tokens", 0) or 0)
    with step_span("openai_response_received", data):
        pass


def flush() -> None:
    if enabled():
        from agents import flush_traces
        flush_traces()
