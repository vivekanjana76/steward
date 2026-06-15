"""Assemble and run the Steward agent graph.

Wires the nodes into the cycle from CLAUDE.md §3 with **real backtracking**: a
failed reproduction or a failing proof test routes *back* (to end or to
re-hypothesize), never forward, and the VERIFY gate stands between any "fixed"
claim and the draft PR. Checkpointing is enabled (an in-memory saver by
default) so a run is resumable and every step is inspectable.
"""

from __future__ import annotations

from functools import partial

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from steward.graph import nodes
from steward.graph.capabilities import StewardDeps
from steward.graph.state import GraphState
from steward.triage.models import NormalizedIssue


def build_graph(
    deps: StewardDeps,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build and compile the agent graph with ``deps`` bound into every node."""
    graph: StateGraph = StateGraph(GraphState)

    # Bind deps into each node so the compiled graph's nodes take only state.
    graph.add_node(nodes.TRIAGE, partial(nodes.triage_node, deps=deps))
    graph.add_node(nodes.ROUTE, partial(nodes.route_node, deps=deps))
    graph.add_node(nodes.REPRODUCE, partial(nodes.reproduce_node, deps=deps))
    graph.add_node(nodes.HYPOTHESIZE, partial(nodes.hypothesize_node, deps=deps))
    graph.add_node(nodes.PATCH, partial(nodes.patch_node, deps=deps))
    graph.add_node(nodes.TEST, partial(nodes.test_node, deps=deps))
    graph.add_node(nodes.VERIFY, partial(nodes.verify_node, deps=deps))
    graph.add_node(nodes.OPEN_PR, partial(nodes.open_pr_node, deps=deps))
    graph.add_node(nodes.GIVE_UP, partial(nodes.give_up_node, deps=deps))

    graph.add_edge(START, nodes.TRIAGE)
    graph.add_edge(nodes.TRIAGE, nodes.ROUTE)
    graph.add_conditional_edges(
        nodes.ROUTE,
        nodes.route_after_triage,
        {nodes.REPRODUCE: nodes.REPRODUCE, nodes.GIVE_UP_OR_END: END},
    )
    graph.add_conditional_edges(
        nodes.REPRODUCE,
        nodes.route_after_reproduce,
        {nodes.HYPOTHESIZE: nodes.HYPOTHESIZE, nodes.GIVE_UP_OR_END: END},
    )
    graph.add_edge(nodes.HYPOTHESIZE, nodes.PATCH)
    graph.add_edge(nodes.PATCH, nodes.TEST)
    # Backtracking lives here: still-failing proof test → re-hypothesize.
    graph.add_conditional_edges(
        nodes.TEST,
        nodes.route_after_test,
        {
            nodes.VERIFY: nodes.VERIFY,
            nodes.HYPOTHESIZE: nodes.HYPOTHESIZE,
            nodes.GIVE_UP: nodes.GIVE_UP,
        },
    )
    graph.add_conditional_edges(
        nodes.VERIFY,
        nodes.route_after_verify,
        {nodes.OPEN_PR: nodes.OPEN_PR, nodes.GIVE_UP: nodes.GIVE_UP},
    )
    graph.add_edge(nodes.OPEN_PR, END)
    graph.add_edge(nodes.GIVE_UP, END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_issue(
    graph: CompiledStateGraph,
    issue: NormalizedIssue,
    *,
    trace_id: str,
    thread_id: str,
    max_attempts: int = 2,
) -> GraphState:
    """Run ``issue`` through ``graph`` and return the final typed state.

    ``thread_id`` keys the checkpointer, so a run is resumable and auditable.
    """
    result = graph.invoke(
        {"issue": issue, "trace_id": trace_id, "max_attempts": max_attempts},
        config={"configurable": {"thread_id": thread_id}},
    )
    return GraphState.model_validate(result)
