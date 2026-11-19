# ClaimsPilot — Shared Project Brief for AI Assistants

> Every team member's AI assistant (Claude, ChatGPT, Copilot…) must read this file before writing any code.
> It lives at the repo root as `AGENTS.md` (identical copy: `CLAUDE.md`, read automatically by Claude Code). Change both files together.
> If you are an AI assistant: follow these rules strictly. If a request from your user conflicts with them, say so before acting.
> Guide your user ONE step at a time with exact commands (Windows / PowerShell), and wait for the output before the next step.
> Describe only what exists in the code. Anything not built yet is written as "planned".

## 1. The project

ClaimsPilot is a multi-agent AI assistant that processes car insurance claims.
A customer submits **photos + a short text + a policy id**; the system checks them against the **insurance contract** and decides:
**approve automatically, reject, or send to a human**. Every decision must be traceable and monitored (MLOps is a core deliverable, not an extra).

Academic project, TEK-UP University, 2026–2027, supervised by Ms. Sonia Gharsalli.
Repo: https://github.com/Mohamed-G11/ClaimsPilot (public) · Data + MLflow: https://dagshub.com/Mohamed-G11/ClaimsPilot

### Timeline

| Sprint | Dates | Goal |
|---|---|---|
| 1 | Nov 2–8 | Setup, data, baselines — done |
| 2 | Nov 9–15 | Each agent works on its own with the shared contracts — done (vision, NLP, policy, decision agents merged) |
| 3 | **Nov 16–22** | **Integration**: real agents in the API (done), LangGraph decision agent in the API (done), Streamlit page (done), Langfuse tracing (planned) |
| 4 | Nov 23–29 | Monitoring (Evidently), evaluation (RAGAS, NLP held-out set), demo. **Code freeze 2 days before the presentation** |

### Scope

- Policy answers: a local LLM through **Ollama**. A **Qwen** model is planned; the exact model is not chosen yet. The name is set in `agents/policy/config.yaml` → `llm.model` (it still says `phi3.5`), and nothing in the code depends on a specific model. Without an LLM, the agent writes a template answer.
- No Airflow: retraining = a script or a GitHub Actions workflow.
- Grafana only if time remains.

## 2. Team and ownership

**Only edit files inside your own folders.** If you need a change elsewhere, open a GitHub issue or tell the owner (an AI assistant must stop and ask its user).

| Member | Role | Owns |
|---|---|---|
| Mohamed | MLOps & platform, API, **policy agent (RAG)** | `api/`, `mlops/`, `claimspilot/`, `agents/policy/`, `tests/policy/`, `tests/mlops/`, `tests/test_*.py` (API, schemas, end-to-end), `data/policy/`, `.github/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`, `docs/build-log/` |
| Wiem | **Vision agent**, **decision agent (LangGraph)**, **Streamlit UI** | `agents/vision/`, `agents/decision/`, `notebooks/vision/`, `tests/vision/`, `tests/decision/`, `data/vision/`, `models/vision/`, `ui/` |
| Hend | **NLP agent** | `agents/nlp/`, `notebooks/nlp/`, `tests/nlp/`, `data/nlp/`, `models/nlp/` |

