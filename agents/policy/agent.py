"""Policy agent (RAG): is the claim covered by the client's insurance contract?

Contract (AGENTS.md section 4): run(claim: ClaimInput, vision: VisionResult) -> PolicyResult

Text and photos must agree (the rules decide, the LLM only explains):

1. policy_id "AXA-TR" -> insurer AXA, formula TR (config.yaml `formulas`).
2. Exclusion mentioned in the text (alcohol, no licence, racing, intentional)
   -> covered=None: a human decides, never an automatic reject.
3. Cause read from the text (collision, vol, incendie, bris_de_glace...):
   - the photos must be compatible with it, else covered=None;
   - no cause in the text -> the guarantee is deduced from the damages.
4. Retrieval: clauses of the guarantee + its exclusions, as evidence.
5. Formula check: covered = the formula includes a guarantee paying this cause.
6. Generation: Phi-3.5-mini (Ollama) writes the answer in French from the claim
   and the clauses. If it contradicts the rule -> covered=None. If Ollama is
   unreachable or too slow -> template answer. `model_version` says which.
"""
import logging
from dataclasses import dataclass, field

from agents.policy import generation, rules
from agents.policy.settings import CONFIG
from claimspilot.schemas import ClaimInput, PolicyClause, PolicyResult, VisionResult

logger = logging.getLogger(__name__)

AGENT_VERSION = "policy-rag-v2"
GENERAL_EXCLUSIONS = "exclusions_generales"

PART_FR = {
    "front_bumper": "pare-chocs avant", "rear_bumper": "pare-chocs arrière",
    "door": "portière", "hood": "capot", "trunk": "coffre", "fender": "aile",
    "headlight": "phare avant", "taillight": "feu arrière", "windshield": "pare-brise",
    "side_mirror": "rétroviseur", "wheel": "roue pneumatique", "other": "carrosserie",
}
DAMAGE_FR = {
    "dent": "enfoncement choc", "scratch": "rayure", "crack": "fissure",
    "glass_shatter": "bris de glace", "broken": "cassé",
}


@dataclass
class PolicyAnalysis:
    """The PolicyResult plus how it was obtained (used by evaluate.py and for debugging)."""

    result: PolicyResult
    step: str                          # which rule gave the result, e.g. "formula"
    cause: str | None = None           # cause read from the text
    exclusions: list[str] = field(default_factory=list)
    needed: list[str] = field(default_factory=list)   # guarantees that could pay
    rule_covered: bool | None = None   # what the rules decided, before the LLM check
    generator: str = "none"            # "llm", "template" or "none"
    llm_verdict: bool | None = None    # what the LLM concluded (None = no LLM answer)


def parse_policy_id(policy_id: str) -> tuple[str, str]:
    """'AXA-TR' -> ('AXA', 'TR')."""
    insurer, _, formula = policy_id.upper().partition("-")
    return insurer, formula


def damages_in_french(vision: VisionResult) -> list[str]:
    return [f"{DAMAGE_FR.get(d.damage_type, d.damage_type)} {PART_FR.get(d.part, d.part)}"
            for d in vision.damages]


def build_query(claim: ClaimInput, vision: VisionResult) -> str:
    """Claim text + damages in French words (the policies are in French)."""
    return f"{claim.text} Dommages : {', '.join(damages_in_french(vision))}."


def retrieve(query: str, insurer: str, guarantees: list[str], k: int,
             exclusions: bool) -> list[dict]:
    """Top-k clauses of this insurer among these guarantees.

    exclusions=False -> clauses describing the guarantee; True -> its exclusions.
    """
    from agents.policy.index import embed, ready_collection

    where = {"$and": [{"insurer": insurer}, {"guarantee": {"$in": guarantees}},
                      {"is_exclusion": exclusions}]}
    result = ready_collection().query(query_embeddings=embed([query]), n_results=k,
                                      where=where)
    return [
        {"clause_id": cid, "text": doc, "relevance": round(1 - dist, 3), **meta}
        for cid, doc, dist, meta in zip(result["ids"][0], result["documents"][0],
                                        result["distances"][0], result["metadatas"][0],
                                        strict=True)
    ]


def _to_schema(found: list[dict]) -> list[PolicyClause]:
    chars = CONFIG["retrieval"]["clause_chars"]
    return [PolicyClause(clause_id=c["clause_id"], text=c["text"][:chars],
                         relevance=c["relevance"]) for c in found]


