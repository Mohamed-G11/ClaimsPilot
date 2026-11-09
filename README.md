# ClaimsPilot

Multi-agent AI assistant for car insurance claims. A customer submits photos and a short description; the system checks them against the insurance policy and decides to **approve**, **reject**, or **send to a human**. Every decision is traceable and monitored.

Academic project – TEK-UP University, 2026–2027.

## Agents

| Agent | What it does | Owner |
|---            |---                                                   |                              ---|
| Vision        | Detects damage on photos (YOLOv8) and rates severity                | Wiem Ghouili |
| NLP           | Checks the claim text matches what the photos show                  | Hend Zitouni |
| Policy(RAG)   | Finds the relevant policy clauses and says if the damage is covered | Mohamed Jebari |
| Decision      | Combines all results (LangGraph)                                    | Sprint 3 |
| MLOpsplatform | CI/CD, DVC, MLflow, Docker, API, monitoring | Mohamed Jebari |

## Stack

Python 3.11 · FastAPI · Pydantic · YOLOv8 · scikit-learn · Chroma · LangGraph · DVC + DagsHub · MLflow · Docker · GitHub Actions

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
```

Data and models (DVC):

```
pip install "dvc[s3]"
dvc remote modify origin --local access_key_id YOUR_DAGSHUB_TOKEN
dvc remote modify origin --local secret_access_key YOUR_DAGSHUB_TOKEN
dvc pull
```

Vision agent dependencies (only if you work on vision): `pip install -r requirements-vision.txt`

## Run

```
uvicorn api.main:app --reload        # API on http://127.0.0.1:8000/docs
docker compose up --build -d         # same API in Docker, with healthcheck
pytest                               # tests
ruff check .                         # lint
```

## Team workflow

- Start each task: `git checkout main` → `git pull` → `git checkout -b feat/<area>-<desc>`
- `main` is protected: pull request + green CI + one approval. Never push to `main`, never work from a fork.
- Data and model weights go through DVC, never Git.
- Every training is logged to the shared MLflow: https://dagshub.com/Mohamed-G11/ClaimsPilot.mlflow
- Data contracts between agents: `claimspilot/schemas.py`. Team rules for AI assistants: `AGENTS.md`.
- Progress: `docs/progress/<name>.md`, updated with every PR.

## Repository structure

```
agents/        vision/, nlp/, policy/, decision/
api/           FastAPI service
claimspilot/   shared schemas
mlops/         MLflow / monitoring scripts
data/ models/  DVC-tracked (not in Git)
notebooks/     exploration
tests/         pytest
```