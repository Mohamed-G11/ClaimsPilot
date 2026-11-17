"""Policy agent tests: no embedding model, no Chroma, no PDF, no Ollama.

The retriever and the generator are parameters of run(), so the tests pass fakes.
"""
import pytest

from agents.policy import agent, generation
from claimspilot.schemas import ClaimInput, Damage, PolicyResult, VisionResult

CLAUSES = {
    "collision": ("015", "Dommages collision", "016", "Exclusions de la garantie collision"),
    "tous_risques": ("013", "Dommage tous accidents", "014", "Exclusions tous accidents"),
    "bris_de_glace": ("021", "Bris de glaces", "022", "Exclusions bris de glaces"),
    "vol": ("019", "Vol du véhicule", "020", "Exclusions vol"),
    "incendie": ("017", "Incendie du véhicule", "018", "Exclusions incendie"),
    "vandalisme": ("060", "Actes de vandalisme", "061", "Exclusions vandalisme"),
    "exclusions_generales": (None, None, "023", "Les exclusions communes"),
}


def fake_retriever(query, insurer, guarantees, k, exclusions):
    """One clause per guarantee, shaped like the real retriever's output."""
    found = []
    for guarantee in guarantees:
        number, title, x_number, x_title = CLAUSES.get(guarantee, (None, None, None, None))
        chosen = (x_number, x_title) if exclusions else (number, title)
        if chosen[0]:
            found.append({"clause_id": f"{insurer}-{chosen[0]}", "title": chosen[1], "page": 18,
                          "text": f"Texte de la clause {chosen[1]}.", "relevance": 0.71,
                          "guarantee": guarantee, "is_exclusion": exclusions})
    return found[:k]


def empty_retriever(query, insurer, guarantees, k, exclusions):
    return []


def claim(policy_id, text="Collision sur un parking, pare-chocs avant enfoncé."):
    return ClaimInput(claim_id="C1", photo_paths=[], text=text, policy_id=policy_id)


def vision(*damages):
    return VisionResult(claim_id="C1", severity="moderate", model_version="test",
                        damages=[Damage(part=p, damage_type=t, bbox=[0, 0, 1, 1],
                                        confidence=0.8) for p, t in damages])


BUMPER = vision(("front_bumper", "dent"))
WINDSHIELD = vision(("windshield", "crack"))


def run(policy_id, text, seen, generator=generation.no_generator, retriever=fake_retriever):
    return agent.analyze(claim(policy_id, text), seen, retriever=retriever, generator=generator)


# --- contract and formula ----------------------------------------------------

def test_returns_policy_result_with_evidence():
    result = agent.run(claim("AXA-TR"), BUMPER, retriever=fake_retriever,
                       generator=generation.no_generator)
    assert isinstance(result, PolicyResult)
    assert result.covered is True
    assert [c.clause_id for c in result.clauses] == ["AXA-015", "AXA-013", "AXA-016", "AXA-014"]


def test_third_party_formula_does_not_cover_own_damage():
    analysis = run("AXA-TIERS", "Collision sur un parking.", BUMPER)
    assert analysis.result.covered is False
    assert analysis.result.clauses                      # evidence is still returned
    assert "NON COUVERT" in analysis.result.answer


def test_unknown_contract_is_uncertain():
    assert run("FOO-TR", "Collision.", BUMPER).result.covered is None
    assert run("AXA-GOLD", "Collision.", BUMPER).result.covered is None


def test_policy_id_parsing():
    assert agent.parse_policy_id("sanlam-tr") == ("SANLAM", "TR")


# --- cause from the text, photos must agree -----------------------------------

def test_cause_and_compatible_photos():
    analysis = run("SANLAM-TR", "Un gravillon a fissuré mon pare-brise.", WINDSHIELD)
    assert analysis.cause == "bris_de_glace"
    assert analysis.result.covered is True
    assert analysis.result.clauses[0].clause_id == "SANLAM-021"


def test_cause_and_incompatible_photos_go_to_human():
    analysis = run("SANLAM-TR", "Un gravillon a fissuré mon pare-brise.", BUMPER)
    assert analysis.step == "incompatible"
    assert analysis.result.covered is None
    assert "Incohérence" in analysis.result.answer
    assert "pare-chocs avant" in analysis.result.answer


def test_cause_needing_damage_but_no_damage_goes_to_human():
    analysis = run("AXA-TR", "Collision avec un autre véhicule.", vision())
    assert analysis.result.covered is None
    assert "aucun dommage" in analysis.result.answer


def test_theft_needs_no_damage_on_photos():
    analysis = run("AXA-TR", "On a volé ma voiture cette nuit.", vision())
    assert analysis.cause == "vol"
    assert analysis.result.covered is True
    assert analysis.result.clauses[0].clause_id == "AXA-019"


def test_theft_is_not_covered_by_third_party_formula():
    assert run("SANLAM-TIERS", "Ma voiture a été volée.", vision()).result.covered is False


