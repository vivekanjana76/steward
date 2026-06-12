"""Append-only audit log: every proposed or executed action leaves a record.

Every action Steward proposes or executes — including dry-runs and denials —
is recorded so any decision can be replayed and audited (CLAUDE.md §11). Each
record carries the ``trace_id`` minted by :mod:`steward.observability`, so an
audit entry links directly to its Langfuse trace.

Tamper resistance is structural:

* Records are **append-only**: the store exposes ``append`` and read access,
  nothing else — there is no update or delete, and records themselves are
  frozen Pydantic models.
* Records form a **hash chain**: each entry hashes its canonical content plus
  the previous entry's hash, anchored at :data:`GENESIS_HASH`. Re-writing,
  re-ordering, or dropping any historical record breaks
  :func:`verify_chain`.

Two backends ship: :class:`InMemoryAuditLog` (tests, ephemeral runs) and
:class:`JsonlAuditLog` (one canonical JSON line per record, reload-safe), both
behind the structural :class:`AuditLog` protocol so callers never depend on a
concrete store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from steward.policy.engine import Action, PolicyDecision

# The chain anchor for the first record (sequence 1).
GENESIS_HASH = "0" * 64

# The actor name Steward uses for its own autonomous decisions; humans appear
# as ``human:<login>`` when they approve/reject (issue #11).
STEWARD_ACTOR = "steward"


class AuditError(RuntimeError):
    """Raised when the audit chain is invalid or a record cannot be appended."""


class AuditRecord(BaseModel):
    """One immutable audit entry.

    ``executed`` distinguishes a proposal (or dry-run, or denial) from an
    action that actually mutated the world; ``dry_run`` mirrors the global
    safety default (CLAUDE.md §5). ``entry_hash`` commits to the record's
    content and to ``prev_hash``, forming the chain.
    """

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1)
    timestamp: datetime
    trace_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: Action
    decision: PolicyDecision
    dry_run: bool
    executed: bool
    note: str | None = None
    prev_hash: str = Field(min_length=64, max_length=64)
    entry_hash: str = Field(min_length=64, max_length=64)


def _content_digest(record: AuditRecord) -> str:
    """Hash everything in ``record`` except ``entry_hash`` itself."""
    content = record.model_dump(mode="json", exclude={"entry_hash"})
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_chain(records: Sequence[AuditRecord]) -> None:
    """Validate the hash chain over ``records``; raise :class:`AuditError` if broken.

    Detects re-written content, re-ordered entries, gaps in the sequence, and
    a forged anchor. An empty log is trivially valid.
    """
    prev_hash = GENESIS_HASH
    for position, record in enumerate(records, start=1):
        if record.seq != position:
            raise AuditError(
                f"sequence break at position {position}: record claims seq {record.seq}"
            )
        if record.prev_hash != prev_hash:
            raise AuditError(f"chain break at seq {record.seq}: prev_hash mismatch")
        if record.entry_hash != _content_digest(record):
            raise AuditError(f"content tampered at seq {record.seq}: entry_hash mismatch")
        prev_hash = record.entry_hash


class AuditLog(Protocol):
    """The append-only surface every audit backend exposes.

    Deliberately minimal: append one record, iterate records. No update, no
    delete — append-only is the contract, not a convention.
    """

    def append(
        self,
        *,
        action: Action,
        decision: PolicyDecision,
        trace_id: str,
        actor: str = STEWARD_ACTOR,
        dry_run: bool = True,
        executed: bool = False,
        note: str | None = None,
    ) -> AuditRecord:
        """Append one record and return it."""
        ...

    def records(self) -> Iterator[AuditRecord]:
        """Iterate all records in append order."""
        ...


class _ChainBuilder:
    """Shared append logic: sequence, timestamp, and hash-chain computation."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(
        self,
        *,
        seq: int,
        prev_hash: str,
        action: Action,
        decision: PolicyDecision,
        trace_id: str,
        actor: str,
        dry_run: bool,
        executed: bool,
        note: str | None,
    ) -> AuditRecord:
        unsealed = AuditRecord(
            seq=seq,
            timestamp=self._clock(),
            trace_id=trace_id,
            actor=actor,
            action=action,
            decision=decision,
            dry_run=dry_run,
            executed=executed,
            note=note,
            prev_hash=prev_hash,
            entry_hash=GENESIS_HASH,  # placeholder, replaced by the real digest
        )
        return unsealed.model_copy(update={"entry_hash": _content_digest(unsealed)})


class InMemoryAuditLog:
    """An in-process audit log for tests and ephemeral runs."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._records: list[AuditRecord] = []
        self._builder = _ChainBuilder(clock)

    def append(
        self,
        *,
        action: Action,
        decision: PolicyDecision,
        trace_id: str,
        actor: str = STEWARD_ACTOR,
        dry_run: bool = True,
        executed: bool = False,
        note: str | None = None,
    ) -> AuditRecord:
        """Append one record; see :class:`AuditLog`."""
        prev_hash = self._records[-1].entry_hash if self._records else GENESIS_HASH
        record = self._builder.build(
            seq=len(self._records) + 1,
            prev_hash=prev_hash,
            action=action,
            decision=decision,
            trace_id=trace_id,
            actor=actor,
            dry_run=dry_run,
            executed=executed,
            note=note,
        )
        self._records.append(record)
        return record

    def records(self) -> Iterator[AuditRecord]:
        """Iterate all records in append order."""
        return iter(tuple(self._records))


class JsonlAuditLog:
    """A durable audit log: one canonical JSON line per record.

    On construction the existing file (if any) is loaded and its chain
    verified, so a tampered log is detected before anything new is appended.
    """

    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._path = path
        self._builder = _ChainBuilder(clock)
        self._seq = 0
        self._last_hash = GENESIS_HASH
        if path.exists():
            existing = list(self.records())
            verify_chain(existing)
            if existing:
                self._seq = existing[-1].seq
                self._last_hash = existing[-1].entry_hash

    def append(
        self,
        *,
        action: Action,
        decision: PolicyDecision,
        trace_id: str,
        actor: str = STEWARD_ACTOR,
        dry_run: bool = True,
        executed: bool = False,
        note: str | None = None,
    ) -> AuditRecord:
        """Append one record; see :class:`AuditLog`."""
        record = self._builder.build(
            seq=self._seq + 1,
            prev_hash=self._last_hash,
            action=action,
            decision=decision,
            trace_id=trace_id,
            actor=actor,
            dry_run=dry_run,
            executed=executed,
            note=note,
        )
        line = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        self._seq = record.seq
        self._last_hash = record.entry_hash
        return record

    def records(self) -> Iterator[AuditRecord]:
        """Iterate all records in file order."""
        if not self._path.exists():
            return iter(())
        with self._path.open("r", encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        return iter(tuple(AuditRecord.model_validate_json(line) for line in lines))
