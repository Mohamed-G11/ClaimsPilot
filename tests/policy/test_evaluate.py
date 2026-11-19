"""Evaluation script tests: fake retriever, no LLM, no MLflow, no data file."""
from agents.policy import evaluate, generation
from tests.policy.test_agent import fake_retriever

CASES = [
    {"claim_id": "T1", "policy_id": "AXA-TR", "language": "fr",
     "text": "Collision sur un parking.", "damages": "front_bumper:dent",
     "expected_covered": "true", "expected_clauses": "AXA-015|AXA-013",
     "category": "collision", "note": ""},
    {"claim_id": "T2", "policy_id": "AXA-TIERS", "language": "fr",
     "text": "On a volé ma voiture.", "damages": "",
     "expected_covered": "true", "expected_clauses": "AXA-999",      # wrong on purpose
     "category": "vol", "note": ""},
    {"claim_id": "T3", "policy_id": "AXA-TR", "language": "fr",
     "text": "Pare-brise fissuré.", "damages": "door:dent",
     "expected_covered": "none", "expected_clauses": "",
     "category": "incompatible", "note": ""},
]


def test_inputs_from_a_csv_row():
    claim, vision = evaluate.to_inputs(CASES[0])
    assert claim.policy_id == "AXA-TR"
    assert [(d.part, d.damage_type) for d in vision.damages] == [("front_bumper", "dent")]
    assert evaluate.to_inputs(CASES[1])[1].damages == []


def test_metrics_on_three_cases():
    report = evaluate.evaluate(CASES, retriever=fake_retriever,
                               generator=generation.no_generator)
    metrics = report["metrics"]
    assert [row["correct"] for row in report["rows"]] == [True, False, True]
    assert metrics["n_claims"] == 3
    assert metrics["coverage_accuracy"] == round(2 / 3, 4)
    assert metrics["clause_hit_at_4"] == 0.5            # T3 has no expected clause: skipped
    assert metrics["answer_cites_correct"] == 0.5
    assert metrics["llm_agrees_with_rule"] is None      # no LLM answer
    assert metrics["template_answers"] == 2
    assert metrics["accuracy_vol"] == 0.0


def test_llm_agreement_is_measured():
    def fake_llm(prompt):
        return "Décision : COUVERT. [AXA-015]"

    report = evaluate.evaluate(CASES[:2], retriever=fake_retriever, generator=fake_llm)
    # T1: rule says covered, LLM agrees. T2: rule says not covered, LLM contradicts.
    assert report["metrics"]["llm_agrees_with_rule"] == 0.5
    assert report["rows"][1]["covered"] is None


# --- LLM comparison metrics ------------------------------------------------------

def test_llm_metrics_on_a_good_and_an_invented_answer():
    answers = iter(["Décision : COUVERT. La collision est garantie [AXA-015].",
                    "Décision : NON COUVERT. Le vol n'est pas garanti [AXA-777]."])
    report = evaluate.evaluate(CASES, retriever=fake_retriever,
                               generator=lambda prompt: next(answers))
    m = report["metrics"]
    assert m["llm_calls"] == 2                     # T3 (incompatible) never calls the LLM
    assert m["llm_fallback_rate"] == 0.0
    assert m["llm_cites_retrieved"] == 0.5
    assert m["llm_invented_citation"] == 0.5       # AXA-777 was not retrieved
    assert m["llm_format_ok"] == 1.0
    assert m["llm_wrong_language"] == 0.0
    assert report["rows"][2]["llm_called"] is False


def test_fallback_reasons_are_counted():
    def cut(prompt):
        raise generation.GeneratorUnavailable("answer cut by max_tokens (1024) on qwen3:4b")

    m = evaluate.evaluate(CASES[:1], retriever=fake_retriever, generator=cut)["metrics"]
    assert m["llm_fallback_rate"] == 1.0 and m["llm_fallback_cut"] == 1
    m = evaluate.evaluate(CASES[:1], retriever=fake_retriever,
                          generator=lambda prompt: "I think it is covered.")["metrics"]
    assert m["llm_fallback_no_verdict"] == 1
    assert m["llm_wrong_language"] == 1.0 and m["llm_format_ok"] == 0.0


def test_no_llm_run_has_no_llm_calls():
    m = evaluate.evaluate(CASES, retriever=fake_retriever,
                          generator=generation.no_generator)["metrics"]
    assert m["llm_calls"] == 0


def test_format_and_language_checks():
    assert evaluate.format_ok("**Décision : NON COUVERT**. Une. Deux. Trois.")
    assert not evaluate.format_ok("Décision : COUVERT. Un. Deux. Trois. Quatre.")
    assert not evaluate.format_ok("Le sinistre est couvert.")
    assert evaluate.wrong_language("Okay, the user is asking about the policy.")
    assert not evaluate.wrong_language("La garantie collision est incluse dans la formule.")
