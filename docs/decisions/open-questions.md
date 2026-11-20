# Decision sheet — the 12 open questions on rules and evaluation

For Mohamed (and the team where a teammate's file is involved). **No rule was changed:** every "what changes" below was measured with in-memory copies of the config, or read from the code.

Written 2026-11-20 on `feat/e2e-evaluation`.

**Which 12:** items 1–11 and 17 of "Open questions for Mohamed (Nov 16)" at the end of `docs/build-log/mohamed.md`: decision rules, policy rules, evaluation. The platform items of that list (12–16, 18) are not here, and most are already answered: AGENTS.md source, Ollama in compose (entry 10), photos between UI and API (shared volume, entries 10 and 13). Newer questions (entries 10–14) are in the morning summary.

**How "eval claims that change" was measured:**
- policy level: the 30 claims of `data/policy/eval_claims.csv`, template answers (no LLM), today's config vs a copy with the option applied;
- decision level: each eval claim through Hend's real NLP agent + the policy rules + Wiem's decision rules (`agents/decision/rules.py`), using the damages written in the CSV as the vision result.

Today: policy coverage accuracy **96.7 %** (29 / 30; only E11 fails). Final decisions on the 30 claims: 8 approve, 5 reject, 17 human_review.

| Final decision today | Claims |
|---|---|
| approve (8) | E01, E05, E06, E14, E15, E18, E23, E25 |
| reject (5) | E03, E04, E10, E17, E24 |
| human_review (17) | E02, E07, E08, E09, E11, E12, E13, E16, E19, E20, E21, E22, E26, E27, E28, E29, E30 |

(These final decisions are not labelled: the eval set only has expected *coverage*. They show what each option moves, not whether it is right.)

---

## Decision rules

### Q1. Reject before or after the text checks?

**Today:** `covered = False` → **reject**, even when NLP says `inconsistent` or `uncertain` (Wiem's `rules.decide`: reject is checked first).

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep (reject first) | nothing | none |
| B. Text doubt wins: `inconsistent` / `uncertain` → human_review even when not covered | `agents/decision/rules.py` (Wiem's file) + maybe a config flag `reject_needs_consistent_text`; tests in `tests/decision/test_rules.py` (e.g. `test_not_covered_is_rejected_first`) | **E10** (AXA-TIERS theft, NLP `uncertain`): reject → human_review. E03, E04, E17, E24 stay reject (NLP consistent) |
| C. Only `inconsistent` wins over reject (`uncertain` does not) | same files | none in the eval set (no not-covered claim is `inconsistent`) |

### Q8. Theft / fire with no visible damage always go to a human

**Today:** NLP returns `uncertain`, score 0.0, when the text names no part. Vision sees nothing. Three decision rules fire (uncertain text, low NLP score, no damage), so the claim goes to human_review even when the policy says covered.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep (a human checks every theft / fire) | nothing | none |
| B. "No damage needed" causes may be approved: when the cause is theft / fire / flood and the policy says covered, skip the 3 photo/text rules | the decision needs the **cause**, but `PolicyResult` has no cause field. Either a **schema change** (`PolicyResult.cause`, needs all 3 members) or parse it from `PolicyResult.answer` (fragile). Then `agents/decision/rules.py` + config (Wiem) and tests | **E08, E09, E12, E13** (covered theft and fire): human_review → **approve** |
| C. Same as B but with a lower confidence, or only for TR contracts | same as B + a confidence value in `agents/decision/config.yaml` | same 4 claims |

---

## Policy rules (`agents/policy/config.yaml`, Mohamed)

### Q2. Several causes in one text

**Today:** the first cause in config order wins (collision, vol, incendie, bris_de_glace, vandalisme, catastrophe_naturelle).

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep "first cause wins" | nothing | none |
| B. Several causes → `covered = None` (human) | `agents/policy/agent.py` (one new step) + a test | **E06** ("Collision avec un camion : le pare-brise est fissuré et le capot est enfoncé": collision + bris_de_glace): policy True → None, final decision approve → human_review; policy accuracy 96.7 → 93.3 % unless E06's label changes |
| C. Several causes → covered only if **all** their guarantees are in the formula | `agent.py` + tests | none in the eval set (E06's two guarantees are both in TR) |

### Q3. Flood / natural catastrophe

**Today:** `catastrophe_naturelle` is in no formula, so the step is `guarantee_not_in_formulas` → `covered = None`.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep (a human decides) | nothing | none |
| B. Add `catastrophe_naturelle` to TR for both insurers | `formulas.TR` in `config.yaml` | **E21** (SANLAM-TR flood): None → **True**; its label says none (Q10), so the label must change too. **E22** (AXA-TR flood): None → None, but the step becomes `no_evidence` (no AXA clause tagged catastrophe_naturelle; AXA covers floods inside "tous accidents", AXA-013). Final decisions do not change (no damage + uncertain text still → human_review) |
| C. Per-insurer formulas (SANLAM: separate guarantees R12/R13; AXA: inside tous accidents) | `config.yaml` structure (`formulas` per insurer) + `agent.py` + tests | E21, E22 depend on the chosen mapping |

### Q4. AXA and vandalism

**Today:** TR lists `vandalisme` for both insurers, but AXA's general conditions have no vandalism guarantee. Step `no_evidence` → `covered = None`.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep (a human decides) | nothing | none |
| B. Per-insurer formulas: AXA-TR without `vandalisme` | `config.yaml` (`formulas` per insurer) + `agent.py` + tests | **E20** (AXA-TR vandalism): None → **False**, final decision human_review → **reject** (automatic). Label E20 must change (Q10) |
| C. Map AXA vandalism to "tous accidents" (if the contract supports it) | `causes.vandalisme.guarantees` per insurer | E20: None → True; needs someone to confirm in the AXA PDF |

### Q5. Collision with only a windshield damage

**Today:** collision is compatible with body parts and lights only. "Collision" + only a windshield damage → `incompatible` → None.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep | nothing | none |
| B. Add `windshield` / `glass_shatter` to the collision compatibility | `compatibility.collision` in `config.yaml` | **none in the eval set** (measured: accuracy unchanged, no claim has collision + windshield only). The e2e or independent sets should include such a case |

### Q6. When the LLM is called

**Today:** only when the rules give True / False (18 of the 30 claims). The 12 others (exclusion, incompatible, unknown guarantee, no evidence, nothing to check) get a fixed French sentence.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep | nothing | none |
| B. Also call the LLM for `None` cases, to explain why a human must check | `agent.py`, `generation.build_prompt` (new instruction), tests; about +20 s per such claim | covered stays None, so no result changes; the explanations of the 12 claims change (E07, E11, E16, E19–E22, E26–E30) |

### Q7. LLM answer without a readable "Décision :" line

**Today:** the template answer is used and `covered` stays the rule's verdict.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep | nothing | none |
| B. Unreadable answer → `covered = None` | `agent.py` + test | **none measured**: 0 unreadable answers in 3 × 18 qwen2.5:7b calls (entries 9 and 14) |

### Q9. Keyword lists

**Today:** "dérobé", "cambriolé", "grêle", "tempête" are not keywords.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep | nothing | none |
| B. Add dérobé(e), cambriolé(e) to `vol`; grêle, tempête to `catastrophe_naturelle` | `causes` in `config.yaml` + `tests/policy/test_rules.py` | **E11** ("On m'a dérobé mon véhicule"): None → **True**, policy accuracy **96.7 → 100 %**. The final decision stays human_review (Q8). Note: E11 was written as a "hard" case for exactly this, so the gain is optimistic |
| C. Let a teammate propose the list (avoids tuning on our own eval set) | same files, after their list | — |

### Q17. Headlights and the glass guarantee

**Today:** with no cause in the text, a broken headlight is treated as glass for both insurers (`from_damages.glass_parts`), although SANLAM's glass clause does not list headlights.

| Option | What changes | Eval claims that change |
|---|---|---|
| A. Keep | nothing | none |
| B. Headlight is not glass (both insurers) | `from_damages.glass_parts` and `compatibility.bris_de_glace.parts` | **none in the eval set** (measured) |
| C. Per insurer: headlight is glass for AXA only | per-insurer config + `agent.py` | none in the eval set |

---

## Evaluation

### Q10. Labels of E20, E21, E22

**Today:** expected = `none` (human review), following the temporary defaults of Q3 and Q4.

| Option | What changes |
|---|---|
| A. Keep, if Q3 and Q4 stay A | nothing |
| B. Relabel to follow the decisions of Q3 / Q4 (e.g. E20 → false if Q4-B, E21 → true if Q3-B) | `data/policy/eval_claims.csv` (DVC: `dvc add` + push), a **human** decides each label |

### Q11. Independent evaluation set

**Today:** the 30 claims were written by the author of the rules.

| Option | What changes |
|---|---|
| A. A teammate writes about 30 claims | template ready: `docs/test-sets/policy-independent/` (task 7); run with `python -m agents.policy.evaluate --cases data/policy/independent_claims.csv` |
| B. Relabel Hend's synthetic claims for coverage | her texts were generated by the same kind of rules; less independent |
| C. Both | — |

---

## Summary: what each "B" option would move

| Question | Option B moves | Final decision change |
|---|---|---|
| Q1 | E10 | reject → human_review |
| Q8 | E08, E09, E12, E13 | human_review → approve |
| Q2 | E06 | approve → human_review |
| Q3 | E21 (policy only) | none |
| Q4 | E20 | human_review → reject |
| Q5, Q7, Q17 | none in the eval set | none |
| Q6 | explanations of 12 claims | none |
| Q9 | E11 (policy only) | none |
| Q10, Q11 | labels / new data | — |
