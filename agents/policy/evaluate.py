"""Evaluate the policy agent on the labelled claims of data/policy/eval_claims.csv.

Usage:  python -m agents.policy.evaluate            (real index + Ollama if it answers)
        python -m agents.policy.evaluate --no-llm   (template answers only)

Each CSV row is one claim: the text, the contract, the damages vision would have
seen ("part:type|part:type") and what a claims handler expects:
`expected_covered` (true / false / none) and `expected_clauses` (any of these
clause ids is a correct piece of evidence).

Metrics
- coverage_accuracy      share of claims where covered == expected (target >= 0.85)
- clause_hit_at_4        share of claims with a correct clause among the <= 4 returned
                         (target >= 0.80; claims without expected clause are skipped)
- answer_cites_correct   share of answers citing a correct clause id, e.g. "[AXA-015]"
- llm_agrees_with_rule   among the answers written by the LLM, share agreeing with the rule
- latency_*              seconds per claim (the first call loads the embedding model)

Results go to MLflow (experiment claimspilot-policy) when credentials exist, and
always to data/policy/eval_results.json.
"""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from agents.policy import agent, generation
from agents.policy.settings import CONFIG, REPO_ROOT, data_path
from claimspilot.schemas import ClaimInput, Damage, VisionResult
from mlops import tracking

EVAL_FILE = REPO_ROOT / "data/policy/eval_claims.csv"
RESULTS_FILE = REPO_ROOT / "data/policy/eval_results.json"
EXPERIMENT = "claimspilot-policy"
COVERED = {"true": True, "false": False, "none": None}
DATA = ["data/policy/raw", "data/policy/processed", "data/policy/eval_claims.csv"]


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


def evaluate(cases: list[dict], retriever=agent.retrieve, generator=None) -> dict:
    """Run the agent on every case. Returns {"metrics": {...}, "rows": [...]}."""
    rows = []
    for case in cases:
        claim, vision = to_inputs(case)
        start = time.perf_counter()
        analysis = agent.analyze(claim, vision, retriever=retriever, generator=generator)
        seconds = time.perf_counter() - start
        expected_clauses = {c for c in case["expected_clauses"].split("|") if c}
        returned = [c.clause_id for c in analysis.result.clauses]
        rows.append({
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
        })
    return {"metrics": metrics(rows), "rows": rows}


def _share(values: list) -> float | None:
    """Share of True among the values that are not None (None when there is none)."""
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


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
            "generator": report["generator"],
        })
        mlflow.log_metrics({k: v for k, v in report["metrics"].items() if v is not None})
        mlflow.log_dict(report, "policy_eval.json")
        return run.info.run_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-llm", action="store_true", help="template answers only")
    parser.add_argument("--no-mlflow", action="store_true", help="do not log to MLflow")
    args = parser.parse_args()

    cases = load_cases()
    report = evaluate(cases, generator=generation.no_generator if args.no_llm else None)
    used_llm = report["metrics"]["llm_answers"] > 0
    report["generator"] = CONFIG["llm"]["model"] if used_llm else "template"
    report["tags"] = tracking.required_tags("mohamed", 3, DATA)
    report["index"] = str(data_path("chroma_dir"))

    for row in report["rows"]:
        mark = "ok  " if row["correct"] else "FAIL"
        print(f"{mark} {row['claim_id']} {row['category']:28} expected={row['expected']!s:5} "
              f"got={row['covered']!s:5} step={row['step']:25} hit={row['clause_hit']}")
    print(json.dumps(report["metrics"], indent=2))

    run_id = None
    if not args.no_mlflow:
        try:
            run_id = log_to_mlflow(report, run_name=f"eval-{report['generator']}")
        except Exception as error:  # noqa: BLE001 - network, credentials: keep the local file
            print(f"MLflow logging failed ({type(error).__name__}: {error}).")
    report["mlflow_run_id"] = run_id
    RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MLflow run: {run_id or 'not logged'} | details saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
