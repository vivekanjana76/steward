"""Unit tests for the append-only audit log — safety-critical (CLAUDE.md §9).

Pin the append-only contract, the hash chain's tamper detection, and the
trace_id linkage. Pure and deterministic: a fixed clock, no network, no model
calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from steward.policy import Action, ActionKind, classify
from steward.policy.audit import (
    GENESIS_HASH,
    AuditError,
    AuditRecord,
    InMemoryAuditLog,
    JsonlAuditLog,
    verify_chain,
)

TARGET = "vivekanjana76/steward-demo"
FIXED_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _clock() -> datetime:
    return FIXED_NOW


def _action(kind: ActionKind = ActionKind.POST_ISSUE_COMMENT) -> Action:
    return Action(kind=kind, repo=TARGET, summary=f"test {kind.value}")


def _append(log: InMemoryAuditLog | JsonlAuditLog, trace_id: str = "trace-1") -> AuditRecord:
    action = _action()
    return log.append(
        action=action,
        decision=classify(action, target_repo=TARGET),
        trace_id=trace_id,
    )


class TestAppendOnly:
    def test_records_accumulate_with_monotonic_seq(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        first, second, third = _append(log), _append(log), _append(log)
        assert [r.seq for r in (first, second, third)] == [1, 2, 3]
        assert [r.seq for r in log.records()] == [1, 2, 3]

    def test_store_exposes_no_mutation_surface(self) -> None:
        # Append-only as a contract: no update/delete/remove/clear/pop on
        # either backend's public API.
        for backend in (InMemoryAuditLog, JsonlAuditLog):
            public = {name for name in dir(backend) if not name.startswith("_")}
            assert public == {"append", "records"}

    def test_records_iteration_cannot_mutate_the_log(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        _append(log)
        items = log.records()
        assert list(items)  # consuming the iterator is fine
        assert [r.seq for r in log.records()] == [1]

    def test_record_is_frozen(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        record = _append(log)
        with pytest.raises(ValidationError):
            record.actor = "mallory"  # type: ignore[misc]

    def test_trace_id_is_required(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        action = _action()
        with pytest.raises(ValidationError):
            log.append(
                action=action,
                decision=classify(action, target_repo=TARGET),
                trace_id="",
            )

    def test_defaults_are_safe(self) -> None:
        # A record is a dry-run proposal unless explicitly stated otherwise.
        record = _append(InMemoryAuditLog(clock=_clock))
        assert record.dry_run is True
        assert record.executed is False
        assert record.actor == "steward"


class TestHashChain:
    def test_chain_anchors_at_genesis_and_verifies(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        records = [_append(log) for _ in range(3)]
        assert records[0].prev_hash == GENESIS_HASH
        assert records[1].prev_hash == records[0].entry_hash
        verify_chain(records)

    def test_empty_chain_is_valid(self) -> None:
        verify_chain([])

    def test_rewritten_content_is_detected(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        records = [_append(log) for _ in range(3)]
        forged = records[1].model_copy(update={"actor": "mallory"})
        with pytest.raises(AuditError, match="tampered"):
            verify_chain([records[0], forged, records[2]])

    def test_dropped_record_is_detected(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        records = [_append(log) for _ in range(3)]
        with pytest.raises(AuditError):
            verify_chain([records[0], records[2]])

    def test_reordered_records_are_detected(self) -> None:
        log = InMemoryAuditLog(clock=_clock)
        records = [_append(log) for _ in range(3)]
        with pytest.raises(AuditError):
            verify_chain([records[1], records[0], records[2]])

    def test_decision_outcomes_are_part_of_the_hash(self) -> None:
        # Two logs differing only in the decision produce different hashes —
        # the verdict itself is tamper-evident.
        allow_log = InMemoryAuditLog(clock=_clock)
        deny_log = InMemoryAuditLog(clock=_clock)
        read, merge = _action(ActionKind.READ_ISSUE), _action(ActionKind.MERGE_PR)
        a = allow_log.append(action=read, decision=classify(read, target_repo=TARGET), trace_id="t")
        b = deny_log.append(
            action=merge, decision=classify(merge, target_repo=TARGET), trace_id="t"
        )
        assert a.entry_hash != b.entry_hash


class TestJsonlBackend:
    def test_round_trips_and_verifies_across_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = JsonlAuditLog(path, clock=_clock)
        _append(log, trace_id="trace-a")
        _append(log, trace_id="trace-b")

        reopened = JsonlAuditLog(path, clock=_clock)
        records = list(reopened.records())
        assert [r.trace_id for r in records] == ["trace-a", "trace-b"]
        verify_chain(records)

        third = _append(reopened, trace_id="trace-c")
        assert third.seq == 3
        verify_chain(list(reopened.records()))

    def test_tampered_file_is_rejected_on_open(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = JsonlAuditLog(path, clock=_clock)
        _append(log)
        _append(log)

        lines = path.read_text(encoding="utf-8").splitlines()
        doctored = json.loads(lines[0])
        doctored["actor"] = "mallory"
        lines[0] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(AuditError):
            JsonlAuditLog(path, clock=_clock)

    def test_missing_file_yields_empty_log(self, tmp_path: Path) -> None:
        log = JsonlAuditLog(tmp_path / "absent.jsonl", clock=_clock)
        assert list(log.records()) == []