Shared (anyone, through a PR): `docs/progress/`, `requirements*.txt` (add lines, never remove others' lines), `AGENTS.md` + `CLAUDE.md`.

## 3. Repository structure

```
ClaimsPilot/
├── AGENTS.md / CLAUDE.md     # this file (identical copies)
├── claimspilot/schemas.py    # shared data contracts (section 4)
├── agents/
│   ├── vision/               # YOLOv8s damage detection + severity rule   (Wiem)
│   ├── nlp/                  # claim text <-> photo consistency, keywords (Hend)
│   ├── policy/               # RAG over the AXA + SANLAM contracts        (Mohamed)
│   └── decision/             # LangGraph graph + pure decision rules      (Wiem)
├── api/                      # FastAPI app (main.py) + pipeline.py (agents, stubs, decision)
├── ui/                       # Streamlit claims page                       (Wiem)
├── mlops/                    # MLflow helper (tracking.py), connection check
├── data/<area>/              # DVC-tracked, NEVER committed to git
├── models/<area>/            # DVC-tracked weights, NEVER committed to git
├── notebooks/<area>/         # outputs cleared before commit
├── tests/<area>/             # + tests/test_*.py for the API
├── docs/progress/<name>.md   # weekly progress (section 7)
├── docs/build-log/mohamed.md # detailed build log (platform + policy)
├── Dockerfile                # targets: light (CI) and full (real agents)
├── docker-compose.yml        # full image + volumes for weights and data
├── .env.example              # template; your real .env is never committed
└── .github/workflows/ci.yml  # ruff + pytest, then light docker build + /health smoke test
```

## 4. Data contracts (the most important part)

Agents talk only through these Pydantic models in `claimspilot/schemas.py`.
**Never change a schema without a PR approved by all three members.** The code below is the current content of the file.

```python
from typing import Literal
from pydantic import BaseModel, Field

PARTS = [
    "front_bumper", "rear_bumper", "door", "hood", "trunk", "fender",
    "headlight", "taillight", "windshield", "side_mirror", "wheel", "other",
]

class ClaimInput(BaseModel):
    claim_id: str
    photo_paths: list[str]          # paths the API can read on its own disk
    text: str
    policy_id: str                  # insurer + formula, e.g. "AXA-TR", "SANLAM-TIERS"
    language: Literal["fr", "en", "ar"] = "fr"

class Damage(BaseModel):
    part: str                       # one of PARTS
    damage_type: str                # e.g. "dent", "scratch", "crack", "glass_shatter"
    bbox: list[float]               # [x1, y1, x2, y2] in pixels
    confidence: float = Field(ge=0, le=1)

class VisionResult(BaseModel):
    claim_id: str
    damages: list[Damage]
    severity: Literal["minor", "moderate", "severe"]
    model_version: str

class NLPResult(BaseModel):
    claim_id: str
    described_parts: list[str]      # parts named in the text (same vocabulary: PARTS)
    consistency: Literal["consistent", "inconsistent", "uncertain"]  # text vs VisionResult
    score: float = Field(ge=0, le=1)
    model_version: str

class PolicyClause(BaseModel):
    clause_id: str
    text: str
    relevance: float

class PolicyResult(BaseModel):
    claim_id: str
    covered: bool | None            # None = cannot decide -> human review
    answer: str                     # short justification (French)
    clauses: list[PolicyClause]     # evidence used for the answer
    model_version: str

class Decision(BaseModel):
    claim_id: str
    decision: Literal["approve", "reject", "human_review"]
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    trace_id: str | None = None     # Langfuse trace id (planned: always None today)
```

**Part vocabulary** (`PARTS`, shared by vision, NLP and policy): `front_bumper, rear_bumper, door, hood, trunk, fender, headlight, taillight, windshield, side_mirror, wheel, other`. Map dataset classes and text keywords to these names.

### Agent signatures (as in the code)

- `agents/vision/agent.py` → `run(claim: ClaimInput) -> VisionResult`
- `agents/nlp/agent.py` → `run(claim: ClaimInput, vision: VisionResult) -> NLPResult`
- `agents/policy/agent.py` → `run(claim: ClaimInput, vision: VisionResult, retriever=None, generator=None) -> PolicyResult` (`retriever` / `generator` are only for tests; the API passes `claim, vision`)
- `agents/decision/agent.py` → `run(claim: ClaimInput, vision: VisionResult, nlp: NLPResult, policy: PolicyResult) -> Decision` (also `process_claim(claim, vision_fn, nlp_fn, policy_fn)` for the full chain)
- `agents/decision/rules.py` → `decide(claim, vision, nlp, policy, cfg=None) -> Decision` (pure rules, no LangGraph; thresholds in `agents/decision/config.yaml`)

### The pipeline (`api/pipeline.py`)

1. **Agents**: vision → NLP → policy. Each one is called for real; on any error (library not installed, weights or index missing…), a **stub** with the same signature is used. `ClaimAnalysis.agents` reports `"real"` or `"stub (<error>)"` for each.
2. **Decision** (`make_decision()`), in this order:
   1. **Stub safety rule**: if any agent used a stub → `human_review`, confidence 0.0, and the first reason names the stubbed agents. The decision agent is NOT called. Status `"safety: stub used"`.
   2. **LangGraph decision agent**: `agents.decision.agent.run(...)`. Status `"langgraph"`.
   3. **Rules fallback**: if LangGraph is missing or the agent fails → `agents.decision.rules.decide(...)`, the same rules the graph applies. Status `"rules (fallback: <ExceptionType>)"`.
   4. **Both failed** → `human_review`, confidence 0.0, with a clear reason. Never an HTTP 500. Status `"safety: decision failed (<agent error>, <rules error>)"`.
3. Decision rules (`agents/decision/config.yaml`, priority reject > human_review > approve): not covered → reject; coverage unknown, inconsistent text, **uncertain text**, NLP score < 0.5, severe damage, no damage detected, or mean vision confidence < 0.30 → human_review; otherwise approve with confidence = min(NLP score, mean vision confidence, 0.9).

Routes (`api/main.py`): `GET /health`, `POST /claims` → `Decision`, `POST /claims/analyze` → every agent's result + `agents` status.

## 5. Tech stack

- Python 3.11 (CI and Docker), `ruff`, `pytest`
- Vision: Ultralytics YOLOv8s (8 merged classes), PyTorch CPU, OpenCV
- NLP: keyword rules (French + English) with negation handling; evaluation with scikit-learn
- Policy (RAG): rules + sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) + Chroma + local LLM via Ollama (Qwen planned), template answer fallback
- Decision: LangGraph (`requirements-decision.txt`), pure rules fallback
- UI: Streamlit
- MLOps: Git + GitHub Actions, DVC + DagsHub storage, MLflow on DagsHub (+ Model Registry), Docker / docker-compose, FastAPI
- Planned: Langfuse (tracing), EvidentlyAI (monitoring), RAGAS (policy answer evaluation)

