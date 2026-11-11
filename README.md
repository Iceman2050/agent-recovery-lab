# Agent Recovery Lab

**Failure-injection and recovery-testing toolkit for AI agent workflows.**

When an agent workflow calls the outside world, things fail in ways that make
naive retries dangerous: the charge went through but the response timed out,
the webhook arrived three times, the worker died mid-run, the approval came
six hours late. Agent Recovery Lab injects those failures into an isolated,
in-process harness and checks the one question that matters: **is it safe to
retry, resume, or compensate — or would that do the action twice?**

Framework-neutral, zero dependencies, Python standard library only.

This is a **testing/verification layer** for your own operations. It is not an
orchestration framework and does not compete with Temporal, AWS Step
Functions, or LangGraph — it tests recovery behaviour those systems still
leave to you: idempotency, reconciliation, checkpoint/resume, compensation.

## The Agent Execution Assurance family

Agent Recovery Lab is the recovery-testing member of the **Agent Execution
Assurance** family — four parts that cover an agent action end to end:

- **Auth Gateway defines permitted actions** — allowlists/denylists, spend
  caps and envelopes, human approval queues, kill switches: what an agent
  is allowed to do at all.
- **EvalScope verifies procedure + contract** — that the agent followed the
  specified procedure and that tool calls honour their contracts.
- **AgentRecovery tests recovery** (this tool) — what happens when actions
  fail mid-flight: lost acknowledgements, duplicate deliveries, worker
  deaths, provider switches — and whether retrying would do the action twice.
- **Flight Recorder preserves evidence** — the hash-chained, append-only
  record of what actually happened, which recovery reconciles against and
  auditors read afterwards.

The parts are deliberately decoupled: this tool reuses the Flight Recorder's
record *shape* (see below) and the Auth Gateway's policy *patterns*, and
imports neither's code.

## Install

```bash
pip install -e .        # from a clone of this repo
agent-recovery doctor
```

Requires Python 3.10+. No third-party dependencies.

## Usage (real output, v0.1.0)

```console
$ agent-recovery doctor
agent-recovery 0.1.0
python: 3.12.3 (CPython) on Linux
dependencies: none (Python standard library only)
isolation: in-process fake gateway, in-memory state only; no network calls, no real payments, no real messages, no real database writes
scenarios testable (11): timeout, duplicate-event, worker-crash, partial-response, repeated-webhook, delayed-approval, provider-interruption, uncertain-outcome, lost-ack-after-success, worker-interruption, failover-eligibility
acceptance gates (3): lost-ack-after-success, repeated-webhook-callback, worker-interruption
flight recorder: attempt lifecycle per business operation (created, authorized, started, result, retry, reconciliation) in AFR record shape, one stable operation ID
policies: example Auth Gateway policies (retry permission, spend ceiling, repeated-sensitive approval) in agent_recovery_lab.policies
failover eligibility: 1 scenario (failover-eligibility) — ambiguous outcomes verdict RECONCILE or ESCALATE, never auto-replay
history import: JSONL action history (Agent Flight Recorder-compatible event shape)
status: OK — everything above is testable locally

$ agent-recovery test --all
[PASS] timeout — A timed-out action is reconciled, not blind-retried: exactly one side effect.
[PASS] duplicate-event — The same callback delivered twice is applied once.
[PASS] worker-crash — Crash mid-workflow, resume from checkpoint: no step is repeated.
[PASS] partial-response — A partial/truncated response is treated as uncertain and reconciled: exactly one side effect.
[PASS] repeated-webhook — A webhook redelivered repeatedly (provider retry storm) is applied once per event/key.
[PASS] delayed-approval — An action gated on human approval runs zero times before approval and exactly once after a delayed approval.
[PASS] provider-interruption — When the provider fails BEFORE applying, a retry is safe and lands exactly one side effect.
[PASS] uncertain-outcome — An uncertain external outcome is resolved by querying true state before retrying or compensating.
[PASS] lost-ack-after-success — Lost-ack-after-success: recovery must not create a second business operation when idempotency holds.
[PASS] worker-interruption — Worker killed after starting an external operation but before recording completion: recovery reconciles from evidence, never blindly re-executes.
[PASS] failover-eligibility — Before a provider switch: retry-eligible, provider approved, capability compatible, policy permits, state known — an ambiguous outcome verdicts RECONCILE or ESCALATE, never auto-replay.

11/11 scenarios passed.

$ agent-recovery test --scenario timeout      # one scenario
$ agent-recovery report --format json         # machine-readable last run
```

