# ClaimsPilot

Multi-agent AI assistant for car insurance claims. A customer submits photos and a short description; the system checks them against the insurance policy and decides to **approve**, **reject**, or **send to a human**. Every decision is traceable and monitored.

Academic project – TEK-UP University, 2026–2027.

## Agents

| Agent | What it does | Owner |
|---|---|---|
| Vision | Detects damage on photos (YOLOv8) and rates severity | Wiem Ghouili |
| NLP | Checks the claim text matches what the photos show | Hend Zitouni |
| Policy (RAG) | Finds the relevant policy clauses and says if the damage is covered | Mohamed Jebari |
| Decision | Combines all results (rules in `api/pipeline.py` today, LangGraph agent in sprint 3) | Wiem Ghouili |
| MLOps platform | CI/CD, DVC, MLflow, Docker, API, monitoring | Mohamed Jebari |

## Stack

Python 3.11 · FastAPI · Pydantic · YOLOv8 · sentence-transformers · Chroma · Phi-3.5-mini (Ollama) · LangGraph · Streamlit · DVC + DagsHub · MLflow · Docker · GitHub Actions

## Setup (Windows / PowerShell)

```
git clone https://github.com/Mohamed-G11/ClaimsPilot.git
cd ClaimsPilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Secrets – copy the template and fill in **your own** DagsHub username and token (DagsHub → Settings → Tokens). `.env` is never committed.

```
copy .env.example .env
python -m mlops.check_mlflow_connection     # checks that MLflow accepts your credentials
```

Data and models (DVC):

```
pip install "dvc[s3]"
dvc remote modify origin --local access_key_id YOUR_DAGSHUB_TOKEN
dvc remote modify origin --local secret_access_key YOUR_DAGSHUB_TOKEN
dvc pull
```

### Requirements files

| File | For | Installed in CI |
|---|---|---|
| `requirements.txt` | the API alone (light Docker image) | yes |
| `requirements-dev.txt` | tests, lint, DVC, MLflow | yes |
| `requirements-policy.txt` | policy agent: embeddings, Chroma, PDF reading | no (heavy) |
| `requirements-vision.txt` | vision agent: PyTorch, Ultralytics | no (heavy) |
| `requirements-ui.txt` | Streamlit page | no |
| `requirements-docker.txt` | runtime libraries of the real agents, for the full Docker image | no |

Install the heavy files only for the agent you work on. Without them the API still runs: a missing agent is replaced by a stub and the claim is sent to human review.

## Run

```
uvicorn api.main:app --reload        # API on http://127.0.0.1:8000/docs
streamlit run ui/app.py              # claims page (needs requirements-ui.txt and the API running)
docker compose up --build -d         # API with the real agents in Docker (see "Run with Docker")
pytest                               # tests
ruff check .                         # lint
```

API routes:

- `GET /health` – is the service up.
- `POST /claims` – a claim in, a `Decision` out (approve / reject / human_review + reasons).
- `POST /claims/analyze` – same pipeline, returns every agent's result and which agents were real or stubs.

## Policy agent (RAG)

```
pip install -r requirements-policy.txt
dvc pull data/policy                          # PDFs + clauses
python -m agents.policy.chunking              # PDFs -> data/policy/processed/clauses.jsonl
python -m agents.policy.index                 # clauses -> Chroma index in data/policy/chroma/
```

The Chroma index is rebuilt locally (never committed, never pushed). Settings: `agents/policy/config.yaml`.

How it decides (text and photos must agree; the rules decide, the LLM only explains):

1. An exclusion in the text (alcohol, no licence, racing, intentional damage) → `covered = None`, a human decides.
2. The cause is read from the text (collision, vol, incendie, bris de glace, vandalisme, catastrophe naturelle). The damages seen by vision must be compatible with it, else `covered = None`. No cause in the text → the guarantee is deduced from the damages.
3. The formula (`TR` / `TIERS`) decides `covered = True / False`; the clauses of the guarantee and its exclusions are returned as evidence.
4. Phi-3.5-mini writes the answer in French and cites the clause ids. If it contradicts the rule → `covered = None`. If Ollama is not reachable or too slow → template answer (`model_version` says which).

Answer generation with Ollama (optional – without it the agent uses the template):

```
ollama pull phi3.5                            # once, about 2.2 GB
ollama serve                                  # if the Ollama app is not already running
```

Evaluation on the 30 labelled claims of `data/policy/eval_claims.csv` (logged to MLflow, experiment `claimspilot-policy`):

```
python -m agents.policy.evaluate              # add --no-llm for template answers only
```

## Run with Docker

One `Dockerfile`, two images:

| Target | Built by | Contains | Agents |
|---|---|---|---|
| `light` | CI (`docker build --target light .`) | API + agent code only | NLP real, vision and policy stubs → every claim goes to human review |
| `full` | `docker compose build` | + PyTorch CPU, Ultralytics, sentence-transformers, Chroma | all real |

Model weights and policy data are never inside the image: they are mounted from your disk.

```
dvc pull models/vision/yolov8s_merged_e30.pt.dvc data/policy/processed.dvc
docker compose build                                            # long the first time (several GB)
docker compose run --rm api python -m agents.policy.index       # builds the policy index
docker compose up -d
curl http://localhost:8000/health
```

- Photos: put them in `data/uploads/` and send paths like `data/uploads/c1_front.jpg` (the folder is mounted in the container).
- Ollama runs on your machine, not in Docker: the container reaches it at `host.docker.internal:11434`.
- Which agents were real for a claim: field `agents` of `POST /claims/analyze`.

## Team workflow

- Start each task: `git checkout main` → `git pull` → `git checkout -b feat/<area>-<desc>`
- `main` is protected: pull request + green CI + one approval. Never push to `main`, never work from a fork.
- Data and model weights go through DVC, never Git.
- Every training / evaluation run is logged to the shared MLflow (https://dagshub.com/Mohamed-G11/ClaimsPilot.mlflow) with the tags `owner`, `git_commit`, `data_version`, `sprint` – use `mlops/tracking.py`.
- Data contracts between agents: `claimspilot/schemas.py`. Team rules for AI assistants: `AGENTS.md` (same content in `CLAUDE.md`).
- Progress: `docs/progress/<name>.md`, updated with every PR. Mohamed's detailed build log: `docs/build-log/mohamed.md`.

## Repository structure

```
agents/        vision/, nlp/, policy/, decision/
api/           FastAPI service (routes + pipeline with stub fallback)
claimspilot/   shared schemas
mlops/         MLflow helper and scripts
ui/            Streamlit claims page
data/ models/  DVC-tracked (not in Git)
notebooks/     exploration
tests/         pytest
docs/          progress notes and build log
```
