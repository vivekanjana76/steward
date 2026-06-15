"""The real container backend: Docker, with isolation enforced (CLAUDE.md §12).

This is the production :class:`~steward.sandbox.runner.ContainerBackend`. It is
kept apart from the runner so the runner stays unit-testable without Docker, and
the ``docker`` SDK is imported **lazily** — installing it is only required to
actually run a sandbox (``uv sync --extra sandbox``), not to import the package
or run the unit suite.

Isolation contract enforced here:

* **Repo never mutated on host.** The checkout is bind-mounted **read-only** at
  ``/repo`` and copied to a writable ``/workspace`` *inside* the disposable
  container, where the test command runs. The host files cannot be written.
* **No network by default** (``network_disabled``).
* **Bounded memory** (``mem_limit``) and **bounded time** — the container is
  waited on with the spec timeout and force-killed if it overruns.
* **Disposable** — the container is always removed, success or failure.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from steward.sandbox.runner import ContainerRun, SandboxError, SandboxSpec

if TYPE_CHECKING:
    from collections.abc import Callable


def _load_docker() -> Any:
    """Import the docker SDK lazily, with an actionable error if it is missing."""
    try:
        import docker  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SandboxError(
            "the 'docker' SDK is not installed; run `uv sync --extra sandbox` to "
            "enable live sandboxed test runs"
        ) from exc
    return docker


# Wrap the test command so it runs against a writable copy, never the read-only
# mount. Quoting is unnecessary: /repo and /workspace are fixed, internal paths.
_WRAPPER = "cp -a /repo /workspace && cd /workspace && {command}"


class DockerBackend:
    """A :class:`ContainerBackend` backed by a local Docker daemon.

    ``client_factory`` defaults to ``docker.from_env``; inject one in tests to
    drive a fake daemon without a real Docker install.
    """

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None

    def _client_or_connect(self) -> Any:
        if self._client is None:
            factory = self._client_factory or _load_docker().from_env
            self._client = factory()
        return self._client

    def run(self, spec: SandboxSpec) -> ContainerRun:
        """Run ``spec`` in a disposable, isolated container; report the outcome."""
        client = self._client_or_connect()
        container = None
        try:
            container = client.containers.run(
                image=spec.image,
                command=["sh", "-lc", _WRAPPER.format(command=spec.command)],
                volumes={str(spec.repo_path.resolve()): {"bind": "/repo", "mode": "ro"}},
                network_disabled=spec.network_disabled,
                mem_limit=spec.mem_limit,
                environment=dict(spec.env),
                detach=True,
            )
            timed_out = False
            exit_code: int | None
            try:
                result = container.wait(timeout=spec.timeout_s)
                exit_code = int(result.get("StatusCode", 1))
            except Exception:
                timed_out = True
                exit_code = None
                _safe_kill(container)

            stdout = _decode(container.logs(stdout=True, stderr=False))
            stderr = _decode(container.logs(stdout=False, stderr=True))
            return ContainerRun(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )
        finally:
            if container is not None:
                _safe_remove(container)


def _decode(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw) if raw is not None else ""


def _safe_kill(container: Any) -> None:
    # Best-effort; removal still runs in the caller's finally.
    with contextlib.suppress(Exception):
        container.kill()


def _safe_remove(container: Any) -> None:
    # Disposable container; if removal fails there is nothing else to do.
    with contextlib.suppress(Exception):
        container.remove(force=True)
