"""Claim pipeline: calls the agents and combines their results.

Each agent is called for real when it is available (code merged, libraries
installed, model files pulled with DVC). Otherwise the pipeline falls back to a
STUB returning a fixed example in the shared format, and says so in `agents`.

Decision (see make_decision):
1. safety: if any agent used a stub, the claim goes to human review (its data is
   invented), and Wiem's decision agent is not called;
2. otherwise Wiem's LangGraph decision agent (agents/decision/agent.py);
3. if LangGraph is not installed or the agent fails: Wiem's pure rules
   (agents/decision/rules.py), the same rules the graph applies.
"""
import importlib.util
import logging

from pydantic import BaseModel

from agents.decision import agent as decision_agent
from agents.decision import rules as decision_rules
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
    # decision -> "langgraph", "rules (fallback)" or "safety: stub used"
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
    from agents.policy.agent import run

    return run(claim, vision)


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
        return decision_rules.decide(claim, vision, nlp, policy), "rules (fallback)"


def analyze_claim(claim: ClaimInput) -> ClaimAnalysis:
    status: dict[str, str] = {}
    vision = _call("vision", vision_real, vision_stub, claim, status=status)
    nlp = _call("nlp", nlp_real, nlp_stub, claim, vision, status=status)
    policy = _call("policy", policy_real, policy_stub, claim, vision, status=status)
    stubs = [name for name, state in status.items() if state != "real"]
    decision, status["decision"] = make_decision(claim, vision, nlp, policy, stubs)
    return ClaimAnalysis(vision=vision, nlp=nlp, policy=policy, decision=decision,
                         agents=status)


def process_claim(claim: ClaimInput) -> Decision:
    return analyze_claim(claim).decision