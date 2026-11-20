"""Claim pipeline: calls the agents and combines their results.

Each agent is called for real when it is available (code merged, libraries
installed, model files pulled with DVC). Otherwise the pipeline falls back to a
STUB returning a fixed example in the shared format, and says so in `agents`.

Decision (see make_decision):
1. safety: if any agent used a stub, the claim goes to human review (its data is
   invented), and Wiem's decision agent is not called;
2. otherwise Wiem's LangGraph decision agent (agents/decision/agent.py);
3. if LangGraph is not installed or the agent fails: Wiem's pure rules
   (agents/decision/rules.py), the same rules the graph applies;
4. if those rules fail too: human review (confidence 0.0), never an HTTP 500.
"""
import importlib.util
import logging

from pydantic import BaseModel

from agents.decision import agent as decision_agent
from agents.decision import rules as decision_rules
from api import tracing
from claimspilot.schemas import (
    ClaimInput,
    Damage,
    Decision,
    NLPResult,
    PolicyClause,
    PolicyResult,
    VisionResult,
)

logger = logging.getLogger(__name__)


def vision_stub(claim: ClaimInput) -> VisionResult:
    return VisionResult(
        claim_id=claim.claim_id,
        damages=[Damage(part="front_bumper", damage_type="dent",
                        bbox=[120, 340, 410, 520], confidence=0.82)],
        severity="moderate",
        model_version="stub",
    )


def nlp_stub(claim: ClaimInput, vision: VisionResult) -> NLPResult:
    return NLPResult(
        claim_id=claim.claim_id,
        described_parts=["front_bumper"],
        consistency="consistent",
        score=0.9,
        model_version="stub",
    )


def policy_stub(claim: ClaimInput, vision: VisionResult) -> PolicyResult:
    return PolicyResult(
        claim_id=claim.claim_id,
        covered=True,
        answer="Collision damage to the bumper is covered by article 4.",
        clauses=[PolicyClause(clause_id="art-4", text="Collision damage is covered.",
                              relevance=0.88)],
        model_version="stub",
    )


class ClaimAnalysis(BaseModel):
    """Everything the pipeline produced for one claim (used by the UI)."""

    vision: VisionResult
    nlp: NLPResult
    policy: PolicyResult
    decision: Decision
    # vision / nlp / policy -> "real" or "stub (reason)";
    # decision -> "langgraph", "rules (fallback: <error type>)", "safety: stub used"
    #             or "safety: decision failed (<agent error>, <rules error>)"
    agents: dict[str, str]


def _has_library(name: str) -> bool:
    """Is this Python package installed? (does not import it)"""
    return importlib.util.find_spec(name) is not None


def vision_real(claim: ClaimInput) -> VisionResult:
    """Wiem's agent. It skips a photo when detection fails, so a missing library
    would look like "no damage": check the library first. Missing weights are
    reported by the agent itself (FileNotFoundError)."""
    if not _has_library("ultralytics"):
        raise ImportError("ultralytics not installed (pip install -r requirements-vision.txt)")
    from agents.vision.agent import run

    return run(claim)


def nlp_real(claim: ClaimInput, vision: VisionResult) -> NLPResult:
    """Hend's agent."""
    from agents.nlp.agent import run

    return run(claim, vision)

def policy_real(claim: ClaimInput, vision: VisionResult) -> PolicyResult:
    """Mohamed's agent. With tracing on, its retrieval and LLM call are traced too."""
    from agents.policy.agent import run

    if tracing.client() is None:
        return run(claim, vision)
    return run(claim, vision, retriever=_traced_retriever, generator=_traced_generator)


def _traced_retriever(query: str, insurer: str, guarantees: list[str], k: int,
                      exclusions: bool) -> list[dict]:
    """The policy agent's retrieval, as a "policy retrieval" observation."""
    from agents.policy import agent as policy_agent

    with tracing.observe("policy retrieval", as_type="retriever",
                         input={"query": query, "insurer": insurer, "guarantees": guarantees,
                                "k": k, "exclusions": exclusions}) as step:
        found = policy_agent.retrieve(query, insurer, guarantees, k, exclusions)
        step.update(output=[{"clause_id": c["clause_id"], "relevance": c["relevance"]}
                            for c in found])
        return found


