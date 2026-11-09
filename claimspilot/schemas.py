"""Shared data contracts between ClaimsPilot agents (AGENTS.md section 4).

Never change a class without a PR approved by all three members.
"""
from typing import Literal

from pydantic import BaseModel, Field

PARTS = [
    "front_bumper", "rear_bumper", "door", "hood", "trunk", "fender",
    "headlight", "taillight", "windshield", "side_mirror", "wheel", "other",
]


class ClaimInput(BaseModel):
    claim_id: str
    photo_paths: list[str]
    text: str
    policy_id: str
    language: Literal["fr", "en", "ar"] = "fr"


class Damage(BaseModel):
    part: str
    damage_type: str
    bbox: list[float]
    confidence: float = Field(ge=0, le=1)


class VisionResult(BaseModel):
    claim_id: str
    damages: list[Damage]
    severity: Literal["minor", "moderate", "severe"]
    model_version: str


class NLPResult(BaseModel):
    claim_id: str
    described_parts: list[str]
    consistency: Literal["consistent", "inconsistent", "uncertain"]
    score: float = Field(ge=0, le=1)
    model_version: str


class PolicyClause(BaseModel):
    clause_id: str
    text: str
    relevance: float


class PolicyResult(BaseModel):
    claim_id: str
    covered: bool | None
    answer: str
    clauses: list[PolicyClause]
    model_version: str


class Decision(BaseModel):
    claim_id: str
    decision: Literal["approve", "reject", "human_review"]
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    trace_id: str | None = None