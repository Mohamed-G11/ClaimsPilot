from fastapi import FastAPI

from api.pipeline import ClaimAnalysis, analyze_claim, process_claim
from claimspilot.schemas import ClaimInput, Decision

app = FastAPI(title="ClaimsPilot API", version="0.3.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/claims", response_model=Decision)
def create_claim(claim: ClaimInput) -> Decision:
    return process_claim(claim)


@app.post("/claims/analyze", response_model=ClaimAnalysis)
def analyze(claim: ClaimInput) -> ClaimAnalysis:
    """Same pipeline as /claims, but returns every agent's result (for the UI)."""
    return analyze_claim(claim)
