"""Flight Recorder attempt lifecycle: one operation, N attempts, AFR shape."""
import json
from pathlib import Path

from agent_recovery_lab.lifecycle import (FlightRecorder, group_records,
                                          summary_line, verify_chain)

EXAMPLE = Path(__file__).parent.parent / "examples" / "lifecycle-operation.jsonl"


def _lost_ack_recorder():
    rec = FlightRecorder()
    rec.create("op_1", "payment.charge")
    rec.authorize("op_1")
    rec.start("op_1")
    rec.result("op_1", "ack-lost")
    rec.retry("op_1")
    rec.reconcile("op_1", "found-applied-no-reexecution")
    return rec


def test_lifecycle_stages_in_order_under_one_operation_id():
    rec = _lost_ack_recorder()
    stages = [r["metadata"]["stage"] for r in rec.records]
    assert stages == ["created", "authorized", "started", "result", "retry", "reconciliation"]
    assert {r["metadata"]["request_id"] for r in rec.records} == {"op_1"}
    assert {r["metadata"]["operation_id"] for r in rec.records} == {"op_1"}


def test_lifecycle_records_use_real_afr_shape():
    rec = _lost_ack_recorder()
    for r in rec.records:
        assert {"seq", "created_at", "action_type", "tool_name",
                "metadata", "prev_hash", "hash"} <= set(r)
    assert [r["seq"] for r in rec.records] == [1, 2, 3, 4, 5, 6]


def test_one_operation_many_attempts_summary():
    summary = _lost_ack_recorder().summary("op_1")
    assert summary["attempts"] == 2 and summary["records"] == 6
    line = summary_line(summary)
    assert "1 operation, 2 attempts" in line


def test_hash_chain_verifies_and_tampering_breaks_it():
    rec = _lost_ack_recorder()
    assert verify_chain(rec.records)
    tampered = [dict(r) for r in rec.records]
    tampered[2] = {**tampered[2], "action_type": "operation.forged"}
    assert not verify_chain(tampered)


def test_group_records_on_real_afr_decision_outcome_shape():
    # AFR's real pairing: decision + outcome share metadata.request_id.
    rows = [
        {"seq": 1, "created_at": "2026-11-10T00:00:01Z", "action_type": "gateway_decision",
         "tool_name": "refund", "metadata": {"request_id": "req_9"}, "prev_hash": "a", "hash": "b"},
        {"seq": 2, "created_at": "2026-11-10T00:00:02Z", "action_type": "refund_outcome",
         "tool_name": "refund", "metadata": {"request_id": "req_9"}, "prev_hash": "b", "hash": "c"},
        {"seq": 3, "created_at": "2026-11-10T00:00:03Z", "action_type": "gateway_decision",
         "tool_name": "refund", "metadata": {"request_id": "req_10"}, "prev_hash": "c", "hash": "d"},
    ]
    summaries = group_records(rows)
    assert [s["operation_id"] for s in summaries] == ["req_9", "req_10"]
    assert summaries[0]["records"] == 2 and summaries[0]["attempts"] == 1


def test_exported_example_file_groups_to_one_operation_two_attempts():
    records = [json.loads(line) for line in EXAMPLE.read_text().splitlines() if line.strip()]
    summaries = group_records(records)
    assert len(summaries) == 1
    assert summaries[0]["operation_id"] == "op_pay_001"
    assert summaries[0]["attempts"] == 2
    assert verify_chain(records)