def analyze(claim: ClaimInput, vision: VisionResult, retriever=None,
            generator: generation.Generator | None = None) -> PolicyAnalysis:
    """Full analysis of one claim. `run()` returns only its PolicyResult.

    retriever / generator: None = the real ones (Chroma index, Ollama). Tests pass fakes.
    """
    retriever = retriever or retrieve
    insurer, formula = parse_policy_id(claim.policy_id)
    bought = CONFIG["formulas"].get(formula)
    rcfg = CONFIG["retrieval"]
    query = build_query(claim, vision)
    seen = ", ".join(damages_in_french(vision))

    def done(step, covered, answer, found=(), version="rules", **details) -> PolicyAnalysis:
        result = PolicyResult(claim_id=claim.claim_id, covered=covered, answer=answer,
                              clauses=_to_schema(list(found)),
                              model_version=f"{AGENT_VERSION}+{version}")
        return PolicyAnalysis(result=result, step=step, **details)

    # 1. Which contract?
    if insurer not in CONFIG["insurers"] or bought is None:
        return done("unknown_contract", None,
                    f"Contrat inconnu : {claim.policy_id}. Vérification manuelle nécessaire.")

    # 2. Exclusions mentioned in the text -> a human decides.
    exclusions = rules.detect_exclusions(claim.text)
    cause = rules.detect_cause(claim.text)
    if exclusions:
        # evidence: the general exclusions + the exclusions of the guarantees concerned
        concerned = (rules.guarantees_for_cause(cause) if cause
                     else rules.guarantees_from_damages(vision.damages))
        labels = ", ".join(CONFIG["exclusions"][name]["label"] for name in exclusions)
        hint = rcfg["exclusion_hint"].format(exclusions=labels)
        found = retriever(f"{hint} {claim.text}", insurer, [GENERAL_EXCLUSIONS, *concerned],
                          rcfg["k_guarantee"] + rcfg["k_exclusions"], True)
        refs = " ".join(f"[{c['clause_id']}]" for c in found)
        return done("exclusion", None,
                    f"Exclusion possible relevée dans la déclaration : {labels}. Les "
                    f"exclusions du contrat peuvent s'appliquer {refs}".rstrip()
                    + " : la décision revient à un gestionnaire.",
                    found, cause=cause, exclusions=exclusions)

    # 3. Cause from the text; the photos must agree with it.
    if cause is not None:
        if not rules.is_compatible(cause, vision.damages):
            shown = f"les photos montrent : {seen}" if seen else \
                "aucun dommage n'a été détecté sur les photos"
            return done("incompatible", None,
                        f"Incohérence entre la déclaration et les photos : le sinistre "
                        f"déclaré est « {generation.CAUSE_FR[cause]} », mais {shown}. "
                        "Vérification manuelle nécessaire.", cause=cause)
        needed = rules.guarantees_for_cause(cause)
    elif vision.damages:
        needed = rules.guarantees_from_damages(vision.damages)
    else:
        return done("nothing_to_check", None,
                    "Cause non précisée dans la déclaration et aucun dommage détecté sur "
                    "les photos : vérification manuelle nécessaire.")

    # 4. Evidence: clauses of the guarantee + its exclusions.
    matching = [g for g in needed if g in bought]
    searched = matching or needed
    found = (retriever(query, insurer, searched, rcfg["k_guarantee"], False)
             + retriever(query, insurer, searched, rcfg["k_exclusions"], True))

    # 5. Formula check: the rule that decides covered True / False.
    known = {g for guarantees in CONFIG["formulas"].values() for g in guarantees}
    if not any(g in known for g in needed):
        names = ", ".join(generation.GUARANTEE_FR.get(g, g) for g in needed)
        refs = " ".join(f"[{c['clause_id']}]" for c in found)
        return done("guarantee_not_in_formulas", None,
                    f"La garantie « {names} » n'est rattachée à aucune formule connue : "
                    f"vérification manuelle nécessaire. Clauses à vérifier : {refs or 'aucune'}.",
                    found, cause=cause, needed=needed)
    covered = bool(matching)
    details = {"cause": cause, "needed": needed, "rule_covered": covered}
    if covered and not any(not c["is_exclusion"] for c in found):
        names = ", ".join(generation.GUARANTEE_FR.get(g, g) for g in matching)
        return done("no_evidence", None,
                    f"La formule {formula} inclut la garantie « {names} », mais aucune clause "
                    f"correspondante n'a été trouvée dans les conditions générales {insurer} : "
                    "vérification manuelle nécessaire.", found, **details)

    # 6. Generation: the LLM explains; it cannot change the decision.
    template = generation.template_answer(covered, insurer, formula, cause, needed,
                                          matching, found)
    generate = generator or generation.default_generator()
    try:
        answer = generate(generation.build_prompt(
            claim.text, insurer, formula, bought, cause, damages_in_french(vision),
            needed, found, covered=covered))
    except generation.GeneratorUnavailable as error:
        logger.info("claim %s: template answer (%s)", claim.claim_id, error)
        return done("formula", covered, template, found, "template",
                    generator="template", **details)

    verdict = generation.read_verdict(answer)
    if verdict is None:          # the LLM did not give a readable decision: do not use it
        logger.warning("claim %s: LLM answer without decision, template used", claim.claim_id)
        return done("formula", covered, template, found, "template",
                    generator="template", **details)
    llm = CONFIG["llm"]["model"]
    if verdict != covered:
        return done("llm_contradiction", None,
                    f"La règle conclut « {generation.VERDICT_FR[covered]} » mais la réponse "
                    f"générée conclut « {generation.VERDICT_FR[verdict]} » : vérification "
                    f"manuelle nécessaire. Réponse générée : {answer}", found, llm,
                    generator="llm", llm_verdict=verdict, **details)
    return done("formula", covered, answer, found, llm,
                generator="llm", llm_verdict=verdict, **details)


def run(claim: ClaimInput, vision: VisionResult, retriever=None,
        generator: generation.Generator | None = None) -> PolicyResult:
    return analyze(claim, vision, retriever, generator).result