`test` exits 0 only when every scenario it ran passed; results are saved to
`.agent-recovery-last-run.json` for `report`.

## Scenario catalogue

| Scenario | Failure injected | Safety property asserted |
|---|---|---|
| `timeout` | Gateway applies the action, response is lost | Runner reconciles via true-state lookup instead of blind-retrying → exactly 1 side effect |
| `duplicate-event` | Same callback delivered twice | Applied once (event-id dedupe) |
| `worker-crash` | Worker crashes mid-workflow | Resume from checkpoint → no step repeated, each action applied once |
| `partial-response` | Truncated response body (no status) | Treated as uncertain, reconciled → exactly 1 side effect |
| `repeated-webhook` | Same webhook delivered 5× + keyed retries | One effect per event id and per idempotency key |
| `delayed-approval` | Human approval arrives late, then duplicated | 0 runs before approval, exactly 1 after |
| `provider-interruption` | Provider fails *before* applying | Retry is safe → exactly 1 side effect |
| `uncertain-outcome` | Action applied, acknowledgement lost | Outcome resolved by querying true state before retry/compensate; compensation runs at most once |
| `lost-ack-after-success` | Operation succeeds, acknowledgement lost, recovery attempt follows | **Acceptance (a)** — recovery reconciles, no second business operation; lifecycle records one operation, 2 attempts, exactly 1 side effect |
| `worker-interruption` | Worker killed *after* starting an external operation, *before* durable completion is recorded | **Acceptance (c)** — recovery reconciles from evidence (true-state lookup) instead of blindly re-executing → exactly 1 side effect |
| `failover-eligibility` | Provider switch proposed, incl. with an ambiguous outcome | All five eligibility checks pass → `ELIGIBLE`; a hard check fails → `NOT_ELIGIBLE`; ambiguous outcome → `RECONCILE` or `ESCALATE`, never auto-replay |

