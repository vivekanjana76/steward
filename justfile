# Steward task runner (CLAUDE.md §17).
#
# `just` is optional. Every recipe lists its raw-command equivalent so users
# without `just` can run the same thing directly. On Windows, recipes run via
# PowerShell (see `set windows-shell` below).

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# List available recipes.
default:
    @just --list

# Bring a clean machine up to a running stack (db + api + dashboard).
# raw: docker compose up --build
up:
    docker compose up --build

# Lint + format check + type check.
# raw: uv run ruff check . ; uv run ruff format --check . ; uv run pyright
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright

# Run the test suite.
# raw: uv run pytest
test:
    uv run pytest

# Run the FastAPI service (audit log, approval queue, scorecard) for the dashboard.
# raw: uv run uvicorn steward.api.app:app --reload --port 8000
api:
    uv run uvicorn steward.api.app:app --reload --port 8000

# Run the eval suite, write evals/report.json, gate against evals/baseline.json.
# raw: uv run python -m steward.evals
eval:
    uv run python -m steward.evals

# Run the Steward MCP server locally (stdio transport).
# raw: uv run python -m steward.mcp
mcp:
    uv run python -m steward.mcp

# Point Steward at the controlled demo repo, one full cycle in dry-run.
# raw: uv run python -m steward.demo
demo:
    uv run python -m steward.demo
