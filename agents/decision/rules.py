"""Decision rules: pure functions, no LangGraph needed (fast to test in CI).

Starts from the rules of api/pipeline.py `decide()` and makes every threshold
configurable in agents/decision/config.yaml. Every rule that fires adds a clear
sentence to Decision.reasons, so a claims handler can see why.
"""
import os
from functools import lru_cache
from pathlib import Path

import yaml

from claimspilot.schemas import (
    ClaimInput,
    Decision,
    NLPResult,
    PolicyResult,
    VisionResult,
)

CONFIG_PATH = Path(os.getenv("DECISION_CONFIG", "agents/decision/config.yaml"))


@lru_cache(maxsize=1)
def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _mean_confidence(vision: VisionResult) -> float | None:
    if not vision.damages:
        return None
    return sum(d.confidence for d in vision.damages) / len(vision.damages)


def summary(vision: VisionResult, nlp: NLPResult, policy: PolicyResult) -> list[str]:
    """Facts shown to the claims handler, whatever the decision."""
    damages = ", ".join(f"{d.part}/{d.damage_type} ({d.confidence:.2f})"
                        for d in vision.damages) or "none"
    return [
        f"vision: {len(vision.damages)} damage(s) [{damages}], severity {vision.severity}",
        (f"text vs photos: {nlp.consistency} (score {nlp.score:.2f}), "
         f"parts in text: {', '.join(nlp.described_parts) or 'none'}"),
        f"policy: covered={policy.covered} - {policy.answer}",
    ]


def decide(claim: ClaimInput, vision: VisionResult, nlp: NLPResult,
           policy: PolicyResult, cfg: dict | None = None) -> Decision:
    """Combine the three agent results into a Decision (reject > human_review > approve)."""
    cfg = cfg or load_config()
    rules, conf = cfg["rules"], cfg["confidence"]
    reasons = summary(vision, nlp, policy)

    if rules["reject_if_not_covered"] and policy.covered is False:
        reasons.append("REJECT: the damage is not covered by the policy")
        return Decision(claim_id=claim.claim_id, decision="reject",
                        confidence=conf["reject"], reasons=reasons)

    review = []
    if rules["review_if_coverage_unknown"] and policy.covered is None:
        review.append("the policy agent could not decide the coverage")
    if rules["review_if_inconsistent"] and nlp.consistency == "inconsistent":
        review.append("the text does not match the damage seen on the photos")
    if rules["review_if_uncertain"] and nlp.consistency == "uncertain":
        review.append("the text could not be compared with the photos")
    if nlp.score < rules["min_nlp_score"]:
        review.append(f"low text/photo consistency score ({nlp.score:.2f} "
                      f"< {rules['min_nlp_score']})")
    if vision.severity in rules["review_severities"]:
        review.append(f"{vision.severity} damage needs a human check")
    mean_conf = _mean_confidence(vision)
    if mean_conf is None:
        if rules["review_if_no_damage"]:
            review.append("no damage detected on the photos (the model can miss damage)")
    elif mean_conf < rules["min_vision_confidence"]:
        review.append(f"low vision confidence ({mean_conf:.2f} "
                      f"< {rules['min_vision_confidence']})")

    if review:
        reasons += [f"HUMAN REVIEW: {r}" for r in review]
        return Decision(claim_id=claim.claim_id, decision="human_review",
                        confidence=conf["human_review"], reasons=reasons)

    confidence = min(nlp.score, mean_conf if mean_conf is not None else 1.0,
                     conf["approve_max"])
    reasons.append("APPROVE: covered, consistent with the photos, no review rule triggered")
    return Decision(claim_id=claim.claim_id, decision="approve",
                    confidence=round(confidence, 4), reasons=reasons)