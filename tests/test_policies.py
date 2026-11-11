"""Auth Gateway policy examples: retry permission, spend ceiling,
human approval before a repeated sensitive action."""
from agent_recovery_lab.policies import (EXAMPLE_POLICIES,
                                         RepeatedSensitiveApprovalPolicy,
                                         RetryPolicy, SpendCeilingPolicy)

# -- (i) retry permission ----------------------------------------------------

def test_retry_allowed_only_when_confirmed_not_applied():
    p = RetryPolicy(max_attempts=3)
    assert p.evaluate("payment.charge", 2, "not_applied")["verdict"] == "allow"


def test_retry_unknown_outcome_reconciles_first_never_blind():
    p = RetryPolicy()
    assert p.evaluate("payment.charge", 2, "unknown")["verdict"] == "reconcile-first"


def test_retry_after_applied_is_denied_as_duplicate():
    p = RetryPolicy()
    assert p.evaluate("payment.charge", 2, "applied")["verdict"] == "deny"


def test_retry_denylist_destructive_killswitch_and_cap():
    p = RetryPolicy(max_attempts=3, denylist=["payment.charge.void"])
    assert p.evaluate("payment.charge.void", 2, "not_applied")["verdict"] == "deny"
    assert p.evaluate("data.delete_all", 2, "not_applied")["verdict"] == "deny"
    assert p.evaluate("payment.charge", 2, "not_applied", agent_enabled=False)["verdict"] == "deny"
    assert p.evaluate("payment.charge", 4, "not_applied")["verdict"] == "deny"


def test_retry_unlisted_action_escalates_to_human():
    p = RetryPolicy(allowlist=["payment.charge"])
    assert p.evaluate("email.send", 2, "not_applied")["verdict"] == "escalate"
    assert p.evaluate("payment.charge", 2, "not_applied")["verdict"] == "allow"

# -- (ii) spend ceiling --------------------------------------------------------

def test_spend_standing_approval_under_threshold_inside_envelope():
    p = SpendCeilingPolicy()
    out = p.evaluate(400, cumulative_cents=1000)
    assert out["verdict"] == "approved" and out["channels"] == ["standing_approval"]


def test_spend_over_threshold_holds_without_holder_approval():
    p = SpendCeilingPolicy()
    out = p.evaluate(600, cumulative_cents=0)
    assert out["verdict"] == "hold" and "over_approval_threshold" in out["channels"]
    assert p.evaluate(600, holder_approval=True)["verdict"] == "approved"


def test_spend_envelope_exhaustion_holds_and_caps_deny():
    p = SpendCeilingPolicy(max_cents=50000)
    assert p.evaluate(400, cumulative_cents=49900)["verdict"] == "hold"
    capped = SpendCeilingPolicy(daily_cap_cents=1000)
    out = capped.evaluate(400, daily_used=900)
    assert out["verdict"] == "deny" and out["channels"] == ["daily_cap_exceeded"]


def test_spend_require_approval_mode_holds_everything_unapproved():
    p = SpendCeilingPolicy(require_approval=True)
    assert p.evaluate(100)["verdict"] == "hold"
    assert p.evaluate(100, holder_approval=True)["verdict"] == "approved"

# -- (iii) repeated sensitive action -------------------------------------------

def test_non_sensitive_action_needs_no_approval():
    p = RepeatedSensitiveApprovalPolicy()
    assert p.evaluate("message.send", "op_1")["verdict"] == "approved"


def test_first_sensitive_execution_needs_approval():
    p = RepeatedSensitiveApprovalPolicy()
    assert p.evaluate("payment.charge", "op_1")["verdict"] == "require_approval"
    assert p.evaluate("payment.charge", "op_1", approval_id="appr_1")["verdict"] == "approved"


def test_repeat_sensitive_needs_fresh_approval_not_the_same_one():
    p = RepeatedSensitiveApprovalPolicy()
    assert p.evaluate("payment.charge", "op_1", approval_id="appr_1")["verdict"] == "approved"
    p.record_execution("payment.charge", "op_1", approval_id="appr_1")
    # Same approval re-presented: not fresh — held for a human again.
    assert p.evaluate("payment.charge", "op_1", approval_id="appr_1")["verdict"] == "require_approval"
    assert p.evaluate("payment.charge", "op_1")["verdict"] == "require_approval"
    # A genuinely fresh approval releases the repeat.
    out = p.evaluate("payment.charge", "op_1", approval_id="appr_2")
    assert out["verdict"] == "approved" and out["repeat"] is True


def test_example_policies_are_shipped():
    assert set(EXAMPLE_POLICIES) == {"payments-retry", "spend-ceiling-default",
                                     "sensitive-repeat-approval"}
