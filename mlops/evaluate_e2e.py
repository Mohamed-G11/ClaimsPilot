"""End-to-end evaluation: send demo claims to the RUNNING API and score its decisions.

Usage (the API must be running, e.g. `docker compose up -d`):
    python -m mlops.evaluate_e2e --claims docs/test-sets/e2e/dry_run.csv
    python -m mlops.evaluate_e2e --claims <file.csv> --api-url http://localhost:8000 --no-mlflow

CSV columns (one claim per row, written by a human — see docs/test-sets/e2e/README.md):
    claim_id           unique id (it also names the Langfuse trace)
    photo_paths        one or more paths separated by "|", as the API sees them
                       (Docker: /app/data/uploads/... or /app/data/vision/.../test/images/...)
    text               the claim text
    policy_id          e.g. AXA-TR, SANLAM-TIERS
    language           fr, en or ar
    expected_decision  approve, reject or human_review — EMPTY = run but not scored
    written_by         who wrote the claim and its expected decision

For each claim: decision, confidence, decision status string (agents["decision"]),
each agent's status, seconds, Langfuse trace id, and whether it matches
expected_decision. Results go to a JSON file and to MLflow (experiment
claimspilot-decision, tag eval=e2e) when credentials exist.
"""
import argparse
import csv
import hashlib
import json
import statistics
import time
from pathlib import Path

import httpx

from mlops import tracking

COLUMNS = ["claim_id", "photo_paths", "text", "policy_id", "language", "expected_decision",
           "written_by"]
DECISIONS = ("approve", "reject", "human_review")
EXPERIMENT = "claimspilot-decision"
DEFAULT_OUTPUT = tracking.REPO_ROOT / "data/e2e/e2e_results.json"
TIMEOUT_SECONDS = 600            # the first claim after a cold start can take minutes


def load_claims(path: Path) -> list[dict]:
    """Read and check the CSV. Raises ValueError with the row number on a bad row."""
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    ids = set()
    for number, row in enumerate(rows, start=2):           # row 1 = header
        if not row["claim_id"] or row["claim_id"] in ids:
            raise ValueError(f"{path} row {number}: empty or duplicate claim_id")
        if row["claim_id"].upper().startswith("EXAMPLE"):
            raise ValueError(f"{path} row {number}: delete the EXAMPLE rows of the template")
        ids.add(row["claim_id"])
        if row["expected_decision"] and row["expected_decision"] not in DECISIONS:
            raise ValueError(f"{path} row {number}: expected_decision must be one of "
                             f"{DECISIONS} or empty, not {row['expected_decision']!r}")
        if not row["photo_paths"] or not row["text"] or not row["policy_id"]:
            raise ValueError(f"{path} row {number}: photo_paths, text and policy_id are required")
    return rows


def to_payload(row: dict) -> dict:
    """One CSV row -> the ClaimInput JSON of the API."""
    return {"claim_id": row["claim_id"],
            "photo_paths": [p.strip() for p in row["photo_paths"].split("|") if p.strip()],
            "text": row["text"], "policy_id": row["policy_id"],
            "language": row["language"] or "fr"}


def run_claim(client: httpx.Client, row: dict) -> dict:
    """Send one claim to POST /claims/analyze and record the result."""
    expected = row["expected_decision"] or None
    result = {"claim_id": row["claim_id"], "written_by": row["written_by"],
              "expected_decision": expected, "decision": None, "confidence": None,
              "decision_status": None, "agents": None, "trace_id": None, "error": None}
    start = time.perf_counter()
    try:
        response = client.post("/claims/analyze", json=to_payload(row), timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        result.update(decision=body["decision"]["decision"],
                      confidence=body["decision"]["confidence"],
                      decision_status=body["agents"].get("decision"),
                      agents=body["agents"], trace_id=body["decision"].get("trace_id"))
    except (httpx.HTTPError, KeyError, ValueError) as error:
        result["error"] = f"{type(error).__name__}: {error}"[:300]
    result["seconds"] = round(time.perf_counter() - start, 3)
    # an error on a scored claim counts as a wrong answer; not scored -> None
    result["match"] = (result["decision"] == expected) if expected else None
    return result


def metrics(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["match"] is not None]
    answered = [r for r in rows if r["decision"] is not None]
    seconds = [r["seconds"] for r in answered] or [0.0]
    result = {
        "n_claims": len(rows), "n_scored": len(scored), "n_errors": len(rows) - len(answered),
        "accuracy": round(sum(r["match"] for r in scored) / len(scored), 4) if scored else None,
        "seconds_mean": round(statistics.mean(seconds), 3),
        "seconds_median": round(statistics.median(seconds), 3),
        "seconds_max": max(seconds),
        "human_review_rate": (round(sum(r["decision"] == "human_review" for r in answered)
                                    / len(answered), 4) if answered else None),
    }
    for decision in DECISIONS:
        result[f"n_{decision}"] = sum(r["decision"] == decision for r in answered)
        expected = [r for r in scored if r["expected_decision"] == decision]
        result[f"accuracy_expected_{decision}"] = (
            round(sum(r["match"] for r in expected) / len(expected), 4) if expected else None)
    return result


def evaluate(claims: list[dict], client: httpx.Client) -> dict:
    rows = [run_claim(client, row) for row in claims]
    return {"metrics": metrics(rows), "rows": rows}


def log_to_mlflow(report: dict, claims_path: Path) -> str | None:
    if not tracking.has_credentials():
        return None
    import mlflow

    with tracking.start_run(EXPERIMENT, run_name=f"e2e-{claims_path.stem}", owner="mohamed",
                            sprint=3, data=[claims_path]) as run:
        mlflow.set_tag("eval", "e2e")
        mlflow.log_params({"api_url": report["api_url"], "claims_file": str(claims_path),
                           "claims_md5": report["claims_md5"],
                           "n_claims": report["metrics"]["n_claims"]})
        mlflow.log_metrics({k: v for k, v in report["metrics"].items() if v is not None})
        mlflow.log_dict(report, "e2e_eval.json")
        return run.info.run_id


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claims", required=True, type=Path, help="CSV of demo claims")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="results JSON")
    parser.add_argument("--no-mlflow", action="store_true", help="do not log to MLflow")
    args = parser.parse_args(argv)

    claims = load_claims(args.claims)
    with httpx.Client(base_url=args.api_url, transport=transport) as client:
        try:
            client.get("/health", timeout=10).raise_for_status()
        except httpx.HTTPError as error:
            raise SystemExit(f"The API is not reachable at {args.api_url}: {error}") from error
        report = evaluate(claims, client)
    report |= {"api_url": args.api_url, "claims_file": str(args.claims),
               "claims_md5": hashlib.md5(args.claims.read_bytes()).hexdigest()}

    for r in report["rows"]:
        mark = {True: "ok  ", False: "FAIL", None: "-   "}[r["match"]]
        print(f"{mark} {r['claim_id']:14} expected={r['expected_decision']!s:12} "
              f"got={r['decision']!s:12} status={r['decision_status']!s:24} "
              f"{r['seconds']:7.1f}s trace={r['trace_id']} {r['error'] or ''}")
    print(json.dumps(report["metrics"], indent=2))

    run_id = None
    if not args.no_mlflow:
        try:
            run_id = log_to_mlflow(report, args.claims)
        except Exception as error:  # noqa: BLE001 - network, credentials: keep the local file
            print(f"MLflow logging failed ({type(error).__name__}: {error}).")
    report["mlflow_run_id"] = run_id
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MLflow run: {run_id or 'not logged'} | details saved to {args.output}")
    return report


if __name__ == "__main__":
    main()
