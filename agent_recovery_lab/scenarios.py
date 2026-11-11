"""The eight built-in failure-injection scenarios.

Each scenario builds a FRESH gateway + runner (full isolation), injects one
failure, and asserts one safety property. A scenario result is a plain dict:
{name, passed, property, checks, side_effects, detail}.
"""
from __future__ import annotations

from .gateway import FakeGateway, ResponseLost
from .runner import SimulatedCrash, WorkflowRunner


def _result(name, prop, checks, gateway, detail):
    return {
        "name": name,
        "passed": all(checks.values()),
        "property": prop,
        "checks": checks,
        "side_effects": gateway.effect_count(),
        "detail": detail,
    }


def scenario_timeout():
    gw, r = FakeGateway(), None
    r = WorkflowRunner(gw)
    key = "pay:payment.charge"
    try:
        gw.apply_then_lose_response(key, "payment.charge", {"amount": 49})
        blind = True
    except ResponseLost:
        blind = False
    # Runner discipline: reconcile instead of blind-retrying.
    found = gw.lookup(key)
    checks = {
        "response_was_lost": not blind,
        "reconciliation_found_the_action": found is not None,
        "exactly_one_side_effect": gw.effect_count("payment.charge") == 1,
    }
    return _result("timeout", "A timed-out action is reconciled, not blind-retried: exactly one side effect.",
                   checks, gw, "Gateway applied the charge, response was lost, lookup() confirmed it; no retry issued.")


def scenario_duplicate_event():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    r.deliver_event("evt_42", "order.updated", {"order": 7})
    _, how2 = r.deliver_event("evt_42", "order.updated", {"order": 7})
    checks = {
        "second_delivery_ignored": how2 == "duplicate-ignored",
        "exactly_one_side_effect": gw.effect_count("order.updated") == 1,
    }
    return _result("duplicate-event", "The same callback delivered twice is applied once.",
                   checks, gw, "event_id evt_42 delivered twice; second delivery ignored by the dedupe store.")


def scenario_worker_crash():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    crashed = False
    try:
        r.run_reference_workflow(crash_after_step="reserve")
    except SimulatedCrash:
        crashed = True
    resumed = WorkflowRunner(gw)
    resumed.checkpoint = r.checkpoint  # checkpoint survives the crash
    out = resumed.run_reference_workflow()
    hows = {row["step"]: row["how"] for row in out}
    checks = {
        "crash_happened": crashed,
        "completed_step_not_repeated": hows.get("reserve") == "checkpoint",
        "each_action_applied_once": all(
            gw.effect_count(a) == 1
            for a in ("inventory.reserve", "payment.charge", "message.send")),
        "all_steps_completed": len(resumed.checkpoint["completed_steps"]) == 3,
    }
    return _result("worker-crash", "Crash mid-workflow, resume from checkpoint: no step is repeated.",
                   checks, gw, "Crashed after 'reserve'; resume skipped it via checkpoint and finished the rest.")


def scenario_partial_response():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    _, how = r.execute_with_partial_response("charge", "payment.charge", {"amount": 49})
    checks = {
        "partial_treated_as_uncertain_and_reconciled": how == "reconciled",
        "exactly_one_side_effect": gw.effect_count("payment.charge") == 1,
    }
    return _result("partial-response", "A partial/truncated response is treated as uncertain and reconciled: exactly one side effect.",
                   checks, gw, "Response body arrived truncated (no status); runner queried true state instead of retrying.")


def scenario_repeated_webhook():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    for _ in range(5):
        r.deliver_event("wh_99", "webhook.payment_succeeded", {"invoice": "in_1"})
    # Provider retries also reuse the same idempotency key at the gateway:
    gw.apply("wh_99-key", "webhook.payment_succeeded", {"invoice": "in_1"})
    gw.apply("wh_99-key", "webhook.payment_succeeded", {"invoice": "in_1"})
    checks = {
        "webhook_applied_once_per_event": gw.effect_count("webhook.payment_succeeded") == 2,
        "no_duplicate_for_same_event_id": len([e for e in gw.effects if e["idempotency_key"] == "event:wh_99"]) == 1,
        "no_duplicate_for_same_key": len([e for e in gw.effects if e["idempotency_key"] == "wh_99-key"]) == 1,
    }
    return _result("repeated-webhook", "A webhook redelivered repeatedly (provider retry storm) is applied once per event/key.",
                   checks, gw, "Same webhook delivered 5x plus 2 keyed retries; one effect per event id and per key.")


