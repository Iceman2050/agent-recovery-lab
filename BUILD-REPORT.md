# Build Report — agent-recovery-lab v0.1.0 (2026-11-11)

## Overlap gate
Verdict: PROCEED — no functional overlap with Agent Flight Recorder. AFR records/proves
history (hash-chained ledger, /v1/actions ingest); this tool injects failures and tests
recovery. Reuse is interface-level via the AFR-compatible JSONL history format.
Full evidence: OVERLAP-GATE.md.

## Build
- Location: ~/workspace/github-repos-build/agent-recovery-lab/ (durable, not /tmp)
- Python 3.10+, standard library only, zero dependencies.
- Coding discipline: Karpathy Skills (~/workspace/design-resources/andrej-karpathy-skills/CLAUDE.md)
  consumed before building — minimum code, no speculative features, goal-driven verification.
- Attribution check: grep for "with Muse" and "2HCQH1" over the whole tree → 0 matches.

## Test suite
```
$ python -m pytest -q
...........................                                              [100%]
28 passed
```
(8 parametrized scenario tests + 1 real-AFR-record-shape test + scenario aggregates + gateway/runner units +
history derivation incl. AFR ingest shape + CLI smoke tests.)

## Real run transcript (venv install, Python 3.12.3)
```
$ agent-recovery doctor
agent-recovery 0.1.0
python: 3.12.3 (CPython) on Linux
dependencies: none (Python standard library only)
isolation: in-process fake gateway, in-memory state only; no network calls, no real payments, no real messages, no real database writes
scenarios testable (8): timeout, duplicate-event, worker-crash, partial-response, repeated-webhook, delayed-approval, provider-interruption, uncertain-outcome
history import: JSONL action history (Agent Flight Recorder-compatible event shape)
status: OK — everything above is testable locally

$ agent-recovery test --all        → 8/8 scenarios passed, exit 0
[PASS] timeout · [PASS] duplicate-event · [PASS] worker-crash · [PASS] partial-response
[PASS] repeated-webhook · [PASS] delayed-approval · [PASS] provider-interruption · [PASS] uncertain-outcome

$ agent-recovery test --history examples/sample-history.jsonl   → 2/2 derived passed, exit 0
[PASS] repeated-webhook (derived: event evt_102 recorded 2x)
[PASS] uncertain-outcome (derived: action act_pay_1 started but never completed)

$ agent-recovery report --format json  → {"passed": 8, "total": 8, ...} for the --all run
```

## Ship
- Repo: https://github.com/Iceman2050/agent-recovery-lab (public)
- Release: v0.1.0
- CI: GitHub Actions, pytest on Python 3.10 / 3.11 / 3.12 (no 3.9).
- Topics: see TOPICS.md; applied list read back after creation (recorded in the ship log).

---

## REVISED-SPEC EXTENSION — STAGED LOCALLY, UPLOAD HELD PENDING ALDO'S APPROVAL

Date: 2026-11-11 · Spec: GODMODE Weekly Intel revision (AgentRecovery Lab =
Priority 1 build). **Nothing in this section has been pushed or uploaded —
local edits and local commits only, per Aldo's 2026-11-11 10:41 CST upload
hold.** All pre-existing functionality is intact: the original 8 scenarios,
the AFR history importer and the CLI behave exactly as before (suite grew
28 → 61 tests, all green; the two hard-coded "8 scenario" test assertions
were updated to the new catalogue size of 11).

### Audit map (spec item → state before this extension)

| Spec item | Before | Action |
|---|---|---|
| 1(a) Lost-ack-after-success | PARTIAL — `timeout` + `uncertain-outcome` exercised reconcile-not-retry, but no acceptance name, no stable operation ID, no lifecycle, no counter-case | Formalized as `lost-ack-after-success` + honest counter-case (below) |
| 1(b) Repeated webhook/callback | PRESENT — `repeated-webhook` (5× delivery + keyed retries) + `duplicate-event` | Mapped into acceptance gate (b) unchanged |
| 1(c) Worker interruption | PARTIAL — `worker-crash` crashes *between* checkpointed steps; the after-start/before-durable-record window was not covered | New `worker-interruption` scenario |
| 2 Flight Recorder attempt lifecycle | MISSING — importer understood the AFR shape but nothing recorded or reported attempts per operation | New `lifecycle.py` (recorder + grouping + hash-chain verify) |
| 3 Auth Gateway policy examples | PARTIAL — `delayed-approval` embodies one approval rule in a scenario; no reusable policies | New `policies.py`: RetryPolicy, SpendCeilingPolicy, RepeatedSensitiveApprovalPolicy (+ `EXAMPLE_POLICIES`) |
| 4 Failover-eligibility (one test) | MISSING | New `failover.py`: one scenario, 9 fixtures |
| 5 README umbrella framing | MISSING | README: Agent Execution Assurance family section + new sections |

Gateway patterns were read from the real source at
`~/workspace/platforms/agent-auth-gateway/` and reused as patterns (no code
imported): `app/spendguard.py` (envelope max_cents/24h, approval threshold,
hold-by-default, standing approval, never-auto-release), `app/main.py::
_decide_action` + `app/dual_approval.py` PolicyJudge (kill switch →
denylist → daily/monthly caps deny → allowlist escalate; destructive
patterns deny), `app/connector.py` (presence-check BEFORE any retry,
backoff [5, 30, 120, 600, 900]s, ambiguous 2xx stays pending).

