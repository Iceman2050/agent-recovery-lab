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
27 passed in 0.13s
```
(8 parametrized scenario tests + scenario aggregates + gateway/runner units +
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
