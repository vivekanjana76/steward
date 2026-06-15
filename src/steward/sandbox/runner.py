"""Sandboxed test runner: repo tests run in disposable containers, never on host.

Reproduction and fix-verification both hinge on running a repository's test
command and trusting the result. That only works if the run is **isolated**
(CLAUDE.md §4/§12): a disposable container, the repo mounted **read-only**, no
network by default, bounded memory and time. This module owns that contract.

The orchestration is split from the container mechanics so it is fully testable
without Docker:

* :class:`SandboxRunner` validates the request, times it, wraps it in a trace
  span, and maps the raw container outcome onto a typed :class:`SandboxResult`.
* :class:`ContainerBackend` is the seam — a protocol with one method. The real
  Docker implementation lives in :mod:`steward.sandbox.docker_backend`; unit
  tests inject a fake, so the runner's logic is exercised deterministically and
  offline.

Running tests is a **whitelist** action
(:attr:`~steward.policy.engine.ActionKind.RUN_SANDBOXED_TESTS`): it is allowed
without approval precisely *because* it is sandboxed and side-effect-free on the
outside world.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from steward.observability import Tracer, get_tracer, new_trace_id

# Conservative defaults: a short timeout and a modest memory cap so a runaway or
# resource-hungry test run can never wedge the host.
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_MEM_LIMIT = "512m"


class SandboxSpec(BaseModel):
    """One sandboxed test run request.

    ``repo_path`` is mounted **read-only** inside the container and copied to a
    writable working directory there, so the test command can write freely while
    the host checkout is never mutated. ``network_disabled`` defaults to
    ``True`` — a test run gets no outbound network unless a caller explicitly
    opts in (CLAUDE.md §12).
    """

    model_config = ConfigDict(frozen=True)

    image: str = Field(min_length=1, description="Container image, e.g. 'python:3.12-slim'")
    command: str = Field(min_length=1, description="Test command, e.g. 'pytest -q'")
    repo_path: Path = Field(description="Host path to the repo checkout to test")
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0, le=3600)
    mem_limit: str = Field(default=DEFAULT_MEM_LIMIT, min_length=1)
    env: dict[str, str] = Field(default_factory=dict)
    network_disabled: bool = True


@dataclass(slots=True)
class ContainerRun:
    """The raw outcome a :class:`ContainerBackend` reports for one run.

    ``exit_code`` is ``None`` when the container was killed before it could
    report one (e.g. on timeout).
    """

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class SandboxResult(BaseModel):
    """The typed verdict of a sandboxed test run.

    ``passed`` is the single source of truth callers should branch on: it is
    ``True`` only when the run finished within its timeout and the test command
    exited ``0``. Logs are captured either way so a failure (or timeout) carries
    its own evidence (CLAUDE.md §1).
    """

    model_config = ConfigDict(frozen=True)

    passed: bool
    exit_code: int | None
    timed_out: bool
    duration_s: float
    stdout: str
    stderr: str
    image: str
    command: str


class SandboxError(RuntimeError):
    """Raised when a run cannot even be attempted (bad request or backend fault)."""


class ContainerBackend(Protocol):
    """The one operation the runner needs from a container engine.

    Implementations must honour the spec's isolation guarantees: a disposable
    container, the repo mounted read-only, network disabled unless opted in,
    memory and time bounded. They return a :class:`ContainerRun`; raising is
    reserved for faults that prevented the run from starting.
    """

    def run(self, spec: SandboxSpec) -> ContainerRun:
        """Run ``spec`` to completion (or timeout) and report the raw outcome."""
        ...


class SandboxRunner:
    """Runs repo tests through a :class:`ContainerBackend`, producing a verdict.

    ``clock`` (monotonic by default) is injectable for deterministic duration
    assertions in tests; ``tracer`` defaults to the process tracer, which is a
    no-op unless Langfuse is configured.
    """

    def __init__(
        self,
        backend: ContainerBackend,
        *,
        clock: Callable[[], float] = time.monotonic,
        tracer: Tracer | None = None,
    ) -> None:
        self._backend = backend
        self._clock = clock
        self._tracer = tracer or get_tracer()

    def run_tests(self, spec: SandboxSpec, *, trace_id: str | None = None) -> SandboxResult:
        """Execute ``spec`` in a sandbox and return a typed :class:`SandboxResult`.

        Raises :class:`SandboxError` if the request is invalid (e.g. the repo
        path does not exist) or the backend faults before producing an outcome.
        """
        if not spec.repo_path.is_dir():
            raise SandboxError(f"repo_path is not a directory: {spec.repo_path}")

        trace_id = trace_id or new_trace_id()
        start = self._clock()
        with self._tracer.span("sandbox.run_tests", trace_id=trace_id) as span:
            try:
                outcome = self._backend.run(spec)
            except SandboxError:
                raise
            except Exception as exc:
                raise SandboxError(f"sandbox backend failed: {exc}") from exc
            duration_s = self._clock() - start
            passed = outcome.exit_code == 0 and not outcome.timed_out
            span.set_metadata(
                passed=passed,
                exit_code=outcome.exit_code,
                timed_out=outcome.timed_out,
            )

        return SandboxResult(
            passed=passed,
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
            duration_s=duration_s,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            image=spec.image,
            command=spec.command,
        )
