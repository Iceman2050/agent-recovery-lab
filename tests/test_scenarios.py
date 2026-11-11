"""Every built-in scenario's safety assertion, plus gateway/runner units."""
import pytest

from agent_recovery_lab.gateway import FakeGateway, ProviderUnavailable, ResponseLost
from agent_recovery_lab.runner import SimulatedCrash, WorkflowRunner
from agent_recovery_lab.scenarios import SCENARIOS, run_all, run_scenario


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_passes(name):
    result = run_scenario(name)
    assert result["passed"], result
    assert all(result["checks"].values())


def test_all_scenarios_present_and_passing():
    results = run_all()
    assert len(results) == 8
    assert all(r["passed"] for r in results)


def test_timeout_exactly_one_effect():
    r = run_scenario("timeout")
    assert r["side_effects"] == 1


def test_duplicate_event_applied_once():
    r = run_scenario("duplicate-event")
    assert r["side_effects"] == 1


def test_worker_crash_no_step_repeated():
    r = run_scenario("worker-crash")
    assert r["side_effects"] == 3  # three distinct steps, each exactly once


def test_gateway_idempotency_key_dedupes():
    gw = FakeGateway()
    gw.apply("k1", "payment.charge")
    gw.apply("k1", "payment.charge")
    assert gw.effect_count() == 1


def test_gateway_response_lost_still_applied():
    gw = FakeGateway()
    with pytest.raises(ResponseLost):
        gw.apply_then_lose_response("k2", "message.send")
    assert gw.lookup("k2") is not None
    assert gw.effect_count() == 1


def test_gateway_provider_interruption_applies_nothing():
    gw = FakeGateway()
    gw.interrupt_next = True
    with pytest.raises(ProviderUnavailable):
        gw.apply("k3", "payment.charge")
    assert gw.effect_count() == 0
    assert gw.lookup("k3") is None


def test_gateway_compensation_at_most_once():
    gw = FakeGateway()
    gw.apply("k4", "payment.charge")
    assert gw.compensate("k4") is not None
    assert gw.compensate("k4") is None
    assert len(gw.compensations) == 1


def test_runner_crash_resume_checkpoint():
    gw = FakeGateway()
    r = WorkflowRunner(gw)
    with pytest.raises(SimulatedCrash):
        r.run_reference_workflow(crash_after_step="charge")
    r2 = WorkflowRunner(gw)
    r2.checkpoint = r.checkpoint
    out = r2.run_reference_workflow()
    assert {row["step"]: row["how"] for row in out}["charge"] == "checkpoint"
    assert gw.effect_count() == 3


def test_unknown_scenario_rejected():
    with pytest.raises(ValueError):
        run_scenario("not-a-scenario")
