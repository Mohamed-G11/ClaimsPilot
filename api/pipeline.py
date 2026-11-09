"""Claim pipeline: calls the agents and combines their results.

The agent functions below are STUBS returning fixed example results in the
shared formats. Each stub will be replaced by the real agent's run().
"""
from claimspilot.schemas import (
    ClaimInput,
    Damage,
    Decision,
    NLPResult,
    PolicyClause,
    PolicyResult,
    VisionResult,
)


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
           policy: PolicyResult) -> Decision:
    """Simple rules until the decision agent exists (sprint 3)."""
    reasons = [f"severity: {vision.severity}", f"text vs photos: {nlp.consistency}",
               f"policy: {policy.answer}"]

    if policy.covered is False:
        decision, confidence = "reject", 0.8
    elif nlp.consistency == "inconsistent" or policy.covered is None:
        decision, confidence = "human_review", 0.5
    elif vision.severity == "severe":
        decision, confidence = "human_review", 0.6
    else:
        decision, confidence = "approve", min(nlp.score, 0.9)

    return Decision(claim_id=claim.claim_id, decision=decision,
                    confidence=confidence, reasons=reasons)


def process_claim(claim: ClaimInput) -> Decision:
    vision = vision_stub(claim)
    nlp = nlp_stub(claim, vision)
    policy = policy_stub(claim, vision)
    return decide(claim, vision, nlp, policy)