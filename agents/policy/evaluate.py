"""Evaluate the policy agent on the labelled claims of data/policy/eval_claims.csv.

Usage:  python -m agents.policy.evaluate            (real index + Ollama if it answers)
        python -m agents.policy.evaluate --model qwen2.5:7b --max-tokens 1024             --prompt-variant explain_rule          (this run only; config.yaml unchanged)
        python -m agents.policy.evaluate --no-llm   (template answers only)

Each CSV row is one claim: the text, the contract, the damages vision would have
seen ("part:type|part:type") and what a claims handler expects:
`expected_covered` (true / false / none) and `expected_clauses` (any of these
clause ids is a correct piece of evidence).

Metrics on all claims
- coverage_accuracy      share of claims where covered == expected (target >= 0.85)
- clause_hit_at_4        share of claims with a correct clause among the <= 4 returned
                         (target >= 0.80; claims without expected clause are skipped)
- answer_cites_correct   share of answers citing a correct clause id, e.g. "[AXA-015]"
- latency_*              seconds per claim (the first call loads the embedding model)

Metrics on the claims that call the LLM (only claims whose rules give True / False)
- llm_calls              number of claims that called the LLM
- llm_seconds_*          seconds per LLM call: mean, median, max
- llm_fallback_rate      share of calls ending in the template answer, and by reason:
                         _timeout, _cut (max_tokens on a reasoning model), _error
                         (other error), _no_verdict (no readable "Décision : ...")
- llm_agrees_with_rule   among the answers written by the LLM, share agreeing with the rule
- llm_contradiction_rate share of calls where the LLM contradicts the rule (covered=None)
- llm_cites_retrieved    share of LLM texts citing at least one retrieved clause id
- llm_invented_citation  share of LLM texts citing a clause id that was NOT retrieved
- llm_format_ok          share of LLM texts starting with "Décision : (NON) COUVERT" with
                         at most 4 sentences (the decision line + 2 or 3 sentences asked)
- llm_wrong_language     share of LLM texts with more English than French stopwords
                         (the prompt asks French; leaked reasoning is in English)

Results go to MLflow (experiment claimspilot-policy) when credentials exist, and
always to data/policy/eval_results.json.
"""
import argparse
import csv
import json
import re
import statistics
import time
from pathlib import Path

from agents.policy import agent, generation
from agents.policy.rules import normalize
from agents.policy.settings import CONFIG, REPO_ROOT, data_path
from claimspilot.schemas import ClaimInput, Damage, VisionResult
from mlops import tracking

EVAL_FILE = REPO_ROOT / "data/policy/eval_claims.csv"
RESULTS_FILE = REPO_ROOT / "data/policy/eval_results.json"
EXPERIMENT = "claimspilot-policy"
COVERED = {"true": True, "false": False, "none": None}
DATA = ["data/policy/raw", "data/policy/processed", "data/policy/eval_claims.csv"]

FRENCH = {"le", "la", "les", "des", "du", "de", "est", "et", "en", "une", "un", "pas",
          "par", "pour", "dans", "sur", "au", "aux", "ce", "qui", "que", "sont", "il"}
ENGLISH = {"the", "is", "and", "of", "to", "in", "this", "that", "it", "for", "with",
           "not", "are", "be", "user", "let", "me", "so", "should", "i"}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def load_cases(path: Path = EVAL_FILE) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_inputs(case: dict) -> tuple[ClaimInput, VisionResult]:
    """One CSV row -> the two objects the agent receives."""
    claim = ClaimInput(claim_id=case["claim_id"], photo_paths=[], text=case["text"],
                       policy_id=case["policy_id"], language=case["language"])
    pairs = [item.split(":") for item in case["damages"].split("|") if item]
    damages = [Damage(part=part, damage_type=kind, bbox=[0, 0, 1, 1], confidence=0.9)
               for part, kind in pairs]
    vision = VisionResult(claim_id=case["claim_id"], damages=damages, severity="moderate",
                          model_version="eval-set")
    return claim, vision


class RecordingGenerator:
    """Wraps a generator and records the last call: seconds, raw text, error."""

    def __init__(self, generate: generation.Generator):
        self.generate = generate
        self.reset()

    def reset(self) -> None:
        self.called, self.seconds, self.text, self.error = False, None, None, None

    def __call__(self, prompt: str) -> str:
        self.called = True
        start = time.perf_counter()
        try:
            self.text = self.generate(prompt)
            return self.text
        except generation.GeneratorUnavailable as error:
            self.error = str(error)
            raise
        finally:
            self.seconds = round(time.perf_counter() - start, 3)


