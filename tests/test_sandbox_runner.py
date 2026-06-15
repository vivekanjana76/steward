"""Unit tests for the sandbox runner (issue #13).

The runner's logic — request validation, timing, verdict mapping, fault
normalization — is exercised against an injected fake backend, so these tests
are fully deterministic and need no Docker.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from steward.sandbox.runner import (
    ContainerRun,
    SandboxError,
    SandboxRunner,
    SandboxSpec,
)


class FakeBackend:
    """A backend that returns a canned outcome, or raises, and records the spec."""

    def __init__(self, outcome: ContainerRun | None = None, *, raises: Exception | None = None):
        self._outcome = outcome
        self._raises = raises
        self.last_spec: SandboxSpec | None = None

    def run(self, spec: SandboxSpec) -> ContainerRun:
        self.last_spec = spec
        if self._raises is not None:
            raise self._raises
        assert self._outcome is not None
        return self._outcome


def _spec(repo: Path, command: str = "pytest -q") -> SandboxSpec:
    return SandboxSpec(image="python:3.12-slim", command=command, repo_path=repo)


def _ticking_clock(values: list[float]) -> Callable[[], float]:
    it: Iterator[float] = iter(values)
    return lambda: next(it)


def test_exit_zero_is_passed(tmp_path: Path) -> None:
    backend = FakeBackend(ContainerRun(exit_code=0, stdout="1 passed", stderr="", timed_out=False))
    result = SandboxRunner(backend).run_tests(_spec(tmp_path))
    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout == "1 passed"


def test_nonzero_exit_is_failed_with_logs(tmp_path: Path) -> None:
    backend = FakeBackend(
        ContainerRun(exit_code=1, stdout="1 failed", stderr="AssertionError", timed_out=False)
    )
    result = SandboxRunner(backend).run_tests(_spec(tmp_path))
    assert result.passed is False
    assert result.exit_code == 1
    assert "AssertionError" in result.stderr


def test_timeout_is_not_passed(tmp_path: Path) -> None:
    backend = FakeBackend(ContainerRun(exit_code=None, stdout="", stderr="", timed_out=True))
    result = SandboxRunner(backend).run_tests(_spec(tmp_path))
    assert result.passed is False
    assert result.timed_out is True
    assert result.exit_code is None


def test_missing_repo_path_raises(tmp_path: Path) -> None:
    backend = FakeBackend(ContainerRun(exit_code=0, stdout="", stderr="", timed_out=False))
    missing = tmp_path / "nope"
    with pytest.raises(SandboxError, match="not a directory"):
        SandboxRunner(backend).run_tests(_spec(missing))


def test_backend_fault_is_normalized(tmp_path: Path) -> None:
    backend = FakeBackend(raises=RuntimeError("daemon down"))
    with pytest.raises(SandboxError, match="sandbox backend failed: daemon down"):
        SandboxRunner(backend).run_tests(_spec(tmp_path))


def test_duration_is_measured(tmp_path: Path) -> None:
    backend = FakeBackend(ContainerRun(exit_code=0, stdout="", stderr="", timed_out=False))
    runner = SandboxRunner(backend, clock=_ticking_clock([10.0, 12.5]))
    result = runner.run_tests(_spec(tmp_path))
    assert result.duration_s == pytest.approx(2.5)


def test_spec_defaults_are_isolated() -> None:
    spec = SandboxSpec(image="img", command="pytest", repo_path=Path("."))
    assert spec.network_disabled is True
    assert spec.timeout_s == 300.0
    assert spec.mem_limit == "512m"
    assert spec.env == {}


def test_spec_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError):
        SandboxSpec(image="img", command="pytest", repo_path=Path("."), timeout_s=0)


def test_spec_echoed_into_result(tmp_path: Path) -> None:
    backend = FakeBackend(ContainerRun(exit_code=0, stdout="", stderr="", timed_out=False))
    result = SandboxRunner(backend).run_tests(_spec(tmp_path, command="pytest -k smoke"))
    assert result.image == "python:3.12-slim"
    assert result.command == "pytest -k smoke"
    assert backend.last_spec is not None