Internals: a fake action gateway (in-memory only — never real network calls,
payments, messages, or database writes), a workflow runner with
checkpointing, an idempotency-key store, outcome reconciliation (query the
gateway's true state before retrying), and a compensation hook.

## The acceptance gate

Three scenarios form the acceptance gate (run them via
`agent_recovery_lab.acceptance.run_acceptance()` or the test suite):

- **(a) Lost-ack-after-success** — the operation succeeds, the
  acknowledgement is lost, and the recovery attempt must not create a
  second business operation. The honest counter-case ships with it: the
  same run against a gateway that ignores idempotency keys
  (`NonIdempotentGateway`) creates the duplicate — and the harness reports
  that run as a **failure** (2 side effects, `passed: false`), never a pass.
- **(b) Repeated webhook/callback** — the same webhook/callback delivered
  more than once must not duplicate the business operation (`repeated-webhook`
  + `duplicate-event`).
- **(c) Worker interruption** — a worker killed after starting an external
  operation but before durable completion is recorded; recovery reconciles
  from evidence instead of blindly re-executing (`worker-interruption`,
  distinct from `worker-crash`, which crashes between checkpointed steps).

## Flight Recorder attempt lifecycle

Acceptance scenarios (a) and (c) record every attempt in the real Agent
Flight Recorder record shape (`seq`, `created_at`, `action_type`,
`tool_name`, `metadata`, `prev_hash`/`hash` chain) as
created → authorized → started → result → retry → reconciliation, all tied
by **one stable business-operation ID** in `metadata.request_id` — AFR's own
decision/outcome pairing convention. The report output states it the way an
auditor reads it:

```console
$ agent-recovery test --scenario lost-ack-after-success
[PASS] lost-ack-after-success — Lost-ack-after-success: recovery must not create a second business operation when idempotency holds.
       side_effects=1 · operation op_pay_001: 1 operation, 2 attempts, 6 lifecycle records (operation.created, operation.authorized, operation.started, operation.result, operation.retry, operation.reconciliation); side_effects=1; reconciliation found the applied charge, no re-execution.
       flight-recorder: operation op_pay_001: 1 operation, 2 attempts, 6 lifecycle records (operation.created, operation.authorized, operation.started, operation.result, operation.retry, operation.reconciliation)
```

`examples/lifecycle-operation.jsonl` is a real exported lifecycle (one
operation, 2 attempts, hash chain verifiable with
`agent_recovery_lab.lifecycle.verify_chain`), and
`lifecycle.group_records()` groups any AFR-shaped export — including raw
decision/outcome record pairs — into one-operation summaries.

## Auth Gateway policy examples

`agent_recovery_lab.policies` ships reusable example policies patterned on
the real Agent Auth Gateway (patterns reused, code not imported), each with
tests:

- **Retry permission** (`RetryPolicy`) — denylist and destructive patterns
  deny, a confirmed-applied action denies (a retry would duplicate it), an
  unknown outcome verdicts `reconcile-first` (the gateway connector's
  presence-check-before-retry discipline), attempts are bounded with
  backoff, an unlisted action escalates to a human.
- **Spend ceiling** (`SpendCeilingPolicy`) — the gateway's spendguard
  envelope: `max_cents` over a rolling window, a per-transaction approval
  threshold, hold-by-default with standing approval only for an
  allowlisted source under threshold inside the envelope; daily/monthly
  caps deny outright when a call would breach them.
- **Repeated sensitive action** (`RepeatedSensitiveApprovalPolicy`) — a
  sensitive action needs a human approval, and a *repeat* needs a **fresh**
  approval: the first approval never carries over and re-presenting the
  same approval does not count (spendguard's "holds are owner-released,
  never auto-released" rule, applied to repeats).

## Failover eligibility (one test, folded in)

`failover-eligibility` is the single failover test folded in from the
deferred FailoverGuard — there is intentionally no failover product here.
Before any provider switch it checks: retry-eligible? · provider approved?
· capability compatible? · spend/data policy permits? · workflow state
known? An ambiguous external action (outcome unknown) verdicts `RECONCILE`
or `ESCALATE` — never auto-replay — and that rule is checked before every
other check, so approvals cannot launder an unknown outcome into an
eligible switch.

## Test from your own action history (Agent Flight Recorder path)

Export an action history as JSONL — one event per line, in the Agent Flight
Recorder-compatible shape (`event_id`, `agent_id`, `event_type` such as
`tool.call.started` / `tool.call.completed`, `action_id`, `timestamp`; AFR's
`action_type`/`status` ingest shape is also accepted) — and derive recovery
scenarios from what actually happened:

```console
$ agent-recovery test --history examples/sample-history.jsonl
[PASS] repeated-webhook (derived: event evt_102 recorded 2x) — History-derived repeated-webhook scenario holds its safety property.
[PASS] uncertain-outcome (derived: action act_pay_1 started but never completed) — History-derived uncertain-outcome scenario holds its safety property.

2/2 scenarios passed.
```

Derivation rules: started-but-never-completed action → `uncertain-outcome`;
same `event_id`/`idempotency_key` recorded more than once → `duplicate-event`;
repeated `webhook.*` deliveries → `repeated-webhook`; a recorded timeout →
`timeout`. A history with no derivable anomaly derives **zero** scenarios and
says so — passes are never invented. See `OVERLAP-GATE.md` for how this
relates to Agent Flight Recorder (it records history; this tool tests
recovery against it — interface-level reuse, no code coupling).

## Limitations — stated plainly

- This tool verifies recovery behaviour of its **built-in reference harness**
  and of **history-derived scenarios**. It does **not** certify arbitrary
  external systems, and a passing run never means a system is "safe" — it
  means these named scenarios held their named properties, in this harness.
- Not tested: real network partitions, real provider semantics, distributed
  consensus, clock skew, multi-process races, or your production code paths.
  Pointing the history importer at a recording shows what *did* happen; it
  cannot prove what *would* happen in your stack.
- The simulation is single-process and in-memory by design, so it can never
  touch a real service — and also cannot reproduce real-service behaviour.
- The policy examples are reference patterns distilled from the Auth
  Gateway's production rules, not the gateway itself: they decide, they do
  not enforce, hold queues, or move money. The failover check is a single
  eligibility test, not a failover system.

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q     # scenario assertions + history + CLI smoke tests
```

MIT licensed. Built by Ingenious AI — https://getingeniousai.com