### New suite

```
$ python3 -m pytest -q
.............................................................            [100%]
61 passed in 0.19s
```
(28 pre-existing + 33 new: +3 parametrized catalogue scenarios, acceptance 5,
lifecycle 6, policies 13, failover 6. History/CLI tests updated 8 → 11.)

### Scenario-by-scenario evidence (real runs, 2026-11-11)

Acceptance gate (`agent_recovery_lab.acceptance.run_acceptance()` → 3/3 gates passed):

- **(a) lost-ack-after-success → PASS.** `[PASS] lost-ack-after-success —
  side_effects=1 · operation op_pay_001: 1 operation, 2 attempts, 6 lifecycle
  records (operation.created, operation.authorized, operation.started,
  operation.result, operation.retry, operation.reconciliation);
  reconciliation found the applied charge, no re-execution.`
- **(a) counter-case → reported as FAILURE (as required).** Same discipline
  against `NonIdempotentGateway` (idempotency absent/broken): `passed=false,
  side_effects=2` — "reconciliation MISSED (idempotency broken downstream),
  retry duplicated the operation." The duplicate is created and surfaced;
  it is never reported as a pass, and gate (a) itself fails if it ever is.
- **(b) repeated-webhook-callback → PASS.** `repeated-webhook`: same webhook
  delivered 5× plus 2 keyed retries, one effect per event id and per key
  (side_effects=2 = one per distinct event/key); `duplicate-event`: evt_42
  delivered twice, applied once.
- **(c) worker-interruption → PASS.** `side_effects=1 · operation
  op_msg_001: 1 operation, 2 attempts, 5 lifecycle records (operation.created,
  operation.authorized, operation.started, operation.retry,
  operation.reconciliation); effect existed at crash, checkpoint had no
  completion record, recovery lookup() found it and marked done without
  re-applying.`

Failover eligibility (`failover-eligibility` scenario, 9 fixtures, all
verdicts matched): all-clear → ELIGIBLE · ambiguous-outcome-reconcilable →
RECONCILE · ambiguous-outcome-not-reconcilable → ESCALATE · state-unknown →
RECONCILE · provider-not-approved → NOT_ELIGIBLE · capability-incompatible →
NOT_ELIGIBLE · policy-forbids → NOT_ELIGIBLE · not-retry-eligible →
NOT_ELIGIBLE · ambiguous-beats-approvals → RECONCILE. Ambiguous outcomes
never verdict ELIGIBLE (auto-replay) — asserted as its own check.

Flight Recorder lifecycle: records are real AFR stored shape (`seq`,
`created_at`, `action_type`, `tool_name`, `metadata.request_id` =
operation ID, `metadata.attempt`, `prev_hash`/`hash` SHA-256 chain).
`examples/lifecycle-operation.jsonl` is a real exported lifecycle:
`group_records()` reads it back as exactly 1 operation (`op_pay_001`),
2 attempts, 6 records, chain verifies; tampering with any record breaks
`verify_chain` (tested). The same grouping reads a raw AFR
decision/outcome pair sharing `metadata.request_id` as one operation.

Policy examples (real verdicts): RetryPolicy — `unknown` outcome →
`reconcile-first`, confirmed `not_applied` → `allow`, `applied` → `deny`,
denylisted/destructive/kill-switch/over-cap → `deny`, unlisted → `escalate`.
SpendCeilingPolicy — 400¢ standing → `approved`; 600¢ (≥ 500¢ threshold)
without holder approval → `hold [over_approval_threshold,
no_holder_approval]`; envelope exhaustion → `hold`; daily-cap breach →
`deny`. RepeatedSensitiveApprovalPolicy — first `payment.charge` without
approval → `require_approval`; with `appr_1` → `approved`; repeat with the
same `appr_1` → `require_approval` (not fresh); repeat with fresh `appr_2`
→ `approved`.

Full catalogue: `agent-recovery test --all` → **11/11 scenarios passed**,
exit 0; `--history examples/sample-history.jsonl` still derives 2/2.

### Files changed/added
- Added: `agent_recovery_lab/lifecycle.py`, `agent_recovery_lab/policies.py`,
  `agent_recovery_lab/failover.py`, `agent_recovery_lab/acceptance.py`,
  `examples/lifecycle-operation.jsonl`, `tests/test_acceptance.py`,
  `tests/test_lifecycle.py`, `tests/test_policies.py`, `tests/test_failover.py`.
- Edited (additive only): `agent_recovery_lab/scenarios.py` (3 new
  scenarios + `run_lost_ack` evaluator), `agent_recovery_lab/gateway.py`
  (`NonIdempotentGateway` fault fixture; `FakeGateway` untouched),
  `agent_recovery_lab/cli.py` (doctor lines + flight-recorder line in
  scenario output), `README.md`, `tests/test_scenarios.py`,
  `tests/test_history_and_cli.py` (catalogue-size assertions 8 → 11).
- Attribution check: grep for "with Muse" / "2HCQH1" over all source,
  tests and examples → 0 matches (the only repo-wide hits are the quoted
  search terms inside this report's own check lines).

