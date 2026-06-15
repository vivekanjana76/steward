"""Tests for the Docker backend (issue #13).

Two layers:

* **Unit** — a fake docker client asserts the backend enforces the isolation
  contract (read-only repo mount, network disabled, memory cap, disposable
  container, wrapped command, timeout handling). No real Docker.
* **Integration** — one real run on a tiny project, gated behind the
  ``STEWARD_SANDBOX_IT`` env var *and* a reachable daemon, so CI and offline dev
  stay green. Run it with ``STEWARD_SANDBOX_IT=1 uv run pytest -k integration``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from steward.sandbox.docker_backend import DockerBackend
from steward.sandbox.runner import SandboxRunner, SandboxSpec


class FakeContainer:
    def __init__(
        self, *, status_code: int = 0, stdout: bytes = b"", stderr: bytes = b"", wait_raises=False
    ):
        self._status = status_code
        self._stdout = stdout
        self._stderr = stderr
        self._wait_raises = wait_raises
        self.killed = False
        self.removed = False

    def wait(self, timeout: float | None = None) -> dict[str, int]:
        if self._wait_raises:
            raise TimeoutError("read timed out")
        return {"StatusCode": self._status}

    def logs(self, *, stdout: bool = False, stderr: bool = False) -> bytes:
        return self._stdout if stdout else self._stderr

    def kill(self) -> None:
        self.killed = True

    def remove(self, *, force: bool = False) -> None:
        self.removed = True


class FakeContainers:
    def __init__(self, container: FakeContainer) -> None:
        self._container = container
        self.run_kwargs: dict[str, Any] | None = None

    def run(self, **kwargs: Any) -> FakeContainer:
        self.run_kwargs = kwargs
        return self._container


class FakeClient:
    def __init__(self, container: FakeContainer) -> None:
        self.containers = FakeContainers(container)


def _spec(repo: Path, **over: Any) -> SandboxSpec:
    base: dict[str, Any] = {"image": "python:3.12-slim", "command": "pytest -q", "repo_path": repo}
    base.update(over)
    return SandboxSpec(**base)


def test_backend_enforces_isolation(tmp_path: Path) -> None:
    container = FakeContainer(status_code=0, stdout=b"2 passed", stderr=b"")
    client = FakeClient(container)
    backend = DockerBackend(client_factory=lambda: client)

    outcome = backend.run(_spec(tmp_path))

    kwargs = client.containers.run_kwargs
    assert kwargs is not None
    # Repo mounted READ-ONLY; network disabled; memory bounded; disposable.
    mount = kwargs["volumes"][str(tmp_path.resolve())]
    assert mount == {"bind": "/repo", "mode": "ro"}
    assert kwargs["network_disabled"] is True
    assert kwargs["mem_limit"] == "512m"
    # Command runs against a writable copy, never the read-only mount.
    assert kwargs["command"] == [
        "sh",
        "-lc",
        "cp -a /repo /workspace && cd /workspace && pytest -q",
    ]
    assert container.removed is True
    assert outcome.exit_code == 0
    assert outcome.stdout == "2 passed"


def test_backend_reports_failure(tmp_path: Path) -> None:
    container = FakeContainer(status_code=1, stdout=b"1 failed", stderr=b"boom")
    backend = DockerBackend(client_factory=lambda: FakeClient(container))
    outcome = backend.run(_spec(tmp_path))
    assert outcome.exit_code == 1
    assert outcome.timed_out is False
    assert outcome.stderr == "boom"


def test_backend_handles_timeout(tmp_path: Path) -> None:
    container = FakeContainer(wait_raises=True)
    backend = DockerBackend(client_factory=lambda: FakeClient(container))
    outcome = backend.run(_spec(tmp_path, timeout_s=1))
    assert outcome.timed_out is True
    assert outcome.exit_code is None
    assert container.killed is True
    assert container.removed is True  # still disposed of


def test_network_opt_in_is_passed_through(tmp_path: Path) -> None:
    container = FakeContainer()
    client = FakeClient(container)
    backend = DockerBackend(client_factory=lambda: client)
    backend.run(_spec(tmp_path, network_disabled=False))
    assert client.containers.run_kwargs is not None
    assert client.containers.run_kwargs["network_disabled"] is False


def _docker_available() -> bool:
    try:
        import docker  # type: ignore[import-untyped]

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    os.environ.get("STEWARD_SANDBOX_IT") != "1" or not _docker_available(),
    reason="integration test: set STEWARD_SANDBOX_IT=1 and run a reachable Docker daemon",
)
def test_integration_runs_real_tests(tmp_path: Path) -> None:
    # A tiny project with one passing test, run for real in a disposable
    # container. Uses stdlib unittest so it needs no network — the sandbox
    # disables networking by default (a `pip install` here would correctly fail).
    (tmp_path / "test_sample.py").write_text(
        "import unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertEqual(1 + 1, 2)\n"
    )
    runner = SandboxRunner(DockerBackend())
    result = runner.run_tests(
        SandboxSpec(
            image="python:3.12-slim",
            command="python -m unittest discover -p 'test_*.py'",
            repo_path=tmp_path,
            timeout_s=600,
        )
    )
    assert result.passed is True, result.stdout + result.stderr
    assert result.exit_code == 0


@pytest.mark.skipif(
    os.environ.get("STEWARD_SANDBOX_IT") != "1" or not _docker_available(),
    reason="integration test: set STEWARD_SANDBOX_IT=1 and run a reachable Docker daemon",
)
def test_integration_network_is_disabled(tmp_path: Path) -> None:
    # Proof of isolation: with networking off, a command that needs the network
    # fails inside the sandbox rather than reaching out from the host.
    reach_out = (
        "python -c \"import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)\""
    )
    runner = SandboxRunner(DockerBackend())
    result = runner.run_tests(
        SandboxSpec(
            image="python:3.12-slim",
            command=reach_out,
            repo_path=tmp_path,
            timeout_s=120,
        )
    )
    assert result.passed is False
    assert result.exit_code != 0
