"""The Steward MCP server (product deliverable, CLAUDE.md §2/§14).

Exposes Steward's capabilities — issue context, duplicate detection, codebase
search, sandboxed test runs, patch proposal, and multi-agent patch review — as
MCP tools so other agents can drive Steward. Build a server with
:func:`build_server` (inject the tools)
or :func:`build_default_server`; run it with ``python -m steward.mcp``.
"""

from __future__ import annotations

from steward.mcp.server import build_default_server, build_server, main
from steward.mcp.service import CapabilityUnavailable, StewardTools

__all__ = [
    "CapabilityUnavailable",
    "StewardTools",
    "build_default_server",
    "build_server",
    "main",
]
