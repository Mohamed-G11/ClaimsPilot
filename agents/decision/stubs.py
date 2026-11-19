"""Stub agents with the real signatures, so the decision graph runs before the real
NLP / policy agents are merged. The vision stub replays a real VisionResult from
agents/vision/examples/ (AGENTS.md section 4)."""
from pathlib import Path

from claimspilot.schemas import (
    ClaimInput,
    NLPResult,
    PolicyClause,
    PolicyResult,
    VisionResult,
)

EXAMPLES = Path("agents/vision/examples")


def vision_stub(claim: ClaimInput, example: str = "vision_result_003.json") -> VisionResult:
    result = VisionResult.model_validate_json((EXAMPLES / example).read_text(encoding="utf-8"))
    return result.model_copy(update={"claim_id": claim.claim_id})


def nlp_stub(claim: ClaimInput, vision: VisionResult) -> NLPResult:
    parts = sorted({d.part for d in vision.damages if d.part != "other"})
    return NLPResult(claim_id=claim.claim_id, described_parts=parts,
                     consistency="consistent" if parts else "uncertain",
                     score=0.9 if parts else 0.5, model_version="stub")


def policy_stub(claim: ClaimInput, vision: VisionResult) -> PolicyResult:
    return PolicyResult(
        claim_id=claim.claim_id, covered=True,
        answer="Collision damage is covered by article 4.",
        clauses=[PolicyClause(clause_id="art-4", text="Collision damage is covered.",
                              relevance=0.88)],
        model_version="stub",
    )