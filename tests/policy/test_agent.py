"""Policy agent tests: no embedding model, no Chroma, no PDF needed (fake retriever)."""
from agents.policy import agent
from claimspilot.schemas import ClaimInput, Damage, PolicyResult, VisionResult


def fake_retriever(query, insurer, guarantees, k):
    return [{"clause_id": f"{insurer}-015", "title": "Dommages collision", "page": 18,
             "text": "Nous garantissons les dommages consécutifs à une collision.",
             "relevance": 0.71, "guarantee": "collision", "is_exclusion": False}]


def claim(policy_id):
    return ClaimInput(claim_id="C1", photo_paths=[], text="Pare-chocs avant enfoncé.",
                      policy_id=policy_id)


def vision(*damages):
    return VisionResult(claim_id="C1", severity="moderate", model_version="test",
                        damages=[Damage(part=p, damage_type=t, bbox=[0, 0, 1, 1],
                                        confidence=0.8) for p, t in damages])


BUMPER = vision(("front_bumper", "dent"))


def test_returns_policy_result_with_evidence():
    result = agent.run(claim("AXA-TR"), BUMPER, retriever=fake_retriever)
    assert isinstance(result, PolicyResult)
    assert result.covered is True
    assert result.clauses[0].clause_id == "AXA-015"


def test_third_party_formula_does_not_cover_own_damage():
    assert agent.run(claim("AXA-TIERS"), BUMPER, retriever=fake_retriever).covered is False


def test_unknown_contract_is_uncertain():
    assert agent.run(claim("FOO-TR"), BUMPER, retriever=fake_retriever).covered is None


def test_no_damage_is_uncertain():
    assert agent.run(claim("SANLAM-TR"), vision(), retriever=fake_retriever).covered is None


def test_glass_damage_needs_glass_guarantee_first():
    needed = agent.needed_guarantees(vision(("windshield", "crack")))
    assert needed[0] == "bris_de_glace"


def test_query_has_the_claim_text_and_the_damages_in_french():
    query = agent.build_query(claim("AXA-TR"), vision(("windshield", "crack"),
                                                     ("rear_bumper", "dent")))
    assert query.startswith("Pare-chocs avant enfoncé.")
    assert "fissure pare-brise" in query
    assert "pare-chocs arrière" in query


def test_query_keeps_unknown_words_as_they_are():
    query = agent.build_query(claim("AXA-TR"), vision(("roof", "hole")))
    assert "hole roof" in query


def test_policy_id_parsing():
    assert agent.parse_policy_id("sanlam-tr") == ("SANLAM", "TR")
