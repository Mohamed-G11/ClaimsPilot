"""End-to-end tests: HTTP request -> real vision, NLP and policy agent code -> decision.

The agents' own code runs (mapping, severity, keyword extraction, cause rules,
formula check, decision rules). Only what needs a model or a database is faked:
- vision: `_detect` (YOLO) returns chosen detections;
- policy: the retriever (Chroma) and the generator (Ollama) are fakes.
So nothing is downloaded and no optional library is needed.
"""
import pytest
from fastapi.testclient import TestClient

from agents.policy import agent as policy_agent
from agents.policy import generation
from agents.policy.index import EmptyIndexError
from agents.vision import agent as vision_agent
from api import pipeline
from api.main import app
from tests.policy.test_agent import fake_retriever

client = TestClient(app)


def detection(class_name: str):
    """A YOLO detection of one of the vision model's classes (class_mapping_merged.yaml)."""
    return vision_agent.Detection(class_name, [10.0, 20.0, 110.0, 220.0], 0.9, 0.05)


@pytest.fixture
def photo(tmp_path) -> str:
    path = tmp_path / "car.jpg"
    path.write_bytes(b"not a real image, detection is faked")
    return str(path)


@pytest.fixture
def real_agents(monkeypatch):
    """Real agent code with fake model / index / LLM. Returns a dict to tune the fakes."""
    fakes = {"detections": [detection("front_bumper-dent")], "retriever": fake_retriever,
             "llm": generation.no_generator}
    monkeypatch.setattr(pipeline, "_has_library", lambda name: True)
    monkeypatch.setattr(vision_agent, "_detect", lambda _path: fakes["detections"])
    monkeypatch.setattr(policy_agent, "retrieve",
                        lambda *args: fakes["retriever"](*args))
    monkeypatch.setattr(generation, "default_generator",
                        lambda: lambda prompt: fakes["llm"](prompt))
    return fakes


def analyze(photo, text, policy_id="AXA-TR"):
    claim = {"claim_id": "E2E-1", "photo_paths": [photo], "text": text, "policy_id": policy_id}
    response = client.post("/claims/analyze", json=claim)
    assert response.status_code == 200
    return response.json()


COLLISION = "Collision sur un parking, le pare-chocs avant est enfoncé."


def test_consistent_covered_claim_is_approved_by_real_agents(real_agents, photo):
    body = analyze(photo, COLLISION)
    assert body["agents"] == {"vision": "real", "nlp": "real", "policy": "real",
                              "decision": "rules (api/pipeline.py)"}
    assert body["vision"]["damages"][0]["part"] == "front_bumper"
    assert body["nlp"]["consistency"] == "consistent"
    assert body["policy"]["covered"] is True
    assert body["policy"]["model_version"] == "policy-rag-v2+template"
    assert body["decision"]["decision"] == "approve"


def test_claims_route_gives_the_same_decision_as_analyze(real_agents, photo):
    claim = {"claim_id": "E2E-1", "photo_paths": [photo], "text": COLLISION,
             "policy_id": "AXA-TR"}
    decision = client.post("/claims", json=claim).json()
    assert decision == client.post("/claims/analyze", json=claim).json()["decision"]
    assert decision["decision"] == "approve"


def test_third_party_contract_is_rejected(real_agents, photo):
    body = analyze(photo, COLLISION, policy_id="SANLAM-TIERS")
    assert body["policy"]["covered"] is False
    assert body["decision"]["decision"] == "reject"


def test_text_and_photos_disagreeing_goes_to_human(real_agents, photo):
    body = analyze(photo, "Un gravillon a fissuré mon pare-brise.")     # photo: dented bumper
    assert body["policy"]["covered"] is None
    assert body["decision"]["decision"] == "human_review"


def test_exclusion_in_text_goes_to_human(real_agents, photo):
    body = analyze(photo, COLLISION + " J'avais bu de l'alcool.")
    assert body["policy"]["covered"] is None
    assert "alcool" in body["policy"]["answer"]
    assert body["decision"]["decision"] == "human_review"


def test_llm_answer_is_returned_when_it_agrees(real_agents, photo):
    real_agents["llm"] = lambda prompt: "Décision : COUVERT. Collision garantie [AXA-015]."
    body = analyze(photo, COLLISION)
    assert body["policy"]["answer"].endswith("[AXA-015].")
    assert body["policy"]["model_version"] == f"policy-rag-v2+{generation.CONFIG['llm']['model']}"
    assert body["decision"]["decision"] == "approve"


def test_llm_contradicting_the_rule_goes_to_human(real_agents, photo):
    real_agents["llm"] = lambda prompt: "Décision : NON COUVERT."
    body = analyze(photo, COLLISION)
    assert body["policy"]["covered"] is None
    assert body["decision"]["decision"] == "human_review"


def test_nothing_detected_goes_to_human(real_agents, photo):
    real_agents["detections"] = []
    body = analyze(photo, COLLISION)
    assert body["agents"]["vision"] == "real"
    assert body["vision"]["damages"] == []
    assert body["decision"]["decision"] == "human_review"


def test_missing_vision_weights_fall_back_to_the_stub(real_agents, photo, monkeypatch):
    def no_weights(_path):
        raise FileNotFoundError("Vision weights not found (run `dvc pull`)")

    monkeypatch.setattr(vision_agent, "_detect", no_weights)
    body = analyze(photo, COLLISION)
    assert body["agents"]["vision"].startswith("stub (FileNotFoundError")
    assert body["agents"]["nlp"] == "real"
    assert body["decision"]["decision"] == "human_review"
    assert "vision" in body["decision"]["reasons"][0]


def test_empty_policy_index_falls_back_to_the_stub(real_agents, photo):
    def empty_index(*_args):
        raise EmptyIndexError("The policy index is empty.")

    real_agents["retriever"] = empty_index
    body = analyze(photo, COLLISION)
    assert body["agents"]["policy"].startswith("stub (EmptyIndexError")
    assert body["decision"]["decision"] == "human_review"
    assert "policy" in body["decision"]["reasons"][0]


def test_missing_vision_library_falls_back_to_the_stub(real_agents, photo, monkeypatch):
    monkeypatch.setattr(pipeline, "_has_library", lambda name: False)
    body = analyze(photo, COLLISION)
    assert body["agents"]["vision"].startswith("stub (ImportError")
    assert body["decision"]["decision"] == "human_review"