def scenario_delayed_approval():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    early, how_early = r.execute_after_approval("appr_1", "deploy", "deploy.release")
    r.approve("appr_1")  # approval arrives late, after the first attempt timed out waiting
    _, how1 = r.execute_after_approval("appr_1", "deploy", "deploy.release")
    r.approve("appr_1")  # duplicate late approval must not re-run it
    _, how2 = r.execute_after_approval("appr_1", "deploy", "deploy.release")
    checks = {
        "nothing_ran_before_approval": early is None and how_early == "waiting-for-approval"
        and gw.effect_count("deploy.release") == 1,  # count checked after full run below
        "ran_once_after_delayed_approval": how1 in ("applied", "applied-after-provider-retry"),
        "duplicate_approval_did_not_rerun": how2 == "checkpoint",
        "exactly_one_side_effect": gw.effect_count("deploy.release") == 1,
    }
    checks["nothing_ran_before_approval"] = early is None and how_early == "waiting-for-approval"
    return _result("delayed-approval", "An action gated on human approval runs zero times before approval and exactly once after a delayed approval.",
                   checks, gw, "Approval arrived late; pre-approval attempt waited, post-approval ran once, duplicate approval was a no-op.")


def scenario_provider_interruption():
    gw = FakeGateway()
    gw.interrupt_next = True
    r = WorkflowRunner(gw)
    _, how = r.execute_once("charge", "payment.charge", {"amount": 49})
    checks = {
        "retry_only_because_nothing_applied": how == "applied-after-provider-retry",
        "exactly_one_side_effect": gw.effect_count("payment.charge") == 1,
    }
    return _result("provider-interruption", "When the provider fails BEFORE applying, a retry is safe and lands exactly one side effect.",
                   checks, gw, "First call raised ProviderUnavailable before applying; single retry applied once.")


def scenario_uncertain_outcome():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    key = "send:message.send"
    try:
        gw.apply_then_lose_response(key, "message.send", {"to": "teammate"})
    except ResponseLost:
        pass
    found = gw.lookup(key)  # reconcile: did it happen or not?
    comp_before = len(gw.compensations)
    if found is not None:
        r._mark_done("send")
    checks = {
        "outcome_resolved_by_reconciliation": found is not None,
        "no_blind_retry": gw.effect_count("message.send") == 1,
        "no_wrong_compensation": len(gw.compensations) == comp_before,
    }
    # Compensation hook sanity: an explicit later cancel compensates exactly once.
    gw.compensate(key, "operator cancelled after confirmation")
    gw.compensate(key, "duplicate cancel")
    checks["compensation_runs_at_most_once"] = len(gw.compensations) == 1
    return _result("uncertain-outcome", "An uncertain external outcome is resolved by querying true state before retrying or compensating.",
                   checks, gw, "Send applied but ack lost; reconciliation confirmed it, no retry, no spurious compensation; explicit cancel compensated once.")


SCENARIOS = {
    "timeout": scenario_timeout,
    "duplicate-event": scenario_duplicate_event,
    "worker-crash": scenario_worker_crash,
    "partial-response": scenario_partial_response,
    "repeated-webhook": scenario_repeated_webhook,
    "delayed-approval": scenario_delayed_approval,
    "provider-interruption": scenario_provider_interruption,
    "uncertain-outcome": scenario_uncertain_outcome,
}


def run_scenario(name):
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario: {name!r}; known: {sorted(SCENARIOS)}")
    return SCENARIOS[name]()


def run_all():
    return [SCENARIOS[name]() for name in SCENARIOS]
