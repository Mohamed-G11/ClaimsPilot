"""Decision agent: LangGraph orchestration vision -> nlp -> policy -> decide.

Contract (AGENTS.md section 4):
    run(claim: ClaimInput, vision: VisionResult, nlp: NLPResult, policy: PolicyResult)
        -> Decision

The graph shares one state between the nodes. Each agent node only calls its agent
when the state does not already hold its result, so the same graph serves both:
- run(): the API already has the three results -> only `decide` does work;
- process_claim(): full chain from a claim, with real agents or stubs.
LangGraph is imported lazily (requirements-decision.txt), so the rules in rules.py
stay testable without it.
"""
from collections.abc import Callable
from functools import lru_cache
from typing import TypedDict

from agents.decision import stubs
from agents.decision.rules import decide
from claimspilot.schemas import (
    ClaimInput,
    Decision,
    NLPResult,
    PolicyResult,
    VisionResult,
)

VisionFn = Callable[[ClaimInput], VisionResult]
NLPFn = Callable[[ClaimInput, VisionResult], NLPResult]
PolicyFn = Callable[[ClaimInput, VisionResult], PolicyResult]


class ClaimState(TypedDict, total=False):
    claim: ClaimInput
    vision: VisionResult
    nlp: NLPResult
    policy: PolicyResult
    decision: Decision


def build_graph(vision_fn: VisionFn = stubs.vision_stub, nlp_fn: NLPFn = stubs.nlp_stub,
                policy_fn: PolicyFn = stubs.policy_stub):
    """Compile the graph vision -> nlp -> policy -> decide with the given agents."""
    from langgraph.graph import END, START, StateGraph

    def vision_node(state: ClaimState) -> dict:
        return {} if state.get("vision") else {"vision": vision_fn(state["claim"])}

    def nlp_node(state: ClaimState) -> dict:
        if state.get("nlp"):
            return {}
        return {"nlp": nlp_fn(state["claim"], state["vision"])}

    def policy_node(state: ClaimState) -> dict:
        if state.get("policy"):
            return {}
        return {"policy": policy_fn(state["claim"], state["vision"])}

    def decide_node(state: ClaimState) -> dict:
        return {"decision": decide(state["claim"], state["vision"], state["nlp"],
                                   state["policy"])}

    graph = StateGraph(ClaimState)
    graph.add_node("vision", vision_node)
    graph.add_node("nlp", nlp_node)
    graph.add_node("policy", policy_node)
    graph.add_node("decide", decide_node)
    graph.add_edge(START, "vision")
    graph.add_edge("vision", "nlp")
    graph.add_edge("nlp", "policy")
    graph.add_edge("policy", "decide")
    graph.add_edge("decide", END)
    return graph.compile()


@lru_cache(maxsize=1)
def _default_graph():
    return build_graph()


def run(claim: ClaimInput, vision: VisionResult, nlp: NLPResult,
        policy: PolicyResult) -> Decision:
    state = _default_graph().invoke(
        {"claim": claim, "vision": vision, "nlp": nlp, "policy": policy})
    return state["decision"]


def process_claim(claim: ClaimInput, vision_fn: VisionFn = stubs.vision_stub,
                  nlp_fn: NLPFn = stubs.nlp_stub,
                  policy_fn: PolicyFn = stubs.policy_stub) -> Decision:
    """Full chain from a claim (the API can pass the real agents' run functions)."""
    return build_graph(vision_fn, nlp_fn, policy_fn).invoke({"claim": claim})["decision"]