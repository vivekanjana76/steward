"""Integrations with external systems Steward *consumes* (issue #57).

Currently: consuming external **MCP servers** as read-only, untrusted context
sources via :class:`~steward.integrations.external_mcp.ExternalToolHub` — the
counterpart to ``steward.mcp``, which *authors* Steward's own MCP server.
"""

from __future__ import annotations

from steward.integrations.external_mcp import (
    ExternalContext,
    ExternalMCPServer,
    ExternalTool,
    ExternalToolHub,
    load_mcp_config,
)

__all__ = [
    "ExternalContext",
    "ExternalMCPServer",
    "ExternalTool",
    "ExternalToolHub",
    "load_mcp_config",
]
