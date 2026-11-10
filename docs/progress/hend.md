# Hend Zitouni — NLP Progress

## Sprint 2 — NLP Agent Integration

**Status:** Implementation completed; pull requests awaiting review.

### Completed work

- Implemented the NLP agent using the shared ClaimsPilot schemas.
- Added multilingual keyword-based extraction of vehicle damage parts.
- Implemented text–vision consistency checks: consistent, inconsistent, uncertain.
- Added NLP integration and edge-case tests (10 tests passed).
- Generated 220 synthetic claims and 15 challenge evaluation cases.
- Tracked both datasets with DVC and synchronized them with DagsHub.
- Added dataset generation and evaluation scripts.
- Created separate GitHub pull requests for NLP integration and datasets.

### Evaluation

Model: `nlp-keywords-v2`

Dataset: `sprint2_test.csv` (15 synthetic development cases)

- Accuracy: 93.33% (14/15)
- Macro F1: approximately 0.90
- One disagreement: T013 (predicted uncertain; expected inconsistent)

These are development results on synthetic examples, not independent test performance.

### MLflow

Experiment: `claimspilot-nlp`

Run: `c174666b74a34dc190970d20ff290d42`

Agent Git commit: `4ce6d5faaacff7244510d6a9795fb459a4568f82`

### Pending

- Mohamed's review and merge of both pull requests.
- Team agreement on partial-overlap consistency behavior.
- Final integration testing after merging.
