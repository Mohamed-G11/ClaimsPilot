"""Warm the policy LLM when the API starts, so the first claim does not pay the
model loading time (on CPU it can pass llm.timeout_seconds and fall back to the
template answer; build log entries 10 and 11).

The call runs in a background thread: the API starts and answers /health at
once, whatever Ollama does. A failure (no Ollama, LLM disabled, timeout) is only
logged. CLAIMSPILOT_WARMUP=0 turns it off (tests, CI).
"""
import logging
import os
import threading

logger = logging.getLogger(__name__)

PROMPT = "Réponds seulement : OK."


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


def start_warmup() -> threading.Thread | None:
    """Start the warm-up in a daemon thread (None when CLAIMSPILOT_WARMUP=0)."""
    if os.getenv("CLAIMSPILOT_WARMUP", "1") == "0":
        return None
    thread = threading.Thread(target=warm_policy_llm, name="policy-llm-warmup", daemon=True)
    thread.start()
    return thread
