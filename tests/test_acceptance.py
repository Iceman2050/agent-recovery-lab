"""The revised acceptance gate: three scenarios, proven by real runs,
plus the honest lost-ack counter-case (broken idempotency must FAIL)."""
from agent_recovery_lab.acceptance import run_acceptance
from agent_recovery_lab.gateway import NonIdempotentGateway
from agent_recovery_lab.scenarios import run_lost_ack, run_scenario


def test_acceptance_gate_a_lost_ack_passes_with_one_side_effect():
    result = run_lost_ack()
    assert result["passed"], result
    assert result["side_effects"] == 1
    assert result["operations"][0]["attempts"] == 2


def test_acceptance_gate_a_counter_case_is_reported_as_failure():
    # Idempotency absent/broken downstream: the duplicate IS created and
    # the harness reports the run as a failure — never a pass.
    result = run_lost_ack(NonIdempotentGateway())
    assert result["passed"] is False
    assert result["side_effects"] == 2
    assert result["checks"]["exactly_one_side_effect"] is False


def test_acceptance_gate_b_repeated_webhook_and_duplicate_event():
    assert run_scenario("repeated-webhook")["passed"]
    assert run_scenario("duplicate-event")["passed"]
    assert run_scenario("repeated-webhook")["side_effects"] == 2  # one per event, one per key


def test_acceptance_gate_c_worker_interruption_reconciles():
    result = run_scenario("worker-interruption")
    assert result["passed"], result
    assert result["side_effects"] == 1
    assert result["checks"]["recovery_reconciled_from_evidence"]
    assert result["checks"]["completion_was_not_durably_recorded"]


def test_acceptance_all_three_gates_pass():
    gates = run_acceptance()
    assert [g["gate"] for g in gates] == [
        "lost-ack-after-success", "repeated-webhook-callback", "worker-interruption"]
    assert all(g["passed"] for g in gates), gates
    counter = gates[0]["counter_case"]
    assert counter["passed"] is False and counter["side_effects"] == 2
