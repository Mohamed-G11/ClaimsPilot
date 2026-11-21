# Sprint 2 Progress Report - Hend Zitouni

## Role

NLP Agent Development and Evaluation - ClaimsPilot

## Completed Work

- Improved the keyword-based NLP extractor to version nlp-keywords-v3.
- Added handling for French vehicle-part synonyms and negation.
- Improved consistency classification when described damaged parts are a subset of vision-detected parts.
- Implemented optional local Ollama LLM extraction with strict JSON validation.
- Added automatic keyword fallback for invalid LLM responses, timeouts, and connection failures.
- Kept photo processing exclusively within the Vision agent.
- Added NLP regression tests, LLM extractor tests, and integration tests.
- Extended the evaluation pipeline to compare keywords and LLM methods.
- Added MLflow tracking for accuracy, macro F1, per-class metrics, confusion matrix, execution time, and fallback rate.
- Updated the held-out validator for the revised 60-claim requirement.
- Verified that Ruff passes across the project.

## Development Baseline Results

Dataset: synthetic_claims_v3.csv

| Metric | Result |
|---|---|
| Dataset size | 220 claims |
| Model version | nlp-keywords-v3 |
| Classification accuracy | 98.64% |
| Macro F1 | 0.9380 |
| Consistent F1 | 0.9956 |
| Inconsistent F1 | 0.9852 |
| Uncertain F1 | 0.8333 |
| Part extraction micro F1 | 1.0000 |
| Seconds per claim | 0.00134 |
| NLP tests | 35 passed in latest reported NLP run |

MLflow experiment: claimspilot-nlp

Keyword baseline run ID:
afc683d7c4864f2faf234dab1d62b627

These results are from synthetic development data, not independent held-out evaluation.

## LLM Integration

- Provider: local Ollama
- Configured NLP model: qwen2.5:3b
- Initial target model: qwen2.5:7b
- Temperature: 0
- Configurable timeout: 150 seconds
- Host configurable through OLLAMA_HOST
- Strict JSON extraction with allowed vehicle-part vocabulary
- Automatic fallback to nlp-keywords-v3
- No image data sent to the LLM

The smaller 3B model was selected for local experiments because the 7B model was slow on available hardware.

Real Ollama extraction was verified on a sample claim.

A 10-claim LLM development evaluation was run, but its final metrics and MLflow run ID have not yet been documented.

## Held-Out Evaluation

The validator now requires:

- At least 60 independent claims
- At least 20 claims per consistency class
- At least 30 claims from Wiem
- At least 30 claims from Mohamed
- Both French and English examples
- Valid vehicle parts and unique claim IDs

Current status:

- wiem_claims.csv: 0 claims
- mohamed_claims.csv: 0 claims
- Held-out validation: NOT READY

The held-out evaluation cannot be completed until the independent datasets are provided and reviewed.

## Testing and Quality

- NLP tests: 35 passing in the latest reported NLP run
- Ruff: all project checks passed
- Full project pytest: subsequently reported successful after installing the missing test dependency

## Previous Git Commit

cbab7d0 - feat(nlp): add Sprint 2 evaluation with MLflow metrics

## Pending Work

- Record the final metrics and MLflow run ID for the 10-claim LLM experiment.
- Obtain and review the independent held-out claims.
- Validate class balance and difficult-case coverage.
- Freeze the approved held-out dataset using DVC.
- Evaluate keywords and LLM on the frozen held-out dataset.
- Complete integration testing with the Vision agent.
- Review Git changes and submit the NLP pull request.

## Known Limitations

- Local LLM inference can be slow on CPU-heavy hardware.
- The 3B model may perform differently from the originally requested 7B model.
- Synthetic development performance does not establish held-out generalization.
- Independent held-out performance has not yet been measured.

## Checkpoint Status

Keyword improvements, optional LLM integration, evaluation tooling,
and held-out validation are implemented.

Final independent evaluation remains pending.

## Historical Sprint 2 Results (Keyword v2)

The earlier NLP integration used `nlp-keywords-v2`.

Development evaluation on `sprint2_test.csv` (15 synthetic cases):

- Accuracy: 93.33% (14/15)
- Macro F1: approximately 0.90
- One disagreement: T013 (predicted uncertain; expected inconsistent)
- NLP integration and edge-case tests: 10 passed

Historical MLflow run:
`c174666b74a34dc190970d20ff290d42`

Historical agent commit:
`4ce6d5faaacff7244510d6a9795fb459a4568f82`

The team also generated 220 synthetic claims and 15 challenge cases,
tracked the datasets using DVC, and synchronized them with DagsHub.

These historical results are separate from the newer keyword-v3
evaluation documented above.

## Team Integration Status

- NLP integration and dataset pull requests were previously submitted.
- Final Vision-NLP integration testing remains pending.
- The team must confirm the desired partial-overlap consistency behavior.
