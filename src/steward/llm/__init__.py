"""Model access layer.

All Anthropic model calls go through :mod:`steward.llm.client` so that the
model used for each role can be swapped in exactly one place (CLAUDE.md §4).
"""
