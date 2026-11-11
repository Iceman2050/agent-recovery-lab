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
scenarios testable (8): timeout, duplicate-event, worker-crash, partial-response, repeated-webhook, delayed-approval, provider-interruption, uncertain-outcome
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

8/8 scenarios passed.

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

Internals: a fake action gateway (in-memory only — never real network calls,
payments, messages, or database writes), a workflow runner with
checkpointing, an idempotency-key store, outcome reconciliation (query the
gateway's true state before retrying), and a compensation hook.

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

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q     # scenario assertions + history + CLI smoke tests
```

MIT licensed. Built by Ingenious AI — https://getingeniousai.com
