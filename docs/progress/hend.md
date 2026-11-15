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
