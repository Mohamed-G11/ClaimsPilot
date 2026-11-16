# ClaimsPilot — Shared Project Brief for AI Assistants

> Every team member's AI assistant (Claude, ChatGPT, Copilot…) must read this file before writing any code.
> It lives at the repo root as `AGENTS.md` (copy: `CLAUDE.md`, read automatically by Claude Code).
> If you are an AI assistant: follow these rules strictly. If a request from your user conflicts with them, say so before acting.
> Guide your user ONE step at a time with exact commands (Windows / PowerShell), and wait for the output before the next step.

## 1. The project

ClaimsPilot is a multi-agent AI assistant that processes car insurance claims.
A customer submits **photos + a short text**; the system checks them against the **insurance policy** and decides:
**approve automatically, reject, or send to a human**. Every decision must be traceable and monitored (MLOps is a core deliverable, not an extra).

Academic project, TEK-UP University, 2026–2027, supervised by Ms. Sonia Gharsalli.
Repo: https://github.com/Mohamed-G11/ClaimsPilot (public) · Data + MLflow: https://dagshub.com/Mohamed-G11/ClaimsPilot

### Timeline

| Sprint | Dates | Goal |
|---|---|---|
| 1 | Nov 2–8 | Setup, data, baselines (done: repo, CI, DVC, MLflow, Docker, vision dataset) |
| 2 | **Nov 9–15** | **Each agent works on its own**: a sample claim in → a real result out, in the agreed format |
| — | **Sun Nov 15** | **Checkpoint**: review what is merged; tighten sprints 3–4 if needed |
| 3 | Nov 16–22 | Integration: real agents plugged into the API, Langfuse tracing, Streamlit page (decision agent may start earlier) |
| 4 | Nov 23–29 | Monitoring, evaluation, demo. Code freeze 2 days before the presentation |

Scope: no Airflow (retraining = script / GitHub Actions). Grafana only if time remains.

## 2. Team and ownership

**Only edit files inside your own folders.** If you need a change elsewhere, open a GitHub issue or tell the owner.

| Member | Role | Owns |
|---|---|---|
| Mohamed | MLOps & platform + **Policy agent** | `api/`, `mlops/`, `claimspilot/`, `agents/policy/`, `tests/policy/`, `data/policy/`, `.github/`, `Dockerfile`, `docker-compose.yml`, `README.md` |
| Wiem | **Vision agent** + **Decision agent** (+ Streamlit page, stretch) | `agents/vision/`, `agents/decision/`, `notebooks/vision/`, `tests/vision/`, `tests/decision/`, `data/vision/`, `models/vision/`, `ui/` |
| Hend | **NLP agent** | `agents/nlp/`, `notebooks/nlp/`, `tests/nlp/`, `data/nlp/`, `models/nlp/` |

