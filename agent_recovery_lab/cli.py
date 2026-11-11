"""CLI: agent-recovery doctor | test | report.

State: the last `test` run is saved to ./.agent-recovery-last-run.json so
`report` can re-emit it. Nothing here makes network calls.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from . import __version__
from .history import load_history, run_derived
from .scenarios import SCENARIOS, run_all, run_scenario

STATE_FILE = Path(".agent-recovery-last-run.json")
SCOPE_NOTE = ("Scope: this verifies recovery behaviour of the built-in reference harness "
              "and of history-derived scenarios. It does not certify arbitrary external systems.")


def _save(results, source):
    payload = {"tool": "agent-recovery", "version": __version__, "source": source,
               "passed": sum(1 for r in results if r["passed"]), "total": len(results),
               "results": results}
    STATE_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def _print_human(payload):
    for r in payload["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        origin = f" (derived: {r['derived_from']})" if r.get("derived") else ""
        print(f"[{mark}] {r['name']}{origin} — {r['property']}")
        print(f"       side_effects={r['side_effects']} · {r['detail']}")
        for op in r.get("operations") or []:
            from .lifecycle import summary_line
            print(f"       flight-recorder: {summary_line(op)}")
    print(f"\n{payload['passed']}/{payload['total']} scenarios passed.")
    print(SCOPE_NOTE)


def cmd_doctor(_args):
    print(f"agent-recovery {__version__}")
    print(f"python: {sys.version.split()[0]} ({platform.python_implementation()}) on {platform.system()}")
    print("dependencies: none (Python standard library only)")
    print("isolation: in-process fake gateway, in-memory state only; no network calls, "
          "no real payments, no real messages, no real database writes")
    print(f"scenarios testable ({len(SCENARIOS)}): {', '.join(SCENARIOS)}")
    print("acceptance gates (3): lost-ack-after-success, repeated-webhook-callback, worker-interruption")
    print("flight recorder: attempt lifecycle per business operation (created, authorized, started, "
          "result, retry, reconciliation) in AFR record shape, one stable operation ID")
    print("policies: example Auth Gateway policies (retry permission, spend ceiling, "
          "repeated-sensitive approval) in agent_recovery_lab.policies")
    print("failover eligibility: 1 scenario (failover-eligibility) — ambiguous outcomes verdict "
          "RECONCILE or ESCALATE, never auto-replay")
    print("history import: JSONL action history (Agent Flight Recorder-compatible event shape)")
    print("status: OK — everything above is testable locally")
    return 0


def cmd_test(args):
    if args.history:
        events = load_history(args.history)
        results = run_derived(events)
        payload = _save(results, f"history:{args.history}")
        if not results:
            print(f"No recovery scenarios could be derived from {args.history} "
                  f"({len(events)} events read, no derivable anomaly found). Nothing was passed or failed.")
            print(SCOPE_NOTE)
            return 0
    elif args.all or not args.scenario:
        payload = _save(run_all(), "built-in:--all")
    else:
        payload = _save([run_scenario(args.scenario)], f"built-in:{args.scenario}")
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)
    return 0 if payload["passed"] == payload["total"] else 1


def cmd_report(args):
    if not STATE_FILE.exists():
        print("No test run recorded yet. Run `agent-recovery test --all` first.", file=sys.stderr)
        return 2
    payload = json.loads(STATE_FILE.read_text())
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agent-recovery",
                                     description="Failure-injection and recovery-testing toolkit for AI agent workflows.")
    parser.add_argument("--version", action="version", version=f"agent-recovery {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="environment/self check")

    p_test = sub.add_parser("test", help="run recovery scenarios")
    p_test.add_argument("--scenario", choices=sorted(SCENARIOS), help="run one named scenario")
    p_test.add_argument("--all", action="store_true", help="run all built-in scenarios")
    p_test.add_argument("--history", metavar="FILE.jsonl",
                        help="derive and run scenarios from an exported action history (AFR-compatible JSONL)")
    p_test.add_argument("--format", choices=["text", "json"], default="text")

    p_rep = sub.add_parser("report", help="show results of the last run")
    p_rep.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "test":
            return cmd_test(args)
        if args.command == "report":
            return cmd_report(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
