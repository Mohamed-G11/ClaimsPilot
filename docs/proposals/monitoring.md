# Monitoring proposal (Evidently)

Status: proposal for the team. No code and no choice here: options with pros and cons. Written 2026-11-20 from the code on `feat/e2e-evaluation`.

## What exists today

| Tool | What it holds | Granularity | Missing for monitoring |
|---|---|---|---|
| **Langfuse** (cloud, `api/tracing.py`) | one trace per claim: the input claim, each agent's output, the policy prompt and answer, token usage, latency, final decision + status | per request, live | no statistics over time on our own features (vision confidence, text length…), no drift test, no alert; the data stays in Langfuse's cloud |
| **MLflow** (DagsHub) | offline evaluation runs: vision mAP, NLP F1, policy coverage accuracy, LLM comparisons, the e2e evaluation (`claimspilot-decision`) | per evaluation run | nothing about live traffic |
| **API logs** | warnings only (agent fallback, warm-up) | per event | not structured, not stored |

Gap: **no stored, structured record of every claim the API decided**. Evidently needs that table. A *reference* table (e.g. the e2e demo set or the first week) is compared with a *current* window.

## What Evidently could monitor

| Signal | Source field | Why it matters | Type of check |
|---|---|---|---|
| Decision rate (approve / reject / human_review) | `Decision.decision` | a jump in `human_review` = an agent degrading or new kinds of claims | categorical drift (share per class) |
| `human_review` rate and its reasons | `Decision.reasons` (`HUMAN REVIEW: …` lines) | which rule sends claims to humans (low vision confidence, uncertain text, coverage unknown, stub used…) | counts per reason over time |
| Decision status | `agents["decision"]` (`langgraph`, `rules (fallback: …)`, `safety: …`) | a fallback becoming frequent = LangGraph or config broken | share of each status |
| Agent fallbacks | `agents["vision" / "nlp" / "policy"]` = `stub (…)` | missing weights / index / Ollama in production | share of stubs (should be 0) |
| Vision confidence | mean / min `Damage.confidence`, number of damages, `severity` | photos unlike the training set (night, other cars) → lower confidence | numeric drift (e.g. Wasserstein / K-S) |
| Damaged parts | `Damage.part` | new part distribution (e.g. many windshield claims, no class for it) | categorical drift |
| Text language and length | `ClaimInput.language`, text length in words, share of text with no part found | new user population, very short texts → more `uncertain` | categorical + numeric drift |
| NLP result | `NLPResult.consistency`, `score` | rise of `uncertain` | categorical + numeric drift |
| Policy result | `PolicyResult.covered` (True / False / None), step (exclusion, incompatible…), `model_version` (`+template` = LLM fallback) | LLM down (template rate up), contract mix changing | categorical drift |
| Policy LLM | answer latency, tokens, contradiction rate | slower model, prompt regression | numeric (already in Langfuse per call) |
| Latency per claim | seconds | CPU saturation, cold starts | numeric |
| Ground truth (later) | final decision of the claims handler for `human_review` claims | real accuracy | needs a feedback field: nothing collects it today |

Evidently compares distributions. It does not know if a decision was right: accuracy needs the human decision (last row), which is not stored anywhere today.

## Which data must be stored

One row per decided claim, without the photos themselves. A minimal record built from `ClaimAnalysis`:

`timestamp, claim_id, trace_id, policy_id (insurer, formula), language, text_length, n_photos, n_damages, mean_vision_confidence, min_vision_confidence, severity, parts, nlp_consistency, nlp_score, policy_covered, policy_step, policy_generator (llm / template), decision, confidence, decision_status, agent_statuses, seconds, (later) human_decision`

Privacy: claim texts and photos are personal data. Storing lengths and labels instead of raw text is enough for drift checks.

Where, three options:

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Prediction log written by the API | `api/` appends one JSON line per claim (a volume `data/monitoring/`) or a SQLite table | simple, offline, our own data, works without Langfuse | new code in the request path (must never fail the claim), file to rotate and back up |
| B. Export from Langfuse | a script reads traces with `api.observations.get_many` and builds the table | no change to the API; Langfuse already has everything | depends on the cloud and its API limits; v5 removed `api.trace.get`, so parsing observations is more work; trace data is not shaped as features |
| C. MLflow only | log per-batch statistics as MLflow metrics | reuses DagsHub, nothing new to host | not per claim; no real drift test; MLflow is made for runs, not traffic |

## How it fits with Langfuse and MLflow

- **Langfuse** stays the place to debug **one** claim (why this decision?). The `trace_id` in each stored row links a drift alert back to example traces.
- **Evidently** answers "has the traffic changed?" over many claims, from the stored table.
- **MLflow** keeps the evaluation history. Each Evidently report (HTML + metrics) could be logged as an MLflow run in a new experiment (e.g. `claimspilot-monitoring`), so reports are versioned like evaluations.
- **Trigger:** a script run by hand or by a scheduled GitHub Action (no Airflow, per the project scope).
- **Grafana:** only if time remains (scope). The Evidently HTML report is enough for the demo.

## Effort (rough, in hours)

| Piece | Hours |
|---|---|
| Prediction log in the API (option A) + tests | 4–6 |
| Langfuse export script instead (option B) + tests | 6–10 |
| Evidently report script (reference vs current, the checks above) | 4–6 |
| Reference dataset: run the e2e demo set (task 6) through the API to fill the log | 1–2 (once the demo claims are written) |
| Log the report to MLflow + README | 2 |
| Scheduled GitHub Action | 2–3 |
| Human feedback field for ground truth (API + UI) | 6–10 (touches Wiem's `ui/`) |
| **Total, without the feedback field** | **about 13–19 h (A) or 15–23 h (B)** |

## Pros and cons of doing it

| Pros | Cons |
|---|---|
| Covers the "monitored" part of the project goal (MLOps deliverable) | Little real traffic: drift on a demo is shown with an artificial "current" window (e.g. claims in English or night photos) |
| Cheap signals with high value: fallback rate, `human_review` rate, LLM template rate | Another library and Docker volume to maintain (Evidently pins its own versions) |
| Reuses MLflow and Langfuse, no new server | Without the human decision, it monitors inputs and outputs, not accuracy |
| Prediction log also feeds the future retraining script | Storing claim data needs a privacy decision |

## Questions for the team

1. Store a prediction log in the API (A), or export from Langfuse (B)?
2. May we store claim texts, or only derived features (length, language, parts)?
3. Should the UI collect the claims handler's final decision for `human_review` claims (ground truth)? (`ui/` is Wiem's.)
4. Who owns monitoring: Mohamed (platform) or shared?
