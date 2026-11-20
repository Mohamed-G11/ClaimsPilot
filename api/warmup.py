"""Warm the models when the API starts, so the first claim does not pay the
loading time (build log entries 10, 11, 13 and 20):

- the policy LLM (Ollama loads qwen2.5:7b; on CPU it can pass llm.timeout_seconds);
- vision (YOLO weights + a first inference on a blank image);
- retrieval (embedding model + Chroma collection + a first query);
- the LangGraph decision graph (its first import and build).

Two background threads (the LLM in one, the agents in the other): the API starts
and answers /health at once. Each step that fails (library or file missing, no
Ollama...) is only logged. CLAIMSPILOT_WARMUP=0 turns everything off (tests, CI).

`status()` gives the state of each step for /health and /ready:
"pending" (not started), "running", "done", "failed" (finished with an error,
the first claim may be slow) or "off" (warm-up turned off).
"""
import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPT = "Réponds seulement : OK."
STEPS = ("llm", "vision", "retrieval", "decision")
FINISHED = {"done", "failed", "off"}
_status = dict.fromkeys(STEPS, "pending")
_lock = threading.Lock()


def status() -> dict:
    """A copy of the state of each warm-up step."""
    with _lock:
        return dict(_status)


def is_ready() -> bool:
    """True when every step has finished (done, failed or off)."""
    return all(state in FINISHED for state in status().values())


def _set(step: str, state: str) -> None:
    with _lock:
        _status[step] = state


def _run_step(step: str, warm) -> bool:
    """Run one warm-up and record its state. Never raises."""
    _set(step, "running")
    ok = warm()
    _set(step, "done" if ok else "failed")
    return ok


def warm_policy_llm(generate=None) -> bool:
    """One short call to the policy LLM. True if it answered; never raises."""
    try:
        from agents.policy import generation

        (generate or generation.default_generator())(PROMPT)
    except Exception as error:  # noqa: BLE001 - warm-up must never stop the API
        logger.warning("policy LLM warm-up failed (the first claim may be slow): %s", error)
        return False
    logger.info("policy LLM warmed up")
    return True


def warm_vision() -> bool:
    """Load YOLO and run one inference through the public run() on a blank image."""
    try:
        import cv2
        import numpy as np

        from agents.vision.agent import run
        from claimspilot.schemas import ClaimInput

        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "blank.jpg"
            cv2.imwrite(str(photo), np.full((640, 640, 3), 255, dtype=np.uint8))
            run(ClaimInput(claim_id="warm-up", photo_paths=[str(photo)], text="",
                           policy_id="warm-up"))
    except Exception as error:  # noqa: BLE001
        logger.warning("vision warm-up failed (the first claim may be slow): %s", error)
        return False
    logger.info("vision warmed up")
    return True


def warm_retrieval() -> bool:
    """Load the embedding model and the Chroma collection with one real query."""
    try:
        from agents.policy.agent import retrieve

        retrieve("Collision, pare-chocs avant enfoncé.", "AXA", ["collision"], 1, False)
    except Exception as error:  # noqa: BLE001
        logger.warning("retrieval warm-up failed (the first claim may be slow): %s", error)
        return False
    logger.info("retrieval warmed up")
    return True


def warm_decision() -> bool:
    """Import and build Wiem's LangGraph graph once, with her stub results."""
    try:
        from agents.decision import agent, stubs
        from claimspilot.schemas import ClaimInput

        claim = ClaimInput(claim_id="warm-up", photo_paths=[], text="", policy_id="warm-up")
        vision = stubs.vision_stub(claim)
        agent.run(claim, vision, stubs.nlp_stub(claim, vision), stubs.policy_stub(claim, vision))
    except Exception as error:  # noqa: BLE001
        logger.warning("decision graph warm-up failed (the first claim may be slow): %s", error)
        return False
    logger.info("decision graph warmed up")
    return True


def warm_agents() -> dict:
    """Vision, retrieval and decision, one after the other. Never raises."""
    return {"vision": _run_step("vision", warm_vision),
            "retrieval": _run_step("retrieval", warm_retrieval),
            "decision": _run_step("decision", warm_decision)}


def warm_llm_step() -> bool:
    return _run_step("llm", warm_policy_llm)


def start_warmup() -> list[threading.Thread]:
    """Start the warm-ups in daemon threads ([] when CLAIMSPILOT_WARMUP=0)."""
    if os.getenv("CLAIMSPILOT_WARMUP", "1") == "0":
        for step in STEPS:
            _set(step, "off")
        return []
    for step in STEPS:
        _set(step, "pending")
    threads = [threading.Thread(target=warm_llm_step, name="policy-llm-warmup", daemon=True),
               threading.Thread(target=warm_agents, name="agents-warmup", daemon=True)]
    for thread in threads:
        thread.start()
    return threads
