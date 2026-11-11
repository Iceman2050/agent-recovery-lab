"""Failover eligibility — exactly ONE folded-in test/scenario.

Folded in from the deferred FailoverGuard (GODMODE Weekly Intel revision,
2026-11-11): before any provider switch, five checks must all pass —
the action is retry-eligible, the candidate provider is approved, its
capabilities are compatible, spend/data policy permits the switch, and
the workflow state is known.

Safety rule: an ambiguous external action (outcome unknown) must verdict
RECONCILE (reconcile against evidence first) or ESCALATE (hand it to a
human) — NEVER auto-replay on the new provider. Ambiguity is checked
before every other check, so no combination of approvals can launder an
unknown outcome into an ELIGIBLE verdict.
"""
from __future__ import annotations

CHECKS = ("retry_eligible", "provider_approved", "capability_compatible",
          "policy_permits", "state_known")


def check_failover_eligibility(*, retry_eligible, provider_approved,
                               capability_compatible, policy_permits,
                               state_known, outcome_unknown=False,
                               reconcilable=True):
    """Return {verdict, checks, failed, reasons}.

    Verdicts: ELIGIBLE (switch + replay permitted), NOT_ELIGIBLE (a hard
    check failed), RECONCILE (outcome ambiguous and evidence exists to
    reconcile), ESCALATE (ambiguous and not reconcilable — human decides).
    """
    checks = {
        "retry_eligible": bool(retry_eligible),
        "provider_approved": bool(provider_approved),
        "capability_compatible": bool(capability_compatible),
        "policy_permits": bool(policy_permits),
        "state_known": bool(state_known),
    }
    if outcome_unknown or not checks["state_known"]:
        verdict = "RECONCILE" if reconcilable else "ESCALATE"
        return {"verdict": verdict, "checks": checks,
                "failed": [k for k, v in checks.items() if not v],
                "reasons": ["External outcome is ambiguous / workflow state unknown — "
                            "never auto-replay on a new provider; "
                            + ("reconcile from evidence first." if reconcilable
                               else "no reconciliation path exists, escalate to a human.")]}
    failed = [k for k, v in checks.items() if not v]
    if failed:
        return {"verdict": "NOT_ELIGIBLE", "checks": checks, "failed": failed,
                "reasons": [f"Failover check failed: {k}." for k in failed]}
    return {"verdict": "ELIGIBLE", "checks": checks, "failed": [],
            "reasons": ["All five failover checks pass and the outcome is known — "
                        "provider switch is eligible."]}


# The one scenario's fixture set: (name, kwargs, expected verdict).
FIXTURES = [
    ("all-clear", dict(retry_eligible=True, provider_approved=True,
                       capability_compatible=True, policy_permits=True,
                       state_known=True), "ELIGIBLE"),
    ("ambiguous-outcome-reconcilable", dict(retry_eligible=True, provider_approved=True,
                                            capability_compatible=True, policy_permits=True,
                                            state_known=True, outcome_unknown=True), "RECONCILE"),
    ("ambiguous-outcome-not-reconcilable", dict(retry_eligible=True, provider_approved=True,
                                                capability_compatible=True, policy_permits=True,
                                                state_known=True, outcome_unknown=True,
                                                reconcilable=False), "ESCALATE"),
    ("state-unknown", dict(retry_eligible=True, provider_approved=True,
                           capability_compatible=True, policy_permits=True,
                           state_known=False), "RECONCILE"),
    ("provider-not-approved", dict(retry_eligible=True, provider_approved=False,
                                   capability_compatible=True, policy_permits=True,
                                   state_known=True), "NOT_ELIGIBLE"),
    ("capability-incompatible", dict(retry_eligible=True, provider_approved=True,
                                     capability_compatible=False, policy_permits=True,
                                     state_known=True), "NOT_ELIGIBLE"),
    ("policy-forbids", dict(retry_eligible=True, provider_approved=True,
                            capability_compatible=True, policy_permits=False,
                            state_known=True), "NOT_ELIGIBLE"),
    ("not-retry-eligible", dict(retry_eligible=False, provider_approved=True,
                                capability_compatible=True, policy_permits=True,
                                state_known=True), "NOT_ELIGIBLE"),
    ("ambiguous-beats-approvals", dict(retry_eligible=True, provider_approved=True,
                                       capability_compatible=True, policy_permits=True,
                                       state_known=True, outcome_unknown=True), "RECONCILE"),
]


def run_failover_eligibility_scenario():
    """Run the fixture set; the scenario passes only if every verdict matches
    AND no ambiguous fixture ever verdicts ELIGIBLE (auto-replay)."""
    verdicts, checks = {}, {}
    for name, kwargs, expected in FIXTURES:
        got = check_failover_eligibility(**kwargs)["verdict"]
        verdicts[name] = got
        checks[f"fixture:{name}"] = got == expected
    ambiguous = [n for n, kw, _ in FIXTURES if kw.get("outcome_unknown") or not kw["state_known"]]
    checks["ambiguous_never_auto_replay"] = all(
        verdicts[n] in ("RECONCILE", "ESCALATE") for n in ambiguous)
    return {
        "name": "failover-eligibility",
        "passed": all(checks.values()),
        "property": "Before a provider switch: retry-eligible, provider approved, capability compatible, "
                    "policy permits, state known — an ambiguous outcome verdicts RECONCILE or ESCALATE, never auto-replay.",
        "checks": checks,
        "side_effects": 0,
        "fixture_verdicts": verdicts,
        "detail": "; ".join(f"{n} -> {verdicts[n]}" for n, _, _ in FIXTURES),
    }
