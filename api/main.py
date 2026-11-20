import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from api import warmup
from api.pipeline import ClaimAnalysis, analyze_claim, process_claim
from claimspilot.schemas import ClaimInput, Decision

API_VERSION = os.getenv("CLAIMSPILOT_VERSION", "0.3.0")   # set by Docker / CI at release time


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warmup.start_warmup()          # background threads: the API does not wait for them
    yield


app = FastAPI(title="ClaimsPilot API", version=API_VERSION, lifespan=lifespan)


@app.get("/health")
def health():
    """Always 200 while the process runs (Docker healthcheck); shows the warm-up state."""
    return {"status": "ok", "warmup": warmup.status()}


@app.get("/ready")
def ready(response: Response):
    """200 when every warm-up has finished (done, failed or off), 503 before.

    Clients (the e2e script, a UI) wait on it so the first claim does not queue
    behind the model loading. `failed` lists the steps that did not warm up.
    """
    steps = warmup.status()
    is_ready = warmup.is_ready()
    if not is_ready:
        response.status_code = 503
    return {"ready": is_ready, "warmup": steps,
            "failed": [step for step, state in steps.items() if state == "failed"]}


@app.post("/claims", response_model=Decision)
def create_claim(claim: ClaimInput) -> Decision:
    return process_claim(claim)


@app.post("/claims/analyze", response_model=ClaimAnalysis)
def analyze(claim: ClaimInput) -> ClaimAnalysis:
    """Same pipeline as /claims, but returns every agent's result (for the UI)."""
    return analyze_claim(claim)
