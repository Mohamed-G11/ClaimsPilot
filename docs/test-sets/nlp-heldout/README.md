# NLP held-out set (text ↔ photo consistency)

**Owner of the set:** Hend (NLP agent). **Writers:** Mohamed (at least 15 claims), Wiem (at least 15 claims), and the independent claims Hend collects.

**Where the files go.** Hend's validator `data/nlp/validate_heldout.py` reads exactly these names:
- `data/nlp/mohamed_claims.csv`
- `data/nlp/wiem_claims.csv`
- `data/nlp/independent_claims.csv`

Then run `python data/nlp/validate_heldout.py`. Hend freezes the set with DVC.

**Size (checked by the validator):** at least 120 claims in total, at least 40 per label, both French and English, no duplicate id or text.

## Columns (exact order, as in `template.csv`)

| Column | Content |
|---|---|
| `claim_id` | unique id, e.g. `M-01` (Mohamed), `W-01` (Wiem) |
| `language` | `fr` or `en` (the validator accepts only these two) |
| `text` | the customer's description, as a customer would write it. May be empty for a photo-only claim |
| `photo_parts` | parts that are damaged on the photos (what vision would see), separated by `\|`. May be empty |
| `true_parts` | parts the **text** names as damaged, separated by `\|` (empty if the text names none) |
| `label` | does the text match the photos? `consistent`, `inconsistent` or `uncertain` |

Parts: the vocabulary of `docs/test-sets/README.md`, **without `other`** (the validator refuses it).

**Label meaning:** use the plain meaning of the words: the text describes the same damage as the photos / a different damage / you cannot tell. Hend, as the set owner, writes the detailed guideline before writing starts. Do not look at how the agent computes it.

**Delete the two `EXAMPLE` rows:** the validator would count them as real claims.

**Rule:** do not read `agents/nlp/`, Hend's synthetic data or the error-analysis notebook before writing (see `docs/test-sets/README.md`).
