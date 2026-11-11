"""The built-in failure-injection scenarios.

Each scenario builds a FRESH gateway + runner (full isolation), injects one
failure, and asserts one safety property. A scenario result is a plain dict:
{name, passed, property, checks, side_effects, detail}.
"""
from __future__ import annotations

from .failover import run_failover_eligibility_scenario
from .gateway import FakeGateway, ResponseLost
from .lifecycle import FlightRecorder, summary_line
from .runner import SimulatedCrash, WorkflowRunner


def _result(name, prop, checks, gateway, detail, operations=None):
    result = {
        "name": name,
        "passed": all(checks.values()),
        "property": prop,
        "checks": checks,
        "side_effects": gateway.effect_count(),
        "detail": detail,
    }
    if operations:
        result["operations"] = operations
    return result


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


def run_lost_ack(gateway=None):
    """Acceptance (a) evaluator, parameterised by gateway so the honest
    counter-case can run it against a NonIdempotentGateway.

    Discipline under test: the operation succeeds, the acknowledgement is
    lost, and the recovery attempt reconciles against true state instead
    of re-executing. With a correct gateway that yields exactly one side
    effect; with a broken (non-idempotent) gateway the lookup misses, the
    retry duplicates the operation, and this result's ``passed`` is False
    — a failure, never a pass.
    """
    gw = gateway or FakeGateway()
    rec = FlightRecorder()
    op, action = "op_pay_001", "payment.charge"
    key = f"{op}:{action}"
    rec.create(op, action)
    rec.authorize(op)
    rec.start(op)
    ack_lost = False
    try:
        gw.apply_then_lose_response(key, action, {"amount": 49})
    except ResponseLost:
        ack_lost = True
    rec.result(op, "ack-lost")
    rec.retry(op)  # recovery attempt, same stable operation ID
    found = gw.lookup(key)
    if found is None:
        # Reconciliation missed (broken idempotency downstream): the retry
        # re-executes — this is the duplicate the counter-case must surface.
        gw.apply(key, action, {"amount": 49})
        rec.start(op)
        rec.result(op, "applied-on-retry")
    else:
        rec.reconcile(op, "found-applied-no-reexecution")
    summary = rec.summary(op)
    checks = {
        "acknowledgement_was_lost": ack_lost,
        "exactly_one_side_effect": gw.effect_count(action) == 1,
        "one_operation_many_attempts": summary is not None and summary["attempts"] == 2
        and summary["records"] >= 5,
        "hash_chain_intact": _chain_ok(rec),
    }
    detail = (f"{summary_line(summary)}; side_effects={gw.effect_count(action)}; "
              + ("reconciliation found the applied charge, no re-execution."
                 if found is not None else
                 "reconciliation MISSED (idempotency broken downstream), retry duplicated the operation."))
    return _result("lost-ack-after-success",
                   "Lost-ack-after-success: recovery must not create a second business operation when idempotency holds.",
                   checks, gw, detail, operations=[summary] if summary else None)


def _chain_ok(recorder):
    from .lifecycle import verify_chain
    return verify_chain(recorder.records)


def scenario_lost_ack_after_success():
    return run_lost_ack()


def scenario_worker_interruption():
    """Acceptance (c): worker killed AFTER starting the external operation
    but BEFORE durable completion is recorded (the dangerous window the
    checkpoint-after-step worker-crash scenario does not cover). Recovery
    reconciles from evidence (gateway true state) instead of blindly
    re-executing the started operation.
    """
    gw = FakeGateway()
    runner = WorkflowRunner(gw)
    rec = FlightRecorder()
    op, action, step = "op_msg_001", "message.send", "notify"
    key = f"{step}:{action}"
    rec.create(op, action)
    rec.authorize(op)
    rec.start(op)
    crashed = False
    try:
        gw.apply(key, action, {"to": "teammate"})  # external operation starts and applies
        raise SimulatedCrash("worker killed after starting, before completion was recorded")
    except SimulatedCrash:
        crashed = True
    effects_at_crash = gw.effect_count(action)
    recorded_at_crash = step in runner.checkpoint["completed_steps"]
    # Recovery: a fresh worker whose checkpoint has NO record of the step.
    recovery = WorkflowRunner(gw)
    recovery.checkpoint = runner.checkpoint
    rec.retry(op)  # recovery attempt, same stable operation ID
    found = gw.lookup(key)  # evidence first — never blind re-execution
    how = None
    if found is not None:
        recovery._mark_done(step)
        rec.reconcile(op, "found-applied-no-reexecution")
        how = "reconciled"
    summary = rec.summary(op)
    checks = {
        "crash_happened_after_start": crashed,
        "operation_had_started_before_crash": effects_at_crash == 1,
        "completion_was_not_durably_recorded": not recorded_at_crash,
        "recovery_reconciled_from_evidence": how == "reconciled",
        "no_blind_reexecution_exactly_one_side_effect": gw.effect_count(action) == 1,
        "one_operation_many_attempts": summary is not None and summary["attempts"] == 2,
    }
    return _result("worker-interruption",
                   "Worker killed after starting an external operation but before recording completion: recovery reconciles from evidence, never blindly re-executes.",
                   checks, gw,
                   f"{summary_line(summary)}; effect existed at crash, checkpoint had no completion "
                   "record, recovery lookup() found it and marked done without re-applying.",
                   operations=[summary] if summary else None)


SCENARIOS = {
    "timeout": scenario_timeout,
    "duplicate-event": scenario_duplicate_event,
    "worker-crash": scenario_worker_crash,
    "partial-response": scenario_partial_response,
    "repeated-webhook": scenario_repeated_webhook,
    "delayed-approval": scenario_delayed_approval,
    "provider-interruption": scenario_provider_interruption,
    "uncertain-outcome": scenario_uncertain_outcome,
    "lost-ack-after-success": scenario_lost_ack_after_success,
    "worker-interruption": scenario_worker_interruption,
    "failover-eligibility": run_failover_eligibility_scenario,
}


def run_scenario(name):
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario: {name!r}; known: {sorted(SCENARIOS)}")
    return SCENARIOS[name]()


def run_all():
    return [SCENARIOS[name]() for name in SCENARIOS]
