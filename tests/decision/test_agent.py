"""LangGraph orchestration (skipped when langgraph is not installed, e.g. in CI)."""
import pytest

pytest.importorskip("yaml")
pytest.importorskip("langgraph")
agent = pytest.importorskip("agents.decision.agent")
stubs = pytest.importorskip("agents.decision.stubs")
rules = pytest.importorskip("agents.decision.rules")
schemas = pytest.importorskip("claimspilot.schemas")

CLAIM = schemas.ClaimInput(claim_id="C-2", photo_paths=["car.jpg"], text="Rear bumper hit.",
                           policy_id="P-1")


def test_run_matches_the_rules():
    v = stubs.vision_stub(CLAIM)
    n, p = stubs.nlp_stub(CLAIM, v), stubs.policy_stub(CLAIM, v)
    d = agent.run(CLAIM, v, n, p)
    assert isinstance(d, schemas.Decision)
    assert d == rules.decide(CLAIM, v, n, p)


def test_process_claim_runs_nodes_in_order():
    calls = []

    def vision_fn(claim):
        calls.append("vision")
        return stubs.vision_stub(claim)

    def nlp_fn(claim, vision):
        calls.append("nlp")
        return stubs.nlp_stub(claim, vision)

    def policy_fn(claim, vision):
        calls.append("policy")
        return stubs.policy_stub(claim, vision)

    d = agent.process_claim(CLAIM, vision_fn, nlp_fn, policy_fn)
    assert calls == ["vision", "nlp", "policy"]
    assert d.claim_id == "C-2"
    assert d.decision in {"approve", "reject", "human_review"}


def test_run_does_not_call_agents_again():
    def boom(*_):
        raise AssertionError("agents must not be called when results are given")

    graph = agent.build_graph(boom, boom, boom)
    v = stubs.vision_stub(CLAIM)
    state = graph.invoke({"claim": CLAIM, "vision": v, "nlp": stubs.nlp_stub(CLAIM, v),
                          "policy": stubs.policy_stub(CLAIM, v)})
    assert isinstance(state["decision"], schemas.Decision)