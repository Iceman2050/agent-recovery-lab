"""Reusable example policies, patterned on the real Agent Auth Gateway.

Patterns are reused, code is not imported (the gateway is a server app,
not a library). Each policy names its source pattern:

- ``RetryPolicy`` — gateway ``app/dual_approval.py`` PolicyJudge (denylist
  and destructive patterns deny; a broken/unknown state fails closed) +
  gateway ``app/connector.py`` delivery discipline (presence-check BEFORE
  any retry — an ambiguous outcome is reconciled, never blindly replayed;
  bounded attempts with backoff ``[5, 30, 120, 600, 900]``s, then dead).
- ``SpendCeilingPolicy`` — gateway ``app/spendguard.py`` (per-key budget
  envelope: ``max_cents`` over a rolling window, per-transaction
  ``approval_threshold_cents``, ``require_approval`` mode, hold-by-default,
  standing approval only for an allowlisted source under threshold inside
  the envelope) + ``app/main.py::_decide_action`` (daily/monthly caps deny
  when the call would breach them; kill switch and denylist deny first).
- ``RepeatedSensitiveApprovalPolicy`` — spendguard's release rule (holds
  are owner-released, NEVER auto-released; the next unapproved transaction
  holds again) applied to repeats: a sensitive action needs a human
  approval, and a REPEAT of it needs a FRESH approval — the first approval
  never carries over, and re-presenting the same approval does not count.

All policies are pure and fail-closed: malformed input denies/holds.
"""
from __future__ import annotations

# Mirrors dual_approval.DESTRUCTIVE_PATTERNS (kept local there to avoid an
# import cycle; kept local here for the same reason).
DESTRUCTIVE_PATTERNS = ("delete", "drop", "purge", "destroy", "truncate",
                        "wipe", "erase", "format", "shutdown")

# Mirrors connector.BACKOFF_S.
BACKOFF_S = (5, 30, 120, 600, 900)

PRIOR_OUTCOMES = ("not_applied", "applied", "unknown")


class RetryPolicy:
    """(i) Retry permission: may this action be attempted again?

    ``prior_outcome`` is what evidence says about the previous attempt:
    ``not_applied`` (provider confirmed nothing happened — the only state
    in which a retry is straightforwardly safe), ``applied`` (it already
    happened — a retry would duplicate it), or ``unknown`` (ambiguous —
    reconcile first, never blind-retry).
    """

    def __init__(self, max_attempts=3, denylist=(), allowlist=None):
        self.max_attempts = max(1, int(max_attempts))
        self.denylist = {str(a).strip().lower() for a in denylist}
        self.allowlist = ({str(a).strip().lower() for a in allowlist}
                          if allowlist is not None else None)

    def evaluate(self, action, attempt, prior_outcome, agent_enabled=True):
        """attempt = the attempt number being considered (1 = first try)."""
        act = str(action or "").strip().lower()
        try:
            attempt = int(attempt)
        except (TypeError, ValueError):
            attempt = 0
        base = {"policy": "retry", "action": act, "attempt": attempt}
        if not act or attempt < 1 or prior_outcome not in PRIOR_OUTCOMES:
            return {**base, "verdict": "deny",
                    "reasons": ["Malformed retry request — fail-closed deny."]}
        if not agent_enabled:
            return {**base, "verdict": "deny",
                    "reasons": ["Kill switch engaged — the agent is disabled; no retry may be approved."]}
        if act in self.denylist:
            return {**base, "verdict": "deny",
                    "reasons": [f"Action '{act}' is on the denylist."]}
        if any(p in act for p in DESTRUCTIVE_PATTERNS):
            return {**base, "verdict": "deny",
                    "reasons": [f"Action '{act}' matches the destructive-action pattern list — never auto-retried."]}
        if prior_outcome == "applied":
            return {**base, "verdict": "deny",
                    "reasons": ["The previous attempt already applied — a retry would duplicate the business operation."]}
        if prior_outcome == "unknown":
            return {**base, "verdict": "reconcile-first",
                    "reasons": ["Previous outcome is unknown — presence-check / reconcile against true state before any retry (connector discipline)."]}
        if attempt > self.max_attempts:
            return {**base, "verdict": "deny",
                    "reasons": [f"Attempt {attempt} exceeds max_attempts={self.max_attempts} — dead-letter, do not retry."]}
        if self.allowlist is not None and act not in self.allowlist:
            return {**base, "verdict": "escalate",
                    "reasons": [f"Action '{act}' is not on the allowlist — a human should confirm the retry."]}
        backoff = BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)] if attempt > 1 else 0
        return {**base, "verdict": "allow", "backoff_s": backoff,
                "reasons": ["Previous attempt confirmed not applied, action policy-clean, "
                            f"attempt {attempt} of {self.max_attempts}."]}


