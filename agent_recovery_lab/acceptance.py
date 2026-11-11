"""The revised acceptance gate (GODMODE Weekly Intel revision, 2026-11-11).

Three gates, each proven by real scenario runs — never by assertion alone:

(a) LOST-ACK-AFTER-SUCCESS — the operation succeeds, the acknowledgement
    is lost, and recovery must not create a second business operation.
    Formalised by the ``lost-ack-after-success`` scenario (the earlier
    ``timeout`` / ``uncertain-outcome`` scenarios exercised the same
    reconcile-instead-of-blind-retry discipline without the acceptance
    name, a stable operation ID, or a lifecycle record). The gate ALSO
    runs the honest counter-case: the same discipline against a
    NonIdempotentGateway must be reported as a FAILURE with two side
    effects — a counter-case reported as a pass fails this gate.
(b) REPEATED WEBHOOK/CALLBACK — the same webhook/callback delivered more
    than once must not duplicate the business operation (proven by the
    pre-existing ``repeated-webhook`` and ``duplicate-event`` scenarios).
(c) WORKER INTERRUPTION — a worker killed after starting an external
    operation but before durable completion is recorded; recovery
    reconciles from evidence instead of blindly re-executing (the
    ``worker-interruption`` scenario; distinct from ``worker-crash``,
    which crashes between checkpointed steps).
"""
from __future__ import annotations

from .gateway import NonIdempotentGateway
from .scenarios import run_lost_ack, run_scenario

GATES = ("lost-ack-after-success", "repeated-webhook-callback", "worker-interruption")


def run_acceptance():
    """Run all three gates. Returns a list of gate-result dicts."""
    good = run_lost_ack()
    counter = run_lost_ack(NonIdempotentGateway())
    gate_a = {
        "gate": "lost-ack-after-success",
        "passed": bool(good["passed"] and not counter["passed"]
                       and counter["side_effects"] == 2),
        "scenarios": [good["name"]],
        "evidence": good["detail"],
        "counter_case": {
            "gateway": "NonIdempotentGateway (idempotency absent/broken)",
            "passed": counter["passed"],
            "side_effects": counter["side_effects"],
            "verdict": "reported as FAILURE — duplicate created and surfaced, never passed"
            if not counter["passed"] else "ERROR: counter-case was reported as a pass",
            "evidence": counter["detail"],
        },
    }
    webhook = run_scenario("repeated-webhook")
    duplicate = run_scenario("duplicate-event")
    gate_b = {
        "gate": "repeated-webhook-callback",
        "passed": bool(webhook["passed"] and duplicate["passed"]),
        "scenarios": [webhook["name"], duplicate["name"]],
        "evidence": f"{webhook['name']}: {webhook['detail']} | {duplicate['name']}: {duplicate['detail']}",
    }
    interruption = run_scenario("worker-interruption")
    gate_c = {
        "gate": "worker-interruption",
        "passed": bool(interruption["passed"]),
        "scenarios": [interruption["name"]],
        "evidence": interruption["detail"],
    }
    return [gate_a, gate_b, gate_c]
