"""Derive recovery scenarios from an exported action history (JSONL).

Accepted line shapes (AFR-compatible):
- Flight Recorder / AgentBridge event shape:
  {"event_id": ..., "agent_id": ..., "event_type": "tool.call.started"|"tool.call.completed"|...,
   "summary": ..., "timestamp": ..., "action_id": ... (optional)}
- AFR ingest shape:
  {"agent_id": ..., "action_type": ..., "tool_name": ..., "status": "started"|"completed"|...,
   "timestamp": ..., "action_id"/"idempotency_key": ... (optional)}
- Real AFR stored/exported record shape (from AFR source, app/main.py —
  records returned by GET /v1/actions):
  {"seq": ..., "created_at": ..., "action_type": ..., "tool_name": ...,
   "input_summary": ..., "output_summary": ..., "metadata": {...}, "prev_hash": ..., "hash": ...}
  Lifecycle is encoded in action_type/tool_name/metadata: e.g. a
  `gateway_decision` record and its `refund_outcome` record share
  `metadata.request_id`; a decision with no outcome record for its
  request_id derives an uncertain-outcome scenario.

Derivation rules (see OVERLAP-GATE.md). A history with no derivable anomaly
derives ZERO scenarios and says so — passes are never invented.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .gateway import FakeGateway
from .runner import WorkflowRunner


def load_history(path):
    events = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{lineno}: each line must be a JSON object")
        events.append(obj)
    return events


def _meta(ev):
    m = ev.get("metadata")
    return m if isinstance(m, dict) else {}


def _kind(ev):
    raw = " ".join(str(ev.get(k) or "") for k in ("event_type", "status", "action_type", "tool_name")).lower()
    if "webhook" in raw:
        return "webhook"
    if any(t in raw for t in ("timeout", "timed_out", "timed-out")):
        return "timeout"
    if any(t in raw for t in ("start", "initiat", "pending")):
        return "started"
    if any(t in raw for t in ("complet", "succeed", "success", "applied", "done")):
        return "completed"
    if any(t in raw for t in ("fail", "error")):
        return "failed"
    return "other"


def _action_key(ev):
    m = _meta(ev)
    return str(ev.get("action_id") or ev.get("correlation_id") or ev.get("idempotency_key")
               or ev.get("request_id")
               or m.get("action_id") or m.get("correlation_id") or m.get("idempotency_key")
               or m.get("request_id")
               or ev.get("event_id") or ev.get("id") or "")


def _action_name(ev):
    return str(ev.get("action_type") or ev.get("tool_name") or ev.get("event_type") or "recorded.action")


def derive(events):
    """Return a list of derived-scenario descriptors (no execution yet)."""
    derived = []
    ids = Counter(str(e.get("event_id") or e.get("id")) for e in events
                  if (e.get("event_id") or e.get("id")))
    for eid, count in ids.items():
        if count > 1:
            kinds = {_kind(e) for e in events if str(e.get("event_id") or e.get("id")) == eid}
            name = "repeated-webhook" if "webhook" in kinds else "duplicate-event"
            derived.append({"name": name, "derived_from": f"event {eid} recorded {count}x",
                            "event_id": eid, "action": _action_name(
                                next(e for e in events if str(e.get("event_id") or e.get("id")) == eid))})
    keys = Counter(str(e["idempotency_key"]) for e in events if e.get("idempotency_key"))
    for key, count in keys.items():
        if count > 1 and not any(d["name"] == "duplicate-event" and key in d["derived_from"] for d in derived):
            derived.append({"name": "duplicate-event", "derived_from": f"idempotency_key {key} recorded {count}x",
                            "event_id": key, "action": _action_name(
                                next(e for e in events if str(e.get("idempotency_key")) == key))})
    by_action = {}
    for e in events:
        by_action.setdefault(_action_key(e), []).append(e)
    for akey, group in by_action.items():
        if not akey:
            continue
        kinds = {_kind(e) for e in group}
        if "timeout" in kinds:
            derived.append({"name": "timeout", "derived_from": f"action {akey} recorded a timeout",
                            "event_id": akey, "action": _action_name(group[0])})
        elif "started" in kinds and not ({"completed", "failed"} & kinds):
            if not any(d["derived_from"].endswith(akey) for d in derived):
                derived.append({"name": "uncertain-outcome",
                                "derived_from": f"action {akey} started but never completed",
                                "event_id": akey, "action": _action_name(group[0])})
    # AFR decision/outcome pairing (real AFR pattern: a `gateway_decision`
    # record and its `refund_outcome` record share a request_id — see AFR's
    # own test_mvcp_coverage). A decision/initiation carrying a request_id
    # with NO outcome record for that id is an uncertain outcome.
    by_request = {}
    for e in events:
        rid = str(e.get("request_id") or _meta(e).get("request_id") or "")
        if rid:
            by_request.setdefault(rid, []).append(e)
    for rid, group in by_request.items():
        types = " ".join(str(e.get("action_type") or "") for e in group).lower()
        initiated = any(t in types for t in ("decision", "started", "initiated"))
        resolved = any(t in types for t in ("outcome", "complet", "succeed", "success", "fail"))
        if initiated and not resolved and not any(
                d["name"] == "uncertain-outcome" and rid in d["derived_from"] for d in derived):
            derived.append({"name": "uncertain-outcome",
                            "derived_from": f"request {rid} has a decision/initiation record but no outcome record",
                            "event_id": rid, "action": _action_name(group[0])})
    return derived


def run_derived(events):
    """Execute each derived scenario against a fresh isolated harness."""
    results = []
    for d in derive(events):
        gw = FakeGateway()
        r = WorkflowRunner(gw)
        action = d["action"]
        if d["name"] == "uncertain-outcome":
            from .gateway import ResponseLost
            key = f"hist:{d['event_id']}"
            try:
                gw.apply_then_lose_response(key, action)
            except ResponseLost:
                pass
            found = gw.lookup(key)
            passed = found is not None and gw.effect_count(action) == 1
            detail = "History showed a started-but-never-completed action; harness reconciled it to exactly one effect."
        elif d["name"] == "timeout":
            from .gateway import ResponseLost
            key = f"hist:{d['event_id']}"
            try:
                gw.apply_then_lose_response(key, action)
            except ResponseLost:
                pass
            found = gw.lookup(key)
            passed = found is not None and gw.effect_count(action) == 1
            detail = "History recorded a timeout; harness reconciled instead of blind-retrying."
        else:  # duplicate-event / repeated-webhook
            r.deliver_event(d["event_id"], action)
            r.deliver_event(d["event_id"], action)
            r.deliver_event(d["event_id"], action)
            passed = gw.effect_count(action) == 1
            detail = "History recorded the same event more than once; harness applied it exactly once."
        results.append({
            "name": d["name"], "passed": passed, "derived": True,
            "derived_from": d["derived_from"],
            "property": f"History-derived {d['name']} scenario holds its safety property.",
            "checks": {"safety_property_held": passed},
            "side_effects": gw.effect_count(), "detail": detail,
        })
    return results
