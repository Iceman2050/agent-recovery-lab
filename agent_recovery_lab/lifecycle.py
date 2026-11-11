"""Flight Recorder attempt lifecycle.

One business operation, N attempts, one stable operation ID.

Every lifecycle event is emitted in the real Agent Flight Recorder stored
record shape (see OVERLAP-GATE.md / history.py): ``seq``, ``created_at``,
``action_type``, ``tool_name``, ``metadata`` and a SHA-256 hash chain
(``prev_hash`` / ``hash``). The stable business-operation ID rides in
``metadata.request_id`` — AFR's own decision/outcome pairing convention
(a ``gateway_decision`` record and its ``refund_outcome`` record share a
``request_id``) — and also in ``metadata.operation_id``. The attempt
number for the operation rides in ``metadata.attempt``.

Lifecycle stages, in order: created -> authorized -> started -> result,
then per recovery attempt: retry -> reconciliation (and a further result
when the recovery attempt itself executes). An auditor groups the records
by operation ID and reads "one operation, N attempts" — see
``group_records`` / ``summary_line``. This module records evidence only;
it never executes an action.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

STAGES = ("created", "authorized", "started", "result", "retry", "reconciliation")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _chain_hash(prev_hash, record):
    material = json.dumps({k: record[k] for k in ("seq", "action_type", "tool_name", "metadata")},
                          sort_keys=True, default=str)
    return hashlib.sha256(f"{prev_hash}|{material}".encode()).hexdigest()


class FlightRecorder:
    """Append-only lifecycle recorder for business operations."""

    def __init__(self):
        self.records = []
        self._prev_hash = ""
        self._attempt = {}   # operation_id -> current attempt number
        self._action = {}    # operation_id -> tool_name / action

    def _append(self, operation_id, stage, outcome=""):
        if stage not in STAGES:
            raise ValueError(f"unknown lifecycle stage: {stage!r}; known: {STAGES}")
        attempt = self._attempt.get(operation_id, 1)
        record = {
            "seq": len(self.records) + 1,
            "created_at": _now(),
            "action_type": f"operation.{stage}",
            "tool_name": self._action.get(operation_id, ""),
            "metadata": {
                "request_id": operation_id,
                "operation_id": operation_id,
                "attempt": attempt,
                "stage": stage,
                "outcome": outcome,
            },
            "prev_hash": self._prev_hash,
        }
        record["hash"] = _chain_hash(self._prev_hash, record)
        self._prev_hash = record["hash"]
        self.records.append(record)
        return record

    # -- lifecycle API ------------------------------------------------------
    def create(self, operation_id, action):
        self._action[operation_id] = action
        self._attempt.setdefault(operation_id, 1)
        return self._append(operation_id, "created")

    def authorize(self, operation_id):
        return self._append(operation_id, "authorized")

    def start(self, operation_id):
        return self._append(operation_id, "started")

    def result(self, operation_id, outcome):
        return self._append(operation_id, "result", outcome)

    def retry(self, operation_id):
        """Begin a new recovery attempt for the same operation."""
        self._attempt[operation_id] = self._attempt.get(operation_id, 1) + 1
        return self._append(operation_id, "retry")

    def reconcile(self, operation_id, outcome):
        return self._append(operation_id, "reconciliation", outcome)

    # -- auditor views --------------------------------------------------------
    def summaries(self):
        return group_records(self.records)

    def summary(self, operation_id):
        for s in self.summaries():
            if s["operation_id"] == operation_id:
                return s
        return None


def _operation_key(record):
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(record.get("operation_id") or meta.get("operation_id")
               or record.get("request_id") or meta.get("request_id")
               or record.get("action_id") or "")


def group_records(records):
    """Group AFR-shaped records by stable operation ID.

    Returns one summary per operation, in first-seen order:
    {operation_id, action, attempts, records, stages}. ``attempts`` is the
    highest attempt number recorded for the operation; records that carry
    no attempt metadata (e.g. a raw AFR decision/outcome pair sharing a
    request_id) count as one attempt spanning all their records.
    """
    order, grouped = [], {}
    for rec in sorted(records, key=lambda r: r.get("seq", 0)):
        key = _operation_key(rec)
        if not key:
            continue
        if key not in grouped:
            order.append(key)
            grouped[key] = {"operation_id": key, "action": rec.get("tool_name") or "",
                            "attempts": 1, "records": 0, "stages": []}
        g = grouped[key]
        g["records"] += 1
        g["stages"].append(str(rec.get("action_type") or ""))
        meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
        try:
            g["attempts"] = max(g["attempts"], int(meta.get("attempt") or 1))
        except (TypeError, ValueError):
            pass
    return [grouped[k] for k in order]


def summary_line(summary):
    """The auditor's one line: 'one operation, N attempts'."""
    return (f"operation {summary['operation_id']}: 1 operation, "
            f"{summary['attempts']} attempts, {summary['records']} lifecycle records "
            f"({', '.join(summary['stages'])})")


def verify_chain(records):
    """True when the records' prev_hash/hash chain is intact, in seq order."""
    prev = ""
    for rec in sorted(records, key=lambda r: r.get("seq", 0)):
        if rec.get("prev_hash") != prev or rec.get("hash") != _chain_hash(prev, rec):
            return False
        prev = rec["hash"]
    return True
