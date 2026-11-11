# Overlap Gate — agent-recovery-lab vs Agent Flight Recorder (AFR)

Date: 2026-11-11 · Verdict: **PROCEED — no functional overlap; interface-level reuse only.**

## What AFR actually does (evidence read)

1. **Live product page** — https://flightrecorder.getingeniousai.com (fetched 2026-11-11):
   - "Tamper-evident audit trail for AI agents: every action, tool call and decision is
     hash-chained with SHA-256 into an append-only ledger."
   - Ingest: agents POST each action to `/v1/actions` with an API key; fields named on the
     page: `agent_id`, `action_type`, `tool_name`, input/output summaries, metadata.
   - Features: one-click chain verification, incident replay, anomaly alerts (burst,
     first-seen tool, after-hours), Tamper-Seal certificates, audit reports, CSV export (Pro).
   - AFR **records and proves history**. It does not inject failures, does not run recovery
     scenarios, and does not test retry/resume/compensation behaviour.

2. **Fleet source that consumes AFR** — `~/workspace/github-repos-build/agent-bridge/`
   (sibling repo Iceman2050/agent-bridge, built in the same GODMODE v2.0 program):
   - `agent_bridge/core.py::adapt_flight_recorder` requires `agent_id` + `event_type` and
     carries through `event_id`, `summary`, `timestamp`.
   - Fixture `tests/fixtures/recorder-event.json`:
     `{"event_id": "evt_001", "agent_id": "demo-agent", "event_type": "tool.call.completed", "summary": "tool call recorded", "timestamp": "2026-11-10T00:00:01Z"}`
   - So an AFR-compatible exported event is a JSON object with an event id, an agent id,
     a dotted event type (`tool.call.started` / `tool.call.completed` style), a summary
     and an ISO-8601 timestamp. AFR's own ingest shape adds `action_type` / `tool_name` /
     `status`-style fields; both shapes describe the same thing: an ordered action history.

3. **Repo check** — `gh repo list Iceman2050` (2026-11-11): no `agent-recovery-lab` repo
   existed before this build, and no existing repo performs failure injection or recovery
   testing. AFR itself has no standalone public source repo in the list; its source was not
   found as a cleanly importable package under `~/workspace`, so no code coupling is attempted.

## Boundary

| | Agent Flight Recorder | agent-recovery-lab |
|---|---|---|
| Job | Record what an agent **did** (proof) | Test what a workflow **does when things fail** |
| Input | Live agent actions via API | Built-in scenarios, or an exported action history |
| Output | Hash-chained ledger, verification verdicts | Per-scenario pass/fail recovery report |
| Failure injection | None | 8 injected failure modes, in-process only |
| Enforcement / orchestration | None (recording ≠ enforcement) | None (testing ≠ orchestration) |

## Genuine reuse (implemented, not just claimed)

`agent-recovery test --history <action-history.jsonl>` accepts a JSONL export whose lines
are AFR-compatible events (either the `event_type` shape above or AFR's
`action_type`/`status` ingest shape) and **derives recovery test scenarios from the
recorded history**:

- an action recorded as started/initiated with no matching completed/failed record for the
  same `action_id` → an **uncertain-outcome** scenario;
- the same `event_id` (or the same `idempotency_key`) recorded more than once → a
  **duplicate-event** scenario;
- repeated `webhook.*` deliveries of one event → a **repeated-webhook** scenario;
- a record whose status/type says `timeout`/`timed_out` → a **timeout** scenario.

Derived scenarios run against the same isolated in-process harness as the built-in
catalogue. If a history contains no derivable anomaly, the tool says so and derives zero
scenarios — it does not invent passes. This is interface-level reuse via the history
format: honest, decoupled, and it works with any recorder that can export the same shape.
