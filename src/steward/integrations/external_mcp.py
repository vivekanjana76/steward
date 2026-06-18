"""Consume **external** MCP servers as read-only, untrusted context (issue #57).

Steward authors its own MCP server (``steward.mcp``); this module is the other
direction — letting the Steward agent *consume* popular external MCP servers
(e.g. Context7 for live docs, sequential-thinking) to gather context while it
reasons about a fix.

Two rules are structural here, not optional:

* **Untrusted by construction.** Every result from an external tool is run
  through :func:`~steward.triage.sanitize.sanitize_text` and
  :func:`~steward.triage.sanitize.detect_injection` before Steward sees it, and
  returned as :class:`ExternalContext` carrying any ``injection_signals`` — it is
  *data to reason over*, never instructions to follow (CLAUDE.md §5).
* **Read-only / advisory.** This hub offers listing and calling tools for
  context only; it exposes no path that mutates Steward's repo. World-mutating
  actions stay behind the policy engine and human approval (CLAUDE.md §1/§5), so
  only read-only external servers should be configured.

The hub wraps a :class:`fastmcp.Client`, so it accepts anything that client does:
an in-memory FastMCP server (used by the tests, fully offline), a single server
spec, or a ``{"mcpServers": {...}}`` config — the standard ``.mcp.json`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import Client
from pydantic import BaseModel, ConfigDict, Field

from steward.triage.sanitize import detect_injection, sanitize_text


class ExternalMCPServer(BaseModel):
    """One external MCP server declaration (a ``.mcp.json`` entry).

    Either a ``command`` (stdio transport — ``command`` + ``args`` + ``env``) or
    a ``url`` (HTTP transport) identifies the server; the FastMCP client infers
    the transport. Secrets belong in ``env`` via ``${VAR}`` expansion, never
    inline (CLAUDE.md §12).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None


class ExternalTool(BaseModel):
    """A tool offered by an external server, as Steward sees it."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""


class ExternalContext(BaseModel):
    """The sanitized result of calling an external tool — untrusted *data*.

    ``text`` is the sanitized, visible text the tool returned; ``structured`` is
    its structured payload if any. ``injection_signals`` flags text that looks
    like it is trying to subvert Steward's instructions — evidence to stay
    cautious, never proof. A caller MUST treat this as content, not commands.
    """

    model_config = ConfigDict(frozen=True)

    server: str
    tool: str
    text: str
    structured: dict[str, Any] | None = None
    injection_signals: tuple[str, ...] = ()

    @property
    def is_suspicious(self) -> bool:
        """True when the returned text tripped any prompt-injection heuristic."""
        return bool(self.injection_signals)


def load_mcp_config(path: str | Path) -> dict[str, ExternalMCPServer]:
    """Load and validate a ``.mcp.json``-shaped file into typed server specs.

    Expects ``{"mcpServers": {name: {...}}}`` (extra top-level keys such as
    ``$comment`` are ignored). Each entry is validated into
    :class:`ExternalMCPServer`, so a malformed config fails loudly here rather
    than deep inside a transport at first use.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = raw.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("config must contain an object 'mcpServers'")
    return {name: ExternalMCPServer.model_validate(spec) for name, spec in servers.items()}


def _client_config(servers: dict[str, ExternalMCPServer]) -> dict[str, Any]:
    """Render typed specs back into the ``mcpServers`` dict the client consumes."""
    out: dict[str, Any] = {}
    for name, server in servers.items():
        entry: dict[str, Any] = {}
        if server.command is not None:
            entry["command"] = server.command
            entry["args"] = list(server.args)
            if server.env:
                entry["env"] = dict(server.env)
        if server.url is not None:
            entry["url"] = server.url
        out[name] = entry
    return {"mcpServers": out}


def _extract_text(result: Any) -> str:
    """Join the text blocks of a FastMCP call result into one string."""
    blocks = getattr(result, "content", None) or []
    parts = [getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p)


class ExternalToolHub:
    """An async context manager over a :class:`fastmcp.Client` to external servers.

    ``source`` is anything the FastMCP client accepts: an in-memory FastMCP
    server (tests), a single server spec, or a ``{"mcpServers": {...}}`` config.
    Use :meth:`from_config` / :meth:`from_config_file` to build one from typed
    specs. Open it with ``async with`` before listing or calling tools.
    """

    def __init__(self, source: Any) -> None:
        self._client = Client(source)

    @classmethod
    def from_config(cls, servers: dict[str, ExternalMCPServer]) -> ExternalToolHub:
        """Build a hub from validated server specs."""
        return cls(_client_config(servers))

    @classmethod
    def from_config_file(cls, path: str | Path) -> ExternalToolHub:
        """Build a hub from a ``.mcp.json``-shaped config file."""
        return cls.from_config(load_mcp_config(path))

    async def __aenter__(self) -> ExternalToolHub:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(*exc)

    async def list_tools(self) -> list[ExternalTool]:
        """List every tool the connected external server(s) offer."""
        tools = await self._client.list_tools()
        return [ExternalTool(name=t.name, description=t.description or "") for t in tools]

    async def fetch_context(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        server: str = "external",
    ) -> ExternalContext:
        """Call ``tool`` and return its result as sanitized, untrusted context.

        The raw text is normalized and stripped of invisible/control characters,
        and scanned for prompt-injection signals — so what Steward reasons over is
        always plain data with its risk flagged (CLAUDE.md §5).
        """
        result = await self._client.call_tool(tool, arguments or {})
        text = sanitize_text(_extract_text(result))
        return ExternalContext(
            server=server,
            tool=tool,
            text=text,
            structured=getattr(result, "structured_content", None),
            injection_signals=detect_injection(text),
        )