def fallback_reason(llm: RecordingGenerator, generator_used: str) -> str | None:
    """Why the template was used although the LLM was called (None = LLM answer used)."""
    if generator_used == "llm":
        return None
    if llm.error is None:
        return "no_verdict"
    if "cut by max_tokens" in llm.error:
        return "cut"
    if "timed out" in llm.error.lower():
        return "timeout"
    return "error"


def format_ok(text: str) -> bool:
    """Starts with the decision line and has at most 4 sentences."""
    starts = re.match(r"\W*decision\s*(non couvert|couvert)", normalize(text)) is not None
    return starts and len([s for s in SENTENCE_END.split(text.strip()) if s]) <= 4


def wrong_language(text: str) -> bool:
    """More English than French stopwords."""
    words = re.findall(r"[a-z]+", normalize(text))
    return sum(w in ENGLISH for w in words) > sum(w in FRENCH for w in words)


def llm_checks(text: str, retrieved: list[str]) -> dict:
    cited = set(generation.cited_clauses(text))
    return {"cites_retrieved": bool(cited & set(retrieved)),
            "invented_citation": bool(cited - set(retrieved)),
            "format_ok": format_ok(text), "wrong_language": wrong_language(text)}


def evaluate(cases: list[dict], retriever=None, generator=None) -> dict:
    """Run the agent on every case. Returns {"metrics": {...}, "rows": [...]}."""
    generate = generator or generation.default_generator()
    llm = RecordingGenerator(generate)
    no_llm = generate is generation.no_generator     # --no-llm: not counted as LLM calls
    rows = []
    for case in cases:
        claim, vision = to_inputs(case)
        llm.reset()
        start = time.perf_counter()
        analysis = agent.analyze(claim, vision, retriever=retriever,
                                 generator=generate if no_llm else llm)
        seconds = time.perf_counter() - start
        expected_clauses = {c for c in case["expected_clauses"].split("|") if c}
        returned = [c.clause_id for c in analysis.result.clauses]
        row = {
            "claim_id": case["claim_id"], "category": case["category"],
            "expected": COVERED[case["expected_covered"]], "covered": analysis.result.covered,
            "correct": analysis.result.covered is COVERED[case["expected_covered"]],
            "step": analysis.step, "cause": analysis.cause,
            "returned_clauses": returned,
            "clause_hit": bool(expected_clauses & set(returned)) if expected_clauses else None,
            "cites_correct": (bool(expected_clauses
                                   & set(generation.cited_clauses(analysis.result.answer)))
                              if expected_clauses else None),
            "generator": analysis.generator,
            "llm_agrees": (analysis.llm_verdict == analysis.rule_covered
                           if analysis.generator == "llm" else None),
            "seconds": round(seconds, 3), "model_version": analysis.result.model_version,
            "answer": analysis.result.answer,
            "llm_called": llm.called, "llm_seconds": llm.seconds, "llm_text": llm.text,
            "llm_error": llm.error,
            "fallback_reason": fallback_reason(llm, analysis.generator) if llm.called else None,
        }
        if llm.text is not None:
            row.update(llm_checks(llm.text, returned))
        rows.append(row)
    return {"metrics": metrics(rows), "rows": rows}


def _share(values: list) -> float | None:
    """Share of True among the values that are not None (None when there is none)."""
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def llm_metrics(rows: list[dict]) -> dict:
    """Metrics on the claims that called the LLM (None when no claim called it)."""
    calls = [r for r in rows if r.get("llm_called")]
    if not calls:
        return {"llm_calls": 0}
    seconds = [r["llm_seconds"] for r in calls]
    texts = [r for r in calls if r["llm_text"] is not None]
    reasons = [r["fallback_reason"] for r in calls]
    result = {
        "llm_calls": len(calls),
        "llm_seconds_mean": round(statistics.mean(seconds), 3),
        "llm_seconds_median": round(statistics.median(seconds), 3),
        "llm_seconds_max": max(seconds),
        "llm_fallback_rate": round(sum(r is not None for r in reasons) / len(calls), 4),
        "llm_contradiction_rate": round(sum(r["step"] == "llm_contradiction" for r in calls)
                                        / len(calls), 4),
    }
    for reason in ("timeout", "cut", "error", "no_verdict"):
        result[f"llm_fallback_{reason}"] = sum(r == reason for r in reasons)
    for check in ("cites_retrieved", "invented_citation", "format_ok", "wrong_language"):
        result[f"llm_{check}"] = _share([r[check] for r in texts])
    return result


