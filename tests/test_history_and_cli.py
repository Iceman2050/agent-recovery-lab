"""History derivation (the AFR reuse path) and CLI smoke tests."""
import json

from agent_recovery_lab.cli import main
from agent_recovery_lab.history import derive, load_history, run_derived

SAMPLE = [
    {"event_id": "e1", "agent_id": "a", "event_type": "tool.call.started",
     "action_id": "act1", "action_type": "payment.charge"},
    {"event_id": "e2", "agent_id": "a", "event_type": "webhook.received",
     "action_id": "act2", "action_type": "webhook.payment_succeeded"},
    {"event_id": "e2", "agent_id": "a", "event_type": "webhook.received",
     "action_id": "act2", "action_type": "webhook.payment_succeeded"},
    {"event_id": "e3", "agent_id": "a", "event_type": "tool.call.completed",
     "action_id": "act3", "action_type": "message.send"},
]


def _write(tmp_path, rows):
    p = tmp_path / "history.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_derive_uncertain_and_repeated_webhook(tmp_path):
    events = load_history(_write(tmp_path, SAMPLE))
    names = sorted(d["name"] for d in derive(events))
    assert names == ["repeated-webhook", "uncertain-outcome"]


def test_derived_scenarios_pass(tmp_path):
    events = load_history(_write(tmp_path, SAMPLE))
    results = run_derived(events)
    assert len(results) == 2
    assert all(r["passed"] for r in results)


def test_clean_history_derives_nothing(tmp_path):
    clean = [{"event_id": "e9", "agent_id": "a", "event_type": "tool.call.completed",
              "action_id": "act9", "action_type": "message.send"}]
    events = load_history(_write(tmp_path, clean))
    assert derive(events) == []
    assert run_derived(events) == []


def test_afr_ingest_shape_supported(tmp_path):
    rows = [{"agent_id": "a", "action_type": "payment.charge", "status": "started",
             "action_id": "actX", "timestamp": "2026-11-10T00:00:01Z"}]
    events = load_history(_write(tmp_path, rows))
    assert [d["name"] for d in derive(events)] == ["uncertain-outcome"]


def test_cli_doctor(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "scenarios testable (8)" in out
    assert "no network calls" in out


def test_cli_test_all_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["test", "--all"]) == 0
    assert "8/8 scenarios passed" in capsys.readouterr().out
    assert main(["report", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 8 and payload["passed"] == 8


def test_cli_single_scenario(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["test", "--scenario", "timeout"]) == 0
    assert "1/1 scenarios passed" in capsys.readouterr().out


def test_cli_history_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    hist = _write(tmp_path, SAMPLE)
    assert main(["test", "--history", str(hist)]) == 0
    out = capsys.readouterr().out
    assert "uncertain-outcome" in out and "repeated-webhook" in out


def test_cli_report_without_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["report", "--format", "json"]) == 2
