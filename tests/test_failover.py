"""The ONE folded-in failover-eligibility scenario (FailoverGuard deferred
standalone; this single test is what the revision asks for)."""
from agent_recovery_lab.failover import (FIXTURES, check_failover_eligibility,
                                         run_failover_eligibility_scenario)
from agent_recovery_lab.scenarios import run_scenario

ALL_CLEAR = dict(retry_eligible=True, provider_approved=True,
                 capability_compatible=True, policy_permits=True, state_known=True)


def test_all_five_checks_pass_is_eligible():
    assert check_failover_eligibility(**ALL_CLEAR)["verdict"] == "ELIGIBLE"


def test_ambiguous_outcome_never_auto_replays():
    out = check_failover_eligibility(**ALL_CLEAR, outcome_unknown=True)
    assert out["verdict"] == "RECONCILE"
    out = check_failover_eligibility(**ALL_CLEAR, outcome_unknown=True, reconcilable=False)
    assert out["verdict"] == "ESCALATE"


def test_unknown_state_reconciles_even_without_outcome_flag():
    out = check_failover_eligibility(**{**ALL_CLEAR, "state_known": False})
    assert out["verdict"] in ("RECONCILE", "ESCALATE")


def test_each_hard_check_failure_is_not_eligible():
    for field in ("retry_eligible", "provider_approved", "capability_compatible", "policy_permits"):
        out = check_failover_eligibility(**{**ALL_CLEAR, field: False})
        assert out["verdict"] == "NOT_ELIGIBLE", field
        assert out["failed"] == [field]


def test_failover_scenario_fixtures_all_match():
    result = run_failover_eligibility_scenario()
    assert result["passed"], result
    assert result["checks"]["ambiguous_never_auto_replay"]
    assert len(FIXTURES) == 9


def test_failover_scenario_is_in_the_catalogue():
    assert run_scenario("failover-eligibility")["passed"]
