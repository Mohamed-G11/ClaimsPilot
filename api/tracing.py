"""Optional Langfuse tracing: one trace per claim, one observation per step.

Tracing is ON only when all of this is true:
- the `langfuse` package is installed (full Docker image: requirements-docker.txt);
- LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (docker compose: from .env);
- CLAIMSPILOT_TRACING is not "0" (kill switch).
LANGFUSE_BASE_URL (or the older LANGFUSE_HOST) selects the Langfuse server.

When tracing is off, nothing is created and every helper here is a no-op, so the
pipeline behaves exactly as without this module. When it is on, any error of
Langfuse itself is logged and ignored: tracing can never break a claim. Data is
sent by Langfuse's background thread, so a claim is not slowed by the network.

    with claim_trace(claim) as root:                 # trace named with the claim_id
        with observe("vision") as step:
            ...
            step.update(output=...)
        root.update(output=...)
"""
import importlib.util
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache

logger = logging.getLogger(__name__)

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
# Langfuse callback handler for LangChain / LangGraph runs started inside
# langchain_callbacks() (see there). None = no handler.
_langchain_handler: ContextVar = ContextVar("claimspilot_langfuse_handler", default=None)


def enabled() -> bool:
    """Keys set, kill switch not used, library installed."""
    return (os.getenv("CLAIMSPILOT_TRACING", "1") != "0"
            and all(os.getenv(key) for key in KEYS)
            and importlib.util.find_spec("langfuse") is not None)


@cache
def client():
    """The Langfuse client, created once; None when tracing is off or cannot start."""
    if not enabled():
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                        base_url=os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
                        or None,
                        timeout=5)
    except Exception as error:  # noqa: BLE001 - tracing must never break the API
        logger.warning("Langfuse tracing disabled: %s", error)
        return None


class Observation:
    """A Langfuse observation, or nothing when tracing is off. Its methods never raise."""

    def __init__(self, observation=None):
        self._observation = observation

    @property
    def trace_id(self) -> str | None:
        return getattr(self._observation, "trace_id", None)

    def update(self, **fields) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**fields)
        except Exception as error:  # noqa: BLE001
            logger.debug("Langfuse update failed: %s", error)


def _exit_quietly(context) -> None:
    try:
        context.__exit__(None, None, None)
    except Exception as error:  # noqa: BLE001
        logger.debug("Langfuse end of observation failed: %s", error)


@contextmanager
def observe(name: str, as_type: str = "span", **fields):
    """A child observation of the current one (or the root when there is none).

    Errors of the code inside the block are re-raised unchanged (after marking the
    observation as ERROR); errors of Langfuse itself are ignored.
    """
    langfuse = client()
    context = None
    if langfuse is not None:
        try:
            context = langfuse.start_as_current_observation(name=name, as_type=as_type,
                                                             **fields)
            observation = Observation(context.__enter__())
        except Exception as error:  # noqa: BLE001
            logger.debug("Langfuse observation %s not started: %s", name, error)
            context = None
    if context is None:
        yield Observation()
        return
    try:
        yield observation
    except BaseException as error:
        observation.update(level="ERROR", status_message=f"{type(error).__name__}: {error}"[:300])
        _exit_quietly(context)
        raise
    _exit_quietly(context)


def _propagate(trace_name: str, claim_id: str):
    """Trace-level attributes for every observation created inside (Langfuse v5)."""
    from langfuse import propagate_attributes

    return propagate_attributes(trace_name=trace_name, metadata={"claim_id": claim_id},
                                tags=["claimspilot"])


@contextmanager
def claim_trace(claim):
    """The root observation of one claim; the trace is named with the claim_id."""
    with observe("claim", input=claim.model_dump()) as root:
        attributes = None
        if root._observation is not None:
            try:
                attributes = _propagate(claim.claim_id, claim.claim_id)
                attributes.__enter__()
            except Exception as error:  # noqa: BLE001
                logger.debug("Langfuse trace attributes not set: %s", error)
                attributes = None
        try:
            yield root
        finally:
            if attributes is not None:
                _exit_quietly(attributes)


@cache
def _register_langchain_hook() -> bool:
    """Tell LangChain to add the handler of _langchain_handler to every run (once)."""
    from langchain_core.tracers.context import register_configure_hook

    register_configure_hook(_langchain_handler, inheritable=True)
    return True


@contextmanager
def langchain_callbacks():
    """Inside this block, LangChain / LangGraph runs report to the current trace.

    LangChain adds the handler stored in a registered context variable to every
    run it configures, so Wiem's graph (agents/decision/agent.py) shows its nodes
    in the claim's trace without any change to her code.
    """
    token = None
    if client() is not None:
        try:
            from langfuse.langchain import CallbackHandler

            _register_langchain_hook()
            token = _langchain_handler.set(
                CallbackHandler(public_key=os.environ["LANGFUSE_PUBLIC_KEY"]))
        except Exception as error:  # noqa: BLE001 - no langchain_core, old langfuse...
            logger.debug("Langfuse LangChain handler not set: %s", error)
    try:
        yield
    finally:
        if token is not None:
            _langchain_handler.reset(token)