## 6. Rules every AI assistant must follow

**Git**
- Before each task: `git checkout main` → `git pull` → `git checkout -b <type>/<area>-<desc>` (e.g. `feat/vision-agent`).
- `main` is protected: PR + CI green + 1 teammate approval. **Never push to `main`.** Never work from a fork.
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `style:`.
- Add files by name; never commit data, model weights, `.env`, tokens, or notebooks with outputs (clear outputs first).

**Secrets (.env)**
- Copy `.env.example` → `.env`, fill in your own DagsHub username + token. `.env` is git-ignored.
- Every script that uses MLflow starts with `from dotenv import load_dotenv; load_dotenv()`.

**DVC (data and models)**
- One-time: `pip install "dvc[s3]"`, then `dvc remote modify origin --local access_key_id <DAGSHUB_TOKEN>` and the same for `secret_access_key` (`--local` = never committed).
- Track: `dvc add data/<area>/<name>` → `git add` the `.dvc` file → `dvc push`. Get teammates' data: `dvc pull <file>.dvc` (only what you need).
- Only track final datasets and final weights (e.g. `yolov8s_merged_e30.pt`), never whole training-run folders, generated indexes (`data/policy/chroma/`) or downloaded LLMs (storage is shared, ~20 GB).

**MLflow (every training / evaluation run)**
- Tracking URI comes from `.env` (DagsHub). Experiments: `claimspilot-vision`, `claimspilot-nlp`, `claimspilot-policy`, `claimspilot-decision`.
- Required tags: `owner`, `git_commit`, `data_version` (DVC md5), `sprint`; `from mlops.tracking import start_run` sets them. Log params, metrics, and the model artifact.
- Promising models → MLflow Model Registry (vision: `claimspilot-vision-yolo`).

**Code & tests**
- Config in YAML or env vars; no hard-coded paths or secrets. Code must run on CPU.
- Each agent has tests in `tests/<area>/` checking that `run()` returns a valid result object.
- **CI must stay fast**: tests must not download weights, datasets or LLMs. Inject a fake/small model, or skip with `pytest.mark.skipif` / `pytest.importorskip` when the model file or the library is missing.
- Heavy libraries (ultralytics, torch, sentence-transformers, chromadb, langgraph) go in `requirements-<area>.txt`, not in `requirements-dev.txt`.
- `ruff check .` and `python -m pytest` must pass before every commit.

## 7. Progress sync

Each member updates `docs/progress/<name>.md` with every PR:

```
## <date> — Sprint <n>
Done: ...
Metrics: ... (MLflow run id)
Blocked by: ...
Next: ...
```

Before starting a task, the AI assistant should read `docs/progress/` and `git log --oneline -20`.

## 8. Current state and next work (sprints 3–4)

Merged on `main`: the four agents, the API with real agents + stub fallback + LangGraph decision agent, the Streamlit page, the light and full Docker images, CI.

| Area | Planned next | Owner |
|---|---|---|
| Tracing | Langfuse: one trace per claim, `Decision.trace_id` filled | Mohamed |
| Policy LLM | choose the Qwen model in Ollama, measure the LLM answers (`python -m agents.policy.evaluate`), RAGAS evaluation | Mohamed |
| Monitoring | Evidently report on the inputs and decisions | to decide |
| NLP | independent held-out set (≥ 120 claims, checked by `data/nlp/validate_heldout.py`), evaluation logged to MLflow | Hend |
| Decision / UI | Langfuse trace id in the UI; human-review view if the team agrees | Wiem |
| Demo | end-to-end demo with the full Docker image | all |