class SpendCeilingPolicy:
    """(ii) Spend ceiling: envelope + per-transaction threshold + caps.

    Defaults mirror spendguard's seeded envelope (db.py): $500 envelope
    per 24h, $5 per-transaction approval threshold.
    """

    def __init__(self, max_cents=50000, envelope_hours=24,
                 approval_threshold_cents=500, daily_cap_cents=0,
                 monthly_cap_cents=0, require_approval=False):
        self.max_cents = max(0, int(max_cents))
        self.envelope_hours = max(1, int(envelope_hours))
        self.approval_threshold_cents = max(0, int(approval_threshold_cents))
        self.daily_cap_cents = max(0, int(daily_cap_cents))
        self.monthly_cap_cents = max(0, int(monthly_cap_cents))
        self.require_approval = bool(require_approval)

    def evaluate(self, amount_cents, cumulative_cents=0, daily_used=0,
                 monthly_used=0, holder_approval=False, wallet_allowlisted=True):
        try:
            amount = max(0, int(amount_cents))
            cumulative, daily_used, monthly_used = (max(0, int(v)) for v in
                                                    (cumulative_cents, daily_used, monthly_used))
        except (TypeError, ValueError):
            return {"policy": "spend-ceiling", "verdict": "hold",
                    "channels": ["fail_closed_error"],
                    "reasons": ["Malformed amounts — held by default (fail-closed)."]}
        # Caps deny outright (mirrors _decide_action step 3).
        if self.daily_cap_cents and daily_used + amount > self.daily_cap_cents:
            return {"policy": "spend-ceiling", "verdict": "deny", "amount_cents": amount,
                    "channels": ["daily_cap_exceeded"],
                    "reasons": [f"Daily cap {self.daily_cap_cents} would be exceeded ({daily_used} used already)."]}
        if self.monthly_cap_cents and monthly_used + amount > self.monthly_cap_cents:
            return {"policy": "spend-ceiling", "verdict": "deny", "amount_cents": amount,
                    "channels": ["monthly_cap_exceeded"],
                    "reasons": [f"Monthly cap {self.monthly_cap_cents} would be exceeded ({monthly_used} used already)."]}
        over_threshold = (amount >= self.approval_threshold_cents
                          if self.approval_threshold_cents > 0 else amount > 0)
        envelope_hit = (cumulative + amount) > self.max_cents if self.max_cents > 0 else False
        standing_ok = (wallet_allowlisted and not over_threshold
                       and not envelope_hit and not self.require_approval)
        approved = bool(holder_approval or standing_ok)
        channels = []
        if over_threshold:
            channels.append("over_approval_threshold")
        if envelope_hit:
            channels.append("envelope_exhausted")
        if not wallet_allowlisted:
            channels.append("non_allowlisted_source")
        if self.require_approval:
            channels.append("require_approval_mode")
        if not approved:
            channels.append("no_holder_approval")
            return {"policy": "spend-ceiling", "verdict": "hold", "amount_cents": amount,
                    "channels": channels,
                    "reasons": ["Held for holder approval — spendguard rule: a hold is "
                                "owner-released, never silently auto-released."]}
        return {"policy": "spend-ceiling", "verdict": "approved", "amount_cents": amount,
                "channels": ["explicit_holder_approval" if holder_approval else "standing_approval"],
                "reasons": ["Explicit holder approval present." if holder_approval
                            else "Standing approval: allowlisted source, under threshold, inside envelope."]}


class RepeatedSensitiveApprovalPolicy:
    """(iii) Human approval before a repeated sensitive action.

    State: executions are counted per (subject, action). The first
    execution of a sensitive action needs an approval; every REPEAT needs
    a FRESH approval id never used for that subject+action before.
    """

    def __init__(self, sensitive_actions=("payment.charge", "payment.refund",
                                          "deploy.release", "data.delete")):
        self.sensitive_actions = {str(a).strip().lower() for a in sensitive_actions}
        self._executions = {}       # (subject, action) -> count
        self._used_approvals = {}   # (subject, action) -> set of approval ids

    def executions(self, subject, action):
        return self._executions.get((subject, str(action).strip().lower()), 0)

    def evaluate(self, action, subject, approval_id=None):
        act = str(action or "").strip().lower()
        key = (subject, act)
        base = {"policy": "repeated-sensitive-approval", "action": act,
                "subject": subject, "prior_executions": self._executions.get(key, 0)}
        if act not in self.sensitive_actions:
            return {**base, "verdict": "approved", "approval_required": False,
                    "reasons": ["Not a sensitive action — no approval gate."]}
        repeat = self._executions.get(key, 0) >= 1
        if not approval_id:
            return {**base, "verdict": "require_approval", "approval_required": True,
                    "repeat": repeat,
                    "reasons": [("Repeat of a sensitive action — a FRESH human approval is "
                                 "required; the earlier approval does not carry over.")
                                if repeat else
                                "Sensitive action — human approval required before it runs."]}
        if approval_id in self._used_approvals.get(key, set()):
            return {**base, "verdict": "require_approval", "approval_required": True,
                    "repeat": repeat,
                    "reasons": ["That approval was already consumed for this action — "
                                "re-presenting it is not a fresh approval."]}
        return {**base, "verdict": "approved", "approval_required": True, "repeat": repeat,
                "reasons": ["Fresh human approval present for this execution."]}

    def record_execution(self, action, subject, approval_id=None):
        """Call only after an approved execution actually ran."""
        act = str(action or "").strip().lower()
        key = (subject, act)
        self._executions[key] = self._executions.get(key, 0) + 1
        if approval_id:
            self._used_approvals.setdefault(key, set()).add(approval_id)
        return self._executions[key]


# Named, reusable example configurations.
EXAMPLE_POLICIES = {
    "payments-retry": RetryPolicy(max_attempts=3, denylist=["payment.charge.void"]),
    "spend-ceiling-default": SpendCeilingPolicy(),
    "sensitive-repeat-approval": RepeatedSensitiveApprovalPolicy(),
}
