"""Sandboxed execution: repo tests run in disposable containers, never on host.

The public surface is the runner and its typed contracts; the Docker backend is
imported on demand by callers that run live (it lazily needs the ``docker`` SDK).
"""

from __future__ import annotations

from steward.sandbox.runner import (
    DEFAULT_MEM_LIMIT,
    DEFAULT_TIMEOUT_S,
    ContainerBackend,
    ContainerRun,
    SandboxError,
    SandboxResult,
    SandboxRunner,
    SandboxSpec,
)

__all__ = [
    "DEFAULT_MEM_LIMIT",
    "DEFAULT_TIMEOUT_S",
    "ContainerBackend",
    "ContainerRun",
    "SandboxError",
    "SandboxResult",
    "SandboxRunner",
    "SandboxSpec",
]
