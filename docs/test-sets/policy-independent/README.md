# Independent policy claims (coverage)

**Writer:** Wiem or Hend, not Mohamed: he wrote the policy rules and the first 30 claims. **How many:** about 30.

**Where the file goes:** `data/policy/independent_claims.csv`, then `dvc add` it. Mohamed runs the evaluation:

```
python -m agents.policy.evaluate --cases data/policy/independent_claims.csv
```

**Why:** the current 30 claims (`data/policy/eval_claims.csv`) were written by the author of the rules, so the 96.7 % coverage accuracy is optimistic (build log entry 4).

## Columns (same format as `data/policy/eval_claims.csv`)

| Column | Content |
|---|---|
| `claim_id` | unique id, e.g. `I-01` |
| `policy_id` | insurer + formula: `AXA-TR`, `AXA-TIERS`, `SANLAM-TR`, `SANLAM-TIERS` |
| `language` | `fr` or `en` |
| `text` | the customer's description |
| `damages` | what the photos would show: `part:type` separated by `\|` (types: `dent`, `scratch`, `crack`, `glass_shatter`), empty if nothing visible |
| `expected_covered` | your reading **of the contract PDF**: `true`, `false`, or `none` (a human must decide: exclusion, unclear case, text and photos disagree) |
| `expected_clauses` | the clause ids that justify your answer, separated by `\|`, empty if none. Ask Mohamed for the list of clause ids and titles (`data/policy/processed/clauses.jsonl`): titles only, not the rules |
| `category` | a short word for the type of case, your choice (e.g. `collision`, `vol`, `exclusion`) |
| `note` | anything useful (why it is hard, what you hesitated on) |

Try to cover:
- each formula and insurer;
- each cause (collision, theft, fire, glass, vandalism, flood);
- exclusions (alcohol, no licence, racing, on purpose);
- texts that disagree with the photos, texts with no cause, English texts.

**Delete the two `EXAMPLE` rows:** the evaluation script refuses them.

**Rule:** read the contracts (AXA and SANLAM PDFs) to decide `expected_covered`, but **not** `agents/policy/config.yaml`, `rules.py`, the prompts or `eval_claims.csv`.
