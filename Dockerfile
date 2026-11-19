# ClaimsPilot API - one Dockerfile, two images:
#
#   docker build --target light -t claimspilot-api .        (CI: small and fast)
#       API + agent code, no heavy library: vision and policy fall back to
#       their stubs, so every claim goes to human review; no LangGraph, so the
#       decision uses the decision agent's rules (agents/decision/rules.py).
#
#   docker build --target full -t claimspilot-api:full .    (docker compose)
#       + PyTorch CPU, Ultralytics, sentence-transformers, Chroma, LangGraph:
#       real agents and the LangGraph decision agent.
#       Model weights and the policy index are NOT in the image: they are
#       mounted as volumes (see docker-compose.yml), after `dvc pull` on the host.

# ---- base: what both images share -------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- full: real agents ---------------------------------------------------------
FROM base AS full

# libraries OpenCV needs at import time (Ultralytics installs opencv-python)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU build of PyTorch first (the default Linux build ships several GB of GPU libraries)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY requirements-docker.txt .
RUN pip install -r requirements-docker.txt

# Decision agent (LangGraph); agents/decision is copied with `COPY agents` below
COPY requirements-decision.txt .
RUN pip install -r requirements-decision.txt

# Downloaded models (embedding model, Ultralytics settings) go to a volume
ENV HF_HOME=/cache/huggingface \
    YOLO_CONFIG_DIR=/cache/ultralytics

COPY claimspilot ./claimspilot
COPY agents ./agents
COPY api ./api

# ---- light: default image (last stage), used by CI ------------------------------
FROM base AS light

COPY claimspilot ./claimspilot
COPY agents ./agents
COPY api ./api
