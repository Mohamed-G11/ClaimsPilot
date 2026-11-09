from fastapi import FastAPI

from api.pipeline import process_claim
from claimspilot.schemas import ClaimInput, Decision

app = FastAPI(title="ClaimsPilot API", version="0.2.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/claims", response_model=Decision)
def create_claim(claim: ClaimInput) -> Decision:
    return process_claim(claim)