def _traced_generator(prompt: str) -> str:
    """The policy agent's LLM call, as a "policy LLM call" generation (model, prompt,
    answer, token usage; latency = start to end of the observation)."""
    from agents.policy import generation
    from agents.policy.settings import CONFIG

    llm = CONFIG["llm"]
    generate = generation.default_generator()
    unavailable = None
    with tracing.observe("policy LLM call", as_type="generation", model=llm["model"],
                         input=prompt, model_parameters={
                             "temperature": llm["temperature"],
                             "max_tokens": llm["max_tokens"]}) as step:
        try:
            if generate is generation.ollama_generate:
                answer = generation.ollama_call(prompt)
                step.update(output=answer.text, usage_details={
                    "input": answer.input_tokens or 0, "output": answer.output_tokens or 0})
                return answer.text
            text = generate(prompt)
            step.update(output=text)
            return text
        except generation.GeneratorUnavailable as error:
            # expected (no Ollama, timeout...): the agent uses its template answer,
            # so a WARNING, not an ERROR; re-raised once the observation is closed
            step.update(level="WARNING", status_message=f"template answer used: {error}"[:300])
            unavailable = error
    raise unavailable


def _call(name: str, real, stub, *args, status: dict):
    """Try the real agent; on any problem use the stub and record why."""
    try:
        result = real(*args)
        status[name] = "real"
        return result
    except Exception as error:  # noqa: BLE001 - missing library, weights, index...
        logger.warning("%s agent unavailable, using stub: %s", name, error)
        status[name] = f"stub ({type(error).__name__}: {error})"[:200]
        return stub(*args)


def make_decision(claim: ClaimInput, vision: VisionResult, nlp: NLPResult,
                  policy: PolicyResult, stubs: list[str]) -> tuple[Decision, str]:
    """Return the Decision and how it was made (the value of agents["decision"]).

    `stubs` = names of the agents that fell back to a stub for this claim. A stub
    returns invented data, so such a claim always goes to a human, whatever the
    other results say, and the decision agent is not called.
    """
    if stubs:
        reasons = ["stub result used for: " + ", ".join(stubs)
                   + " (agent unavailable, its result is not real)"]
        reasons += decision_rules.summary(vision, nlp, policy)
        decision = Decision(claim_id=claim.claim_id, decision="human_review",
                            confidence=0.0, reasons=reasons)
        return decision, "safety: stub used"
    try:
        return decision_agent.run(claim, vision, nlp, policy), "langgraph"
    except Exception as error:  # noqa: BLE001 - langgraph not installed, graph error...
        logger.warning("decision agent unavailable, using its rules: %s", error)
        agent_error = type(error).__name__
    try:
        decision = decision_rules.decide(claim, vision, nlp, policy)
        return decision, f"rules (fallback: {agent_error})"
    except Exception as error:  # noqa: BLE001 - config missing or invalid...
        # Never a 500 and never an automatic answer: a human decides.
        logger.error("decision rules failed too, sending to human review: %s", error)
        reason = (f"no automatic decision: the decision agent ({agent_error}) and its "
                  f"rules ({type(error).__name__}: {error}) both failed")[:300]
        decision = Decision(claim_id=claim.claim_id, decision="human_review",
                            confidence=0.0, reasons=[reason])
        return decision, f"safety: decision failed ({agent_error}, {type(error).__name__})"


def _traced_call(name: str, real, stub, *args, status: dict):
    """_call inside an observation named after the agent (output: its result and status)."""
    with tracing.observe(name) as step:
        result = _call(name, real, stub, *args, status=status)
        step.update(output=result.model_dump(), metadata={"status": status[name]})
        return result


def analyze_claim(claim: ClaimInput) -> ClaimAnalysis:
    """vision -> nlp -> policy -> decision; one Langfuse trace per claim when tracing is on."""
    status: dict[str, str] = {}
    with tracing.claim_trace(claim) as root:
        vision = _traced_call("vision", vision_real, vision_stub, claim, status=status)
        nlp = _traced_call("nlp", nlp_real, nlp_stub, claim, vision, status=status)
        policy = _traced_call("policy", policy_real, policy_stub, claim, vision, status=status)
        stubs = [name for name, state in status.items() if state != "real"]
        with tracing.observe("decision") as step, tracing.langchain_callbacks():
            decision, status["decision"] = make_decision(claim, vision, nlp, policy, stubs)
            step.update(output={**decision.model_dump(), "status": status["decision"]})
        if root.trace_id:
            decision = decision.model_copy(update={"trace_id": root.trace_id})
        root.update(output={"decision": decision.decision, "confidence": decision.confidence,
                            "status": status["decision"]})
    return ClaimAnalysis(vision=vision, nlp=nlp, policy=policy, decision=decision,
                         agents=status)


def process_claim(claim: ClaimInput) -> Decision:
    return analyze_claim(claim).decision