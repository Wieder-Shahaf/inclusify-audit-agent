"""LangGraph assembly. Wires perceive → route ⇄ act → reflect → stop."""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from . import nodes
from .state import AgentState


def build_graph(llm: Any, store: Any, embedder: Any):
    """Return a compiled LangGraph app.

    Routing: route node sets state['next_action']; conditional edge dispatches.
    Loop bound: route also checks step >= max_iters and forces 'stop'.
    """
    sg = StateGraph(AgentState)

    sg.add_node("perceive", nodes.perceive)
    sg.add_node("route", lambda s: nodes.route(s, llm=llm))
    sg.add_node("act", lambda s: nodes.act(s, llm=llm, store=store, embedder=embedder))
    sg.add_node("reflect", lambda s: nodes.reflect(s, llm=llm))
    sg.add_node("stop", nodes.stop)

    sg.set_entry_point("perceive")
    sg.add_edge("perceive", "route")

    # Route → act | reflect | stop based on state['next_action']
    def _from_route(state: AgentState) -> str:
        action = state.get("next_action", "stop")
        if action == "stop":
            return "stop"
        if action == "reflect":
            return "reflect"
        return "act"

    sg.add_conditional_edges("route", _from_route, {
        "act": "act",
        "reflect": "reflect",
        "stop": "stop",
    })
    sg.add_edge("act", "route")
    sg.add_edge("reflect", "stop")
    sg.add_edge("stop", END)

    return sg.compile()