def metrics(rows: list[dict]) -> dict:
    seconds = [r["seconds"] for r in rows]
    warm = seconds[1:] or seconds          # the first call loads the embedding model
    result = {
        "n_claims": len(rows),
        "coverage_accuracy": _share([r["correct"] for r in rows]),
        "clause_hit_at_4": _share([r["clause_hit"] for r in rows]),
        "answer_cites_correct": _share([r["cites_correct"] for r in rows]),
        "llm_agrees_with_rule": _share([r["llm_agrees"] for r in rows]),
        "llm_answers": sum(r["generator"] == "llm" for r in rows),
        "template_answers": sum(r["generator"] == "template" for r in rows),
        "latency_first_s": seconds[0],
        "latency_mean_s": round(statistics.mean(warm), 3),
        "latency_max_s": max(warm),
    }
    result |= llm_metrics(rows)
    for category in sorted({r["category"] for r in rows}):
        result[f"accuracy_{category}"] = _share([r["correct"] for r in rows
                                                 if r["category"] == category])
    return result


def log_to_mlflow(report: dict, run_name: str) -> str | None:
    """Log params, metrics and the detailed JSON. Returns the run id, or None if skipped."""
    if not tracking.has_credentials():
        return None
    import mlflow

    with tracking.start_run(EXPERIMENT, run_name=run_name, owner="mohamed", sprint=3,
                            data=DATA) as run:
        mlflow.log_params({
            "agent_version": agent.AGENT_VERSION,
            "embedding_model": CONFIG["embedding_model"],
            "k_guarantee": CONFIG["retrieval"]["k_guarantee"],
            "k_exclusions": CONFIG["retrieval"]["k_exclusions"],
            "llm_model": CONFIG["llm"]["model"],
            "llm_timeout_seconds": CONFIG["llm"]["timeout_seconds"],
            "llm_max_tokens": CONFIG["llm"]["max_tokens"],
            "llm_temperature": CONFIG["llm"]["temperature"],
            "llm_prompt_variant": CONFIG["llm"].get("prompt_variant", "current"),
            "generator": report["generator"],
        })
        mlflow.set_tags({"llm_model": CONFIG["llm"]["model"],
                         "prompt_variant": CONFIG["llm"].get("prompt_variant", "current")})
        mlflow.log_metrics({k: v for k, v in report["metrics"].items() if v is not None})
        mlflow.log_dict(report, "policy_eval.json")
        return run.info.run_id


def warm_up() -> None:
    """Load the LLM once before measuring (its loading time is not an answer time)."""
    try:
        generation.default_generator()("Réponds par OK.")
    except generation.GeneratorUnavailable as error:
        print(f"LLM warm-up failed: {error}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="Ollama model for this run (default: llm.model "
                                        "in agents/policy/config.yaml, file not changed)")
    parser.add_argument("--max-tokens", type=int,
                        help="max tokens of the LLM answer for this run (default: config)")
    parser.add_argument("--prompt-variant", choices=generation.PROMPT_VARIANTS,
                        help="llm.prompt_variant for this run (default: config)")
    parser.add_argument("--no-llm", action="store_true", help="template answers only")
    parser.add_argument("--no-mlflow", action="store_true", help="do not log to MLflow")
    args = parser.parse_args(argv)
    # in memory, for this process only: the Ollama request, model_version and the
    # MLflow params / tags all read CONFIG["llm"]
    if args.model:
        CONFIG["llm"]["model"] = args.model
    if args.max_tokens:
        CONFIG["llm"]["max_tokens"] = args.max_tokens
    if args.prompt_variant:
        CONFIG["llm"]["prompt_variant"] = args.prompt_variant

    cases = load_cases()
    if not args.no_llm:
        warm_up()
    report = evaluate(cases, generator=generation.no_generator if args.no_llm else None)
    used_llm = report["metrics"]["llm_answers"] > 0
    report["generator"] = CONFIG["llm"]["model"] if used_llm else "template"
    report["llm_settings"] = {k: CONFIG["llm"].get(k) for k in
                              ("model", "max_tokens", "timeout_seconds", "temperature",
                               "prompt_variant")}
    report["tags"] = tracking.required_tags("mohamed", 3, DATA)
    report["index"] = str(data_path("chroma_dir"))

    for row in report["rows"]:
        mark = "ok  " if row["correct"] else "FAIL"
        print(f"{mark} {row['claim_id']} {row['category']:28} expected={row['expected']!s:5} "
              f"got={row['covered']!s:5} step={row['step']:25} hit={row['clause_hit']} "
              f"llm={row['llm_seconds']} fallback={row['fallback_reason']}")
    print(json.dumps(report["metrics"], indent=2))

    run_id = None
    if not args.no_mlflow:
        try:
            variant = CONFIG["llm"].get("prompt_variant", "current")
            run_name = f"eval-{report['generator']}" + ("" if variant == "current"
                                                         else f"-{variant}")
            run_id = log_to_mlflow(report, run_name=run_name)
        except Exception as error:  # noqa: BLE001 - network, credentials: keep the local file
            print(f"MLflow logging failed ({type(error).__name__}: {error}).")
    report["mlflow_run_id"] = run_id
    RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MLflow run: {run_id or 'not logged'} | details saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
