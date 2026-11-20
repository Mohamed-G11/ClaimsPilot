"""End-to-end evaluation script with a FAKE API (httpx.MockTransport): no server, no model."""
import json

import httpx
import pytest

from mlops import evaluate_e2e

HEADER = "claim_id,photo_paths,text,policy_id,language,expected_decision,written_by\n"


def write_csv(tmp_path, rows: str):
    path = tmp_path / "claims.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def fake_api(decisions: dict, fail: set = frozenset(), not_ready: int = 0):
    """/health ok; /ready 503 `not_ready` times then 200; /claims/analyze answers
    decisions[claim_id] (500 for ids in `fail`)."""
    sent = []
    ready_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/ready":
            ready_calls.append(1)
            if len(ready_calls) <= not_ready:
                return httpx.Response(503, json={"ready": False, "warmup": {"llm": "running"}})
            return httpx.Response(200, json={"ready": True, "warmup": {}, "failed": []})
        claim = json.loads(request.content)
        sent.append(claim)
        if claim["claim_id"] in fail:
            return httpx.Response(500, json={"detail": "boom"})
        decision = decisions[claim["claim_id"]]
        return httpx.Response(200, json={
            "decision": {"claim_id": claim["claim_id"], "decision": decision, "confidence": 0.8,
                         "reasons": [], "trace_id": "t" * 32},
            "agents": {"vision": "real", "nlp": "real", "policy": "real",
                       "decision": "langgraph"},
        })

    return httpx.MockTransport(handler), sent


ROWS = ("D1,a.jpg|b.jpg,Collision,AXA-TR,fr,approve,Wiem\n"
        "D2,c.jpg,Vol,AXA-TIERS,fr,reject,Hend\n"
        "D3,d.jpg,Pare-brise,SANLAM-TR,fr,,Mohamed\n")


def test_scores_only_claims_with_an_expected_decision(tmp_path):
    transport, sent = fake_api({"D1": "approve", "D2": "human_review", "D3": "approve"})
    out = tmp_path / "results.json"
    report = evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--output", str(out),
                                "--no-mlflow"], transport=transport)
    m = report["metrics"]
    assert (m["n_claims"], m["n_scored"], m["accuracy"]) == (3, 2, 0.5)
    assert m["accuracy_expected_approve"] == 1.0 and m["accuracy_expected_reject"] == 0.0
    assert m["human_review_rate"] == round(1 / 3, 4)
    rows = {r["claim_id"]: r for r in report["rows"]}
    assert rows["D3"]["match"] is None                       # run, not scored
    assert rows["D1"]["decision_status"] == "langgraph" and rows["D1"]["trace_id"] == "t" * 32
    assert sent[0]["photo_paths"] == ["a.jpg", "b.jpg"]      # "|" separates photos
    assert json.loads(out.read_text(encoding="utf-8"))["metrics"]["n_scored"] == 2


def test_an_api_error_is_recorded_and_counts_as_wrong(tmp_path):
    transport, _ = fake_api({"D2": "reject", "D3": "approve"}, fail={"D1"})
    report = evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--output",
                                str(tmp_path / "r.json"), "--no-mlflow"], transport=transport)
    d1 = report["rows"][0]
    assert d1["decision"] is None and d1["match"] is False and "HTTPStatusError" in d1["error"]
    assert report["metrics"]["n_errors"] == 1


@pytest.mark.parametrize(("rows", "message"), [
    ("D1,a.jpg,t,AXA-TR,fr,maybe,W\n", "expected_decision must be one of"),
    ("D1,a.jpg,t,AXA-TR,fr,,W\nD1,b.jpg,t,AXA-TR,fr,,W\n", "duplicate claim_id"),
    ("D1,,t,AXA-TR,fr,,W\n", "photo_paths, text and policy_id are required"),
    ("EXAMPLE-1,a.jpg,t,AXA-TR,fr,approve,EXAMPLE\n", "delete the EXAMPLE rows"),
])
def test_bad_rows_are_refused_with_their_row_number(tmp_path, rows, message):
    with pytest.raises(ValueError, match=message):
        evaluate_e2e.load_claims(write_csv(tmp_path, rows))


def test_missing_column_is_refused(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("claim_id,text\nD1,t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        evaluate_e2e.load_claims(path)


def test_api_down_stops_with_a_clear_message(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(SystemExit, match="not reachable"):
        evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--no-mlflow"],
                          transport=httpx.MockTransport(down))


def test_waits_for_ready_before_the_first_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate_e2e.time, "sleep", lambda seconds: None)
    transport, sent = fake_api({"D1": "approve", "D2": "reject", "D3": "approve"}, not_ready=2)
    report = evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--output",
                                str(tmp_path / "r.json"), "--no-mlflow"], transport=transport)
    assert report["metrics"]["n_claims"] == 3 and len(sent) == 3


def test_not_ready_in_time_stops_without_sending_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate_e2e.time, "sleep", lambda seconds: None)
    transport, sent = fake_api({}, not_ready=10**6)
    with pytest.raises(SystemExit, match="not ready after 0 s"):
        evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--ready-timeout", "0",
                           "--no-mlflow"], transport=transport)
    assert sent == []


def test_api_without_ready_endpoint_falls_back_to_health(tmp_path):
    def handler(request):
        if request.url.path == "/ready":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        claim = json.loads(request.content)
        return httpx.Response(200, json={
            "decision": {"claim_id": claim["claim_id"], "decision": "approve", "confidence": 0.9,
                         "reasons": [], "trace_id": None},
            "agents": {"decision": "langgraph"}})

    report = evaluate_e2e.main(["--claims", str(write_csv(tmp_path, ROWS)), "--output",
                                str(tmp_path / "r.json"), "--no-mlflow"],
                               transport=httpx.MockTransport(handler))
    assert report["metrics"]["n_claims"] == 3
