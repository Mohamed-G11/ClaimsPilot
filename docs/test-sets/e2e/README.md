# End-to-end demo claims (final decision)

**Writers:** the team, several writers; each signs the rows they wrote (`written_by`). **How many:** 20 to 30.

**Where the files go:**
- the CSV: `data/e2e/demo_claims.csv` (git-ignored);
- the photos: `data/uploads/e2e/`, mounted in the API container as `/app/data/uploads/e2e/`. You can also use dataset test photos (`/app/data/vision/car_dent_scratch_split/test/images/...`).

**Run** (the Docker stack must be running: `docker compose up -d`):

```
python -m mlops.evaluate_e2e --claims data/e2e/demo_claims.csv
```

The script sends each claim to `POST /claims/analyze`. It records the decision, the decision status, the seconds, the Langfuse trace id and whether the decision matches `expected_decision`. Results go to `data/e2e/e2e_results.json` and to MLflow (`claimspilot-decision`, tag `eval=e2e`). Add `--no-mlflow` for a quick try.

## Columns

| Column | Content |
|---|---|
| `claim_id` | unique id, e.g. `DEMO-01` (it also names the Langfuse trace) |
| `photo_paths` | one or more photo paths **as the API container sees them**, separated by `\|` |
| `text` | the customer's description |
| `policy_id` | `AXA-TR`, `AXA-TIERS`, `SANLAM-TR`, `SANLAM-TIERS` |
| `language` | `fr`, `en` or `ar` |
| `expected_decision` | what a claims handler should decide: `approve`, `reject` or `human_review`. **Leave it empty** if you are not sure: the claim is run but not scored |
| `written_by` | your name |

**Delete the two `EXAMPLE` rows:** the script refuses any row whose `claim_id` starts with `EXAMPLE`.

**Rule:** decide `expected_decision` as a claims handler would, from the contract, the photo and common sense. Do **not** use the agents' rules, configs or prompts. A good set mixes clear approvals, clear rejections (third-party contracts, exclusions) and cases that should go to a human.
