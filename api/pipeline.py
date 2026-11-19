"""Claim pipeline: calls the agents and combines their results.

Each agent is called for real when it is available (code merged, libraries
installed, model files pulled with DVC). Otherwise the pipeline falls back to a
STUB returning a fixed example in the shared format, and says so in `agents`.
"""
import importlib.util
import logging

from pydantic import BaseModel

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


def decide(claim: ClaimInput, vision: VisionResult, nlp: NLPResult,
           policy: PolicyResult, stubs: list[str] | None = None) -> Decision:
    """Simple rules until the decision agent exists (sprint 3).

    `stubs` = names of the agents that fell back to a stub for this claim. A stub
    returns invented data, so such a claim always goes to a human, whatever the
    other results say. A claim is approved only when every agent was real, the
    policy says covered, the text matches the photos and the damage is not severe.
    """
    stubs = stubs or []
    reasons = [f"severity: {vision.severity}", f"text vs photos: {nlp.consistency}",
               f"policy: {policy.answer}"]

    if stubs:
        decision, confidence = "human_review", 0.0
        reasons.insert(0, "stub result used for: " + ", ".join(stubs)
                       + " (agent unavailable, its result is not real)")
    elif policy.covered is False:
        decision, confidence = "reject", 0.8
    elif policy.covered is None:
        decision, confidence = "human_review", 0.5
        reasons.insert(0, "coverage could not be decided automatically")
    elif nlp.consistency == "inconsistent":
        decision, confidence = "human_review", 0.5
        reasons.insert(0, "the text does not match the photos")
    elif nlp.consistency == "uncertain":
        decision, confidence = "human_review", 0.5
        reasons.insert(0, "text and photos could not be compared (uncertain)")
    elif vision.severity == "severe":
        decision, confidence = "human_review", 0.6
        reasons.insert(0, "severe damage is always checked by a claims handler")
    else:
        decision, confidence = "approve", min(nlp.score, 0.9)

    return Decision(claim_id=claim.claim_id, decision=decision,
                    confidence=confidence, reasons=reasons)


class ClaimAnalysis(BaseModel):
    """Everything the pipeline produced for one claim (used by the UI)."""

    vision: VisionResult
    nlp: NLPResult
    policy: PolicyResult
    decision: Decision
    agents: dict[str, str]  # agent -> "real" or "stub (reason)"


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


def analyze_claim(claim: ClaimInput) -> ClaimAnalysis:
    status: dict[str, str] = {}
    vision = _call("vision", vision_real, vision_stub, claim, status=status)
    nlp = _call("nlp", nlp_real, nlp_stub, claim, vision, status=status)
    policy = _call("policy", policy_real, policy_stub, claim, vision, status=status)
    stubs = [name for name, state in status.items() if state != "real"]
    decision = decide(claim, vision, nlp, policy, stubs=stubs)
    status["decision"] = "rules (api/pipeline.py)"
    return ClaimAnalysis(vision=vision, nlp=nlp, policy=policy, decision=decision,
                         agents=status)


def process_claim(claim: ClaimInput) -> Decision:
    return analyze_claim(claim).decision