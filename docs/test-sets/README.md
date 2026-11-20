# Human-written test sets

Three sets of claims that **people** write, so that we measure the agents on text they have never been tuned on. They are templates only: no claim and no expected answer in this folder is real test data. Every expected answer must be written by a human, never generated.

| Set | Folder | Who writes | How many | Measures |
|---|---|---|---|---|
| NLP held-out | `nlp-heldout/` | Mohamed (15) and Wiem (15), plus Hend's independent claims | ≥ 120 in total, ≥ 40 per label (Hend's validator) | text ↔ photo consistency (`consistent / inconsistent / uncertain`) |
| Independent policy claims | `policy-independent/` | Wiem or Hend | about 30 | `covered` true / false / none + evidence clause |
| End-to-end demo claims | `e2e/` | the team (several writers) | 20 to 30 | the final decision `approve / reject / human_review`, through the running API |

## The rule for writers (all sets)

**Do not read the rules, configs, prompts or code of the agent you write for before writing your claims**: `agents/*/config.yaml`, `agents/*/rules.py`, `agents/policy/generation.py`, the keyword lists, `data/policy/eval_claims.csv`, Hend's synthetic data. A claim written after reading the keyword list measures the keyword list, not the agent. Write the way a real customer would, including typos, vague texts and mixed languages.

You **may** read: the contracts themselves (AXA and SANLAM PDFs, for the expected coverage), the part vocabulary below, and this folder.

## How to use a template

1. Copy `template.csv` to the place given in the set's README (not inside `docs/`).
2. **Delete the two rows whose id starts with `EXAMPLE`**: they only show the format. They are not real labels.
3. Fill one row per claim, and put your name in the author column when the set has one.
4. Save as UTF-8 (Excel: "CSV UTF-8").

Part vocabulary (the only allowed part names): `front_bumper, rear_bumper, door, hood, trunk, fender, headlight, taillight, windshield, side_mirror, wheel` (and `other`, except where a README says it is not allowed).
