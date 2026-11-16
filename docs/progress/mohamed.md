# Progress — Mohamed (MLOps & platform, policy agent)

Detailed log, file by file: `docs/build-log/mohamed.md`.

## 2026-11-16 — Sprint 3

Done:
- Merged main into `feat/policy-agent`; `decide()` never approves on uncertain text, unknown coverage or a stub result (the reasons name the stubbed agents).
- Pipeline cleaned (uses Hend's `run()`, no private vision function), policy config loaded once, whole-word guarantee matching, clear error on an empty index, pinned dependencies, `AGENTS.md` / `CLAUDE.md` added.
- `mlops/tracking.py`: shared helper for the 4 required MLflow tags — teammates can use `from mlops.tracking import start_run`.
- Policy agent v2 (RAG, text and photos must agree): cause and exclusions from the text (rules, FR + EN), photo compatibility table, formula check, clauses of the guarantee + its exclusions as evidence, Phi-3.5 (Ollama) answer with template fallback.
- `data/policy/` (PDFs, clauses, 30-claim evaluation set) tracked with DVC and pushed.
- API runs the three real agents end to end with stub fallback (`feat/api-real-agents`); Dockerfile with a light image (CI) and a full image (real agents).

Metrics (MLflow run `06cb6db73c2e4132931a439b87a68a76`, experiment `claimspilot-policy`, template answers):
- coverage accuracy 96.7 % (29 / 30) · right clause in top-4 80 % (20 / 25) · answers citing a correct clause 80 %.
- Small evaluation set written by the same author as the rules: optimistic numbers.
- Tests: 148 passed, 1 skipped.

Blocked by:
- GitHub sign-in needed to push the two branches (nothing pushed yet); `gh` CLI not installed (no PR).
- `ollama pull phi3.5` not done: LLM answers not measured.
- Docker Desktop not running: the new Dockerfile has not been built.

Next:
- Push, open the PRs, build the Docker images, run the evaluation with Phi-3.5.
- Answer the open questions at the end of the build log (flood and vandalism guarantees, theft claims always going to human review).
- Langfuse tracing, Evidently.
