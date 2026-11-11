"""Workflow runner with checkpointing, reconciliation and idempotent delivery.

The runner embodies the recovery discipline this tool tests:
- every step carries a stable idempotency key;
- before any retry, reconcile: ask the gateway what actually happened;
- completed steps are checkpointed and never repeated after a crash/resume;
- duplicate deliveries (same event id) are applied once.
"""
from __future__ import annotations

from .gateway import FakeGateway, ProviderUnavailable, ResponseLost


class SimulatedCrash(Exception):
    """Raised to simulate a worker crashing mid-workflow."""


class WorkflowRunner:
    def __init__(self, gateway=None):
        self.gateway = gateway or FakeGateway()
        self.checkpoint = {"completed_steps": []}
        self.seen_event_ids = set()
        self.approvals = set()

    # -- checkpointing -----------------------------------------------------
    def _mark_done(self, step):
        if step not in self.checkpoint["completed_steps"]:
            self.checkpoint["completed_steps"].append(step)

    def is_done(self, step):
        return step in self.checkpoint["completed_steps"]

    # -- core safe execution ----------------------------------------------
    def execute_once(self, step, action, payload=None):
        """Run one step safely: reconcile before retrying, never blind-retry.

        Returns (record, how) where how is one of:
        'applied', 'reconciled' (found already applied), 'checkpoint' (skipped).
        """
        key = f"{step}:{action}"
        if self.is_done(step):
            return self.gateway.lookup(key), "checkpoint"
        try:
            record = self.gateway.apply(key, action, payload)
            self._mark_done(step)
            return record, "applied"
        except ResponseLost:
            # Outcome uncertain: reconcile against true state before any retry.
            found = self.gateway.lookup(key)
            if found is not None:
                self._mark_done(step)
                return found, "reconciled"
            record = self.gateway.apply(key, action, payload)
            self._mark_done(step)
            return record, "applied-after-reconcile-miss"
        except ProviderUnavailable:
            # Nothing was applied (provider said so before acting): safe to retry once.
            record = self.gateway.apply(key, action, payload)
            self._mark_done(step)
            return record, "applied-after-provider-retry"

    def execute_with_partial_response(self, step, action, payload=None):
        """Handle a truncated/partial response: treat as uncertain, reconcile."""
        key = f"{step}:{action}"
        if self.is_done(step):
            return self.gateway.lookup(key), "checkpoint"
        # Gateway applies, but caller only receives a partial body (no status).
        self.gateway.apply(key, action, payload)
        partial = {"act": action}  # truncated: no status, no confirmation
        if "status" not in partial:
            found = self.gateway.lookup(key)
            if found is not None:
                self._mark_done(step)
                return found, "reconciled"
        raise RuntimeError("unreachable in the reference harness")

    # -- event / webhook delivery ------------------------------------------
    def deliver_event(self, event_id, action, payload=None):
        """Deliver a callback/webhook: the same event id applies at most once."""
        if event_id in self.seen_event_ids:
            return None, "duplicate-ignored"
        self.seen_event_ids.add(event_id)
        record = self.gateway.apply(f"event:{event_id}", action, payload)
        return record, "applied"

    # -- approvals -----------------------------------------------------------
    def approve(self, approval_id):
        self.approvals.add(approval_id)

    def execute_after_approval(self, approval_id, step, action, payload=None):
        """Run an action only if its approval has arrived; at most once."""
        if approval_id not in self.approvals:
            return None, "waiting-for-approval"
        return self.execute_once(step, action, payload)

    # -- multi-step workflow with crash/resume -------------------------------
    def run_reference_workflow(self, crash_after_step=None):
        """Three-step reference workflow. Optionally crash after a named step."""
        steps = [
            ("reserve", "inventory.reserve"),
            ("charge", "payment.charge"),
            ("notify", "message.send"),
        ]
        results = []
        for step, action in steps:
            record, how = self.execute_once(step, action, {"step": step})
            results.append({"step": step, "action": action, "how": how})
            if crash_after_step == step:
                raise SimulatedCrash(f"simulated worker crash after step {step!r}")
        return results
