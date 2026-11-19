# Sprint 2 Progress Report — Hend Zitouni

## Role
NLP Agent Development and Evaluation — ClaimsPilot

## Completed Work

- Implemented and tested the NLP agent using the shared ClaimsPilot schemas.
- Developed an evaluation script using the NLP agent's run() interface.
- Evaluated 220 synthetic development claims.
- Recorded evaluation metrics and artifacts using MLflow.
- Confirmed the claimspilot-nlp experiment contains one run.
- Executed the existing NLP test suite successfully.

## Development Baseline Results

| Metric | Result |
|---|---|
| Dataset size | 220 claims |
| Classification accuracy | Approximately 97% |
| Macro F1 | 0.8654 |
| Inconsistent recall | Approximately 0.96 |
| Uncertain F1 | Approximately 0.62 |
| NLP tests | 10 passed |

These results are from synthetic development data, not an independent held-out evaluation.

## Git Commit

cbab7d0 — feat(nlp): add Sprint 2 evaluation with MLflow metrics

## Pending Work

- Collect and independently review at least 120 held-out claims.
- Obtain 15 independently written claims each from Wiem and Mohamed.
- Verify difficult-case coverage and class balance.
- Freeze the completed held-out dataset using DVC.
- Perform development-only error analysis and improve NLP rules.
- Evaluate the final agent on the frozen held-out dataset.
- Complete integration testing with the Vision agent.
- Record final results and submit the completed Sprint 2 deliverables.

## Known Limitations

- The current NLP implementation does not explicitly handle negation.
- Some French keyword strings may have encoding issues.
- The existing consistency rules do not yet implement configurable overlap thresholds.
- Held-out performance has not been measured.

## Checkpoint Status

Evaluation pipeline implemented and development baseline recorded.
The complete Sprint 2 evaluation remains in progress.

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
