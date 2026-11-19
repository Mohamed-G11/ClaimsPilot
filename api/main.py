import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import warmup
from api.pipeline import ClaimAnalysis, analyze_claim, process_claim
from claimspilot.schemas import ClaimInput, Decision

API_VERSION = os.getenv("CLAIMSPILOT_VERSION", "0.3.0")   # set by Docker / CI at release time


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warmup.start_warmup()          # background thread: the API does not wait for it
    yield


app = FastAPI(title="ClaimsPilot API", version=API_VERSION, lifespan=lifespan)


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
