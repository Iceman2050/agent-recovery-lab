"""In-process fake action gateway.

Isolation contract: this gateway holds in-memory state ONLY. It performs no
network calls, no real payments, no real messages, no real database writes.
It exists so recovery behaviour can be tested without touching real services.
"""
from __future__ import annotations


class ProviderUnavailable(Exception):
    """Raised when the simulated provider is interrupted before applying."""


class ResponseLost(Exception):
    """Raised when the provider applied the action but the response was lost."""


class FakeGateway:
    def __init__(self):
        self._effects = []          # ordered list of applied side effects (dicts)
        self._by_key = {}           # idempotency_key -> effect record
        self._compensations = []    # compensation records
        self.interrupt_next = False  # provider-interruption fault switch

    def apply(self, idempotency_key, action, payload=None):
        """Apply an action exactly once per idempotency key.

        Returns the stored effect record. A second call with the same key
        returns the original record and applies nothing new.
        """
        if self.interrupt_next:
            self.interrupt_next = False
            raise ProviderUnavailable("simulated provider interruption (nothing applied)")
        if idempotency_key in self._by_key:
            return self._by_key[idempotency_key]
        record = {
            "seq": len(self._effects) + 1,
            "idempotency_key": idempotency_key,
            "action": action,
            "payload": dict(payload or {}),
            "status": "applied",
        }
        self._effects.append(record)
        self._by_key[idempotency_key] = record
        return record

    def apply_then_lose_response(self, idempotency_key, action, payload=None):
        """Apply the action, then simulate the response being lost."""
        self.apply(idempotency_key, action, payload)
        raise ResponseLost("action applied but the response never arrived")

    def lookup(self, idempotency_key):
        """Reconciliation query: return the true state for a key, or None."""
        return self._by_key.get(idempotency_key)

    def compensate(self, idempotency_key, reason="compensated"):
        """Compensation hook: mark an applied effect compensated, at most once."""
        record = self._by_key.get(idempotency_key)
        if record is None or record["status"] == "compensated":
            return None
        record["status"] = "compensated"
        entry = {"idempotency_key": idempotency_key, "reason": reason}
        self._compensations.append(entry)
        return entry

    @property
    def effects(self):
        return list(self._effects)

    @property
    def compensations(self):
        return list(self._compensations)

    def effect_count(self, action=None):
        if action is None:
            return len(self._effects)
        return sum(1 for e in self._effects if e["action"] == action)