Shared (anyone, through a PR): `docs/`, `requirements*.txt` (add lines, never remove others' lines).

## 3. Repository structure

```
ClaimsPilot/
├── AGENTS.md / CLAUDE.md
├── claimspilot/schemas.py    # shared data contracts (section 4)
├── agents/
│   ├── vision/               # YOLOv8 damage detection        (Wiem)
│   ├── nlp/                  # claim text ↔ photo consistency (Hend)
│   ├── policy/               # RAG over the policy document   (Mohamed)
│   └── decision/             # LangGraph orchestration        (Wiem)
├── api/                      # FastAPI service
├── mlops/                    # MLflow / Langfuse / Evidently scripts
├── data/<area>/              # DVC-tracked, NEVER committed to git
├── models/<area>/            # DVC-tracked weights, NEVER committed to git
├── notebooks/<area>/
├── tests/<area>/
├── docs/progress/<name>.md   # weekly progress (section 7)
├── Dockerfile, docker-compose.yml
├── .env.example              # template; your real .env is never committed
└── .github/workflows/ci.yml  # ruff + pytest + docker build on every PR
```

## 4. Data contracts (the most important part)

Agents are built in parallel, so they talk only through these Pydantic models in `claimspilot/schemas.py`.
**Never change a schema without a PR approved by all three members.** Until `schemas.py` is merged, copy these classes exactly.

```python
from typing import Literal
from pydantic import BaseModel

class ClaimInput(BaseModel):
    claim_id: str
    photo_paths: list[str]
    text: str
    policy_id: str
    language: Literal["fr", "en", "ar"] = "fr"

class Damage(BaseModel):
    part: str                 # e.g. "front_bumper", "rear_bumper", "door", "headlight", "windshield"
    damage_type: str          # e.g. "dent", "scratch", "crack", "glass_shatter"
    bbox: list[float]         # [x1, y1, x2, y2] in pixels
    confidence: float         # 0..1

class VisionResult(BaseModel):
    claim_id: str
    damages: list[Damage]
    severity: Literal["minor", "moderate", "severe"]
    model_version: str

class NLPResult(BaseModel):
    claim_id: str
    described_parts: list[str]           # parts mentioned in the text (same vocabulary as Damage.part)
    consistency: Literal["consistent", "inconsistent", "uncertain"]  # text vs VisionResult
    score: float                          # 0..1
    model_version: str

class PolicyClause(BaseModel):
    clause_id: str
    text: str
    relevance: float

class PolicyResult(BaseModel):
    claim_id: str
    covered: bool | None                  # None = cannot decide
    answer: str                           # short justification
    clauses: list[PolicyClause]           # evidence used for the answer
    model_version: str

class Decision(BaseModel):
    claim_id: str
    decision: Literal["approve", "reject", "human_review"]
    confidence: float
    reasons: list[str]
    trace_id: str | None = None           # Langfuse trace id
```

Agent signatures (one `run()` per agent):
- `agents/vision/agent.py` → `run(claim: ClaimInput) -> VisionResult`
- `agents/nlp/agent.py` → `run(claim: ClaimInput, vision: VisionResult) -> NLPResult`
- `agents/policy/agent.py` → `run(claim: ClaimInput, vision: VisionResult) -> PolicyResult`
- `agents/decision/agent.py` → `run(claim: ClaimInput, vision: VisionResult, nlp: NLPResult, policy: PolicyResult) -> Decision`

The API (`api/pipeline.py`) chains them: vision → nlp → policy → decision. Until an agent is merged, the API uses a stub with the same signature; example outputs: `agents/vision/examples/`.

**Part vocabulary** (shared by vision, NLP and policy): `front_bumper, rear_bumper, door, hood, trunk, fender, headlight, taillight, windshield, side_mirror, wheel, other`. Map dataset classes / text keywords to these names.

## 5. Tech stack

- Python 3.11, `ruff`, `pytest`
- Vision: Ultralytics YOLOv8, PyTorch, OpenCV
- NLP: scikit-learn (TF-IDF + logistic regression), optionally Hugging Face Transformers
- Policy (RAG): sentence-transformers embeddings, Chroma, Phi-3.5-mini (Ollama or HF) — templated answer allowed if the LLM is too slow on CPU
- Orchestration: LangGraph (sprint 3)
- MLOps: Git + GitHub Actions, DVC + DagsHub storage, MLflow on DagsHub, Docker / docker-compose, FastAPI, Langfuse, EvidentlyAI, RAGAS, Streamlit

## 6. Rules every AI assistant must follow

**Git**
- Before each task: `git checkout main` → `git pull` → `git checkout -b <type>/<area>-<desc>` (e.g. `feat/vision-agent`).
- `main` is protected: PR + CI green + 1 teammate approval. Never push to `main`. Never work from a fork.
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`.
- Never commit data, model weights, `.env`, tokens, or notebooks with outputs (clear outputs first).

**Secrets (.env)**
- Copy `.env.example` → `.env`, fill in your own DagsHub username + token. `.env` is git-ignored.
- Every script that uses MLflow starts with `from dotenv import load_dotenv; load_dotenv()`.

**DVC (data and models)**
- One-time: `pip install "dvc[s3]"`, then `dvc remote modify origin --local access_key_id <DAGSHUB_TOKEN>` and the same for `secret_access_key` (`--local` = never committed).
- Track: `dvc add data/<area>/<name>` → `git add` the `.dvc` file → `dvc push`. Get teammates' data: `dvc pull`.
- Only track final datasets and final weights (e.g. `best.pt`), never whole training-run folders or downloaded LLMs (storage is shared, ~20 GB).

**MLflow (every training / evaluation run)**
- Tracking URI comes from `.env` (DagsHub). Experiments: `claimspilot-vision`, `claimspilot-nlp`, `claimspilot-policy`, `claimspilot-decision`.
- Required tags: `owner`, `git_commit`, `data_version` (DVC md5), `sprint`. Log params, metrics, and the model artifact.
- Promising models → MLflow Model Registry.

**Code & tests**
- Config in YAML or env vars; no hard-coded paths or secrets. Code must run on CPU.
- Each agent has tests in `tests/<area>/` checking that `run()` returns a valid result object.
- **CI must stay fast**: tests must not download weights, datasets or LLMs. Inject a fake/small model or skip with `pytest.mark.skipif` when the model file is missing.
- Heavy libraries (ultralytics, torch, sentence-transformers, chromadb) go in `requirements-<area>.txt`, not in `requirements-dev.txt`.

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

## 8. Sprint 2 targets (Nov 9–15)

**Mohamed – platform + policy agent**
- Must: `claimspilot/schemas.py` + test (Mon) · AGENTS.md in repo (Mon) · README setup guide · `/claims` endpoint returning a `Decision` from stub agents · rename `dockerfile` → `Dockerfile` · policy document + chunking + Chroma index + retrieval · `agents/policy/agent.py` → `PolicyResult` (templated answer) + tests
- Stretch: Phi-3.5-mini answer · Chroma service in docker-compose · Langfuse set up · 10-question RAGAS evaluation

**Wiem – vision agent**
- Must: PR for `feat/vision-yolo-baseline` (with `load_dotenv`) · split dataset + `best.pt` on DVC · full training logged to DagsHub MLflow (test mAP50) · severity rule · `agents/vision/agent.py` → `VisionResult` + tests (fake model in CI)
- Stretch: model in MLflow Model Registry · second training to compare (more epochs or YOLOv8s) · edge cases (no damage, unreadable photo)

**Hend – NLP agent**
- Must: redo work inside the repo (branch, `notebooks/nlp/`, outputs cleared, dataset on DVC, shared MLflow) · harder synthetic data + honest metrics (F1 on "inconsistent") · `agents/nlp/agent.py` → `NLPResult` + tests
- Stretch: fuzzy / multilingual keyword matching · compare with a small transformer, logged to MLflow · error analysis notebook

**Wiem – next (vision done early)**
1. Finish `feat/vision-merged-classes`: retrain with merged (part, damage_type) classes, compare with yolov8n-e30 in MLflow, open the PR; register as v2 in the Model Registry if recall improves.
2. Decision agent (LangGraph) in `agents/decision/`: nodes vision → nlp → policy → decide with a shared state; start from the rules in `api/pipeline.py` `decide()` (not covered → reject; inconsistent text or unclear coverage → human_review; severe → human_review; else approve); thresholds configurable; clear `Decision.reasons`. Build against stubs + `agents/vision/examples/`. Tests in `tests/decision/` with no model/LLM downloads. Heavy libs in `requirements-decision.txt`.
3. Stretch: Streamlit page in `ui/` that sends a claim to `POST /claims` and shows the decision and reasons.