def test_no_cause_deduces_guarantee_from_damages():
    analysis = run("AXA-TR", "Le pare-chocs avant est enfoncé.", BUMPER)
    assert analysis.cause is None
    assert analysis.needed == ["collision", "tous_risques"]
    assert analysis.result.covered is True
    assert "Cause non précisée" in analysis.result.answer


def test_no_cause_and_no_damage_is_uncertain():
    analysis = run("SANLAM-TR", "Ma voiture est abîmée.", vision())
    assert analysis.step == "nothing_to_check"
    assert analysis.result.covered is None


# --- exclusions ---------------------------------------------------------------

@pytest.mark.parametrize("policy_id", ["AXA-TR", "AXA-TIERS"])
def test_exclusion_in_text_goes_to_human_never_reject(policy_id):
    analysis = run(policy_id, "Collision : j'avais bu de l'alcool avant de conduire.", BUMPER)
    assert analysis.step == "exclusion"
    assert analysis.exclusions == ["alcool"]
    assert analysis.result.covered is None
    assert "alcool" in analysis.result.answer
    # evidence = general exclusions + exclusions of the guarantees concerned
    assert [c.clause_id for c in analysis.result.clauses] == ["AXA-023", "AXA-016", "AXA-014"]


# --- guarantees outside the formulas, missing evidence -------------------------

def test_guarantee_in_no_formula_goes_to_human():
    analysis = run("SANLAM-TR", "Voiture endommagée par une inondation.", vision())
    assert analysis.step == "guarantee_not_in_formulas"
    assert analysis.result.covered is None


def test_covered_without_any_clause_goes_to_human():
    analysis = run("AXA-TR", "Collision sur un parking.", BUMPER, retriever=empty_retriever)
    assert analysis.step == "no_evidence"
    assert analysis.result.covered is None


# --- generation: the LLM explains, the rules decide ----------------------------

def test_template_answer_when_the_llm_is_unavailable():
    analysis = run("AXA-TR", "Collision sur un parking.", BUMPER)
    assert analysis.generator == "template"
    assert analysis.result.model_version == "policy-rag-v2+template"
    assert analysis.result.answer.startswith("Décision : COUVERT")
    assert "AXA-015" in generation.cited_clauses(analysis.result.answer)


def test_llm_answer_is_used_when_it_agrees_with_the_rule():
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return "Décision : COUVERT. La collision est garantie par la formule TR [AXA-015]."

    analysis = run("AXA-TR", "Collision sur un parking.", BUMPER, generator=fake_llm)
    assert analysis.generator == "llm"
    assert analysis.result.covered is True
    assert analysis.result.answer.endswith("[AXA-015].")
    assert analysis.result.model_version == "policy-rag-v2+phi3.5"
    # the LLM only sees the claim and the retrieved clauses
    assert "Collision sur un parking." in prompts[0]
    assert "[AXA-015] Dommages collision" in prompts[0]


def test_llm_contradicting_the_rule_goes_to_human():
    def wrong_llm(prompt):
        return "Décision : NON COUVERT. Le contrat ne prévoit rien [AXA-016]."

    analysis = run("AXA-TR", "Collision sur un parking.", BUMPER, generator=wrong_llm)
    assert analysis.step == "llm_contradiction"
    assert analysis.rule_covered is True
    assert analysis.llm_verdict is False
    assert analysis.result.covered is None


def test_llm_answer_without_decision_falls_back_to_the_template():
    analysis = run("AXA-TR", "Collision sur un parking.", BUMPER,
                   generator=lambda prompt: "Je ne sais pas trop.")
    assert analysis.generator == "template"
    assert analysis.result.covered is True
    assert analysis.result.model_version == "policy-rag-v2+template"


def test_llm_is_not_called_when_a_human_must_decide():
    def never(prompt):
        raise AssertionError("the LLM must not be called")

    assert run("AXA-TR", "Collision en état d'ébriété.", BUMPER,
               generator=never).result.covered is None
    assert run("AXA-TR", "Pare-brise fissuré.", BUMPER, generator=never).result.covered is None


# --- generation helpers --------------------------------------------------------

def test_read_verdict():
    assert generation.read_verdict("Décision : COUVERT. Parce que...") is True
    assert generation.read_verdict("**Décision : NON COUVERT**") is False
    assert generation.read_verdict("Le sinistre semble couvert.") is None


def test_ollama_unreachable_raises_generator_unavailable(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")     # nothing listens there
    with pytest.raises(generation.GeneratorUnavailable):
        generation.ollama_generate("Bonjour")


# --- query builder --------------------------------------------------------------

def test_query_has_the_claim_text_and_the_damages_in_french():
    query = agent.build_query(claim("AXA-TR", "Choc à l'avant."),
                              vision(("windshield", "crack"), ("rear_bumper", "dent")))
    assert query.startswith("Choc à l'avant.")
    assert "fissure pare-brise" in query
    assert "pare-chocs arrière" in query


def test_query_keeps_unknown_words_as_they_are():
    query = agent.build_query(claim("AXA-TR"), vision(("roof", "hole")))
    assert "hole roof" in query
