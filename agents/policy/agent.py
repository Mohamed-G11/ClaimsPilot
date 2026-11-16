"""Policy agent (RAG): is the damage covered by the client's insurance contract?

Contract (AGENTS.md section 4): run(claim: ClaimInput, vision: VisionResult) -> PolicyResult

1. policy_id "AXA-TR" -> insurer AXA, formula TR (guarantees bought, config.yaml `formulas`)
2. From the damages, deduce which guarantee is needed (bris de glace or collision/accident)
3. Retrieval: search the insurer's general conditions for the most relevant clauses
4. Decision: covered if the formula includes a needed guarantee; answer cites the clauses
"""
from agents.policy.settings import CONFIG
from claimspilot.schemas import ClaimInput, PolicyClause, PolicyResult, VisionResult

MODEL_VERSION = "policy-rag-v1"

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
GLASS_PARTS = {"windshield", "headlight"}
ACCIDENT_GUARANTEES = ["collision", "tous_risques"]


def parse_policy_id(policy_id: str) -> tuple[str, str]:
    """'AXA-TR' -> ('AXA', 'TR')."""
    insurer, _, formula = policy_id.upper().partition("-")
    return insurer, formula


def needed_guarantees(vision: VisionResult) -> list[str]:
    """Which guarantees could pay for these damages."""
    needed: list[str] = []
    for damage in vision.damages:
        if damage.part in GLASS_PARTS or damage.damage_type == "glass_shatter":
            candidates = ["bris_de_glace", *ACCIDENT_GUARANTEES]
        else:
            candidates = ACCIDENT_GUARANTEES
        needed += [g for g in candidates if g not in needed]
    return needed


def build_query(claim: ClaimInput, vision: VisionResult) -> str:
    """Claim text + damages in French words (the policies are in French)."""
    damages = [f"{DAMAGE_FR.get(d.damage_type, d.damage_type)} {PART_FR.get(d.part, d.part)}"
               for d in vision.damages]
    return f"{claim.text} Dommages : {', '.join(damages)}."


def retrieve(query: str, insurer: str, guarantees: list[str], k: int) -> list[dict]:
    """Top-k clauses of this insurer, among the clauses of these guarantees."""
    from agents.policy.index import embed, ready_collection

    where = {"$and": [{"insurer": insurer}, {"guarantee": {"$in": guarantees}}]}
    result = ready_collection().query(query_embeddings=embed([query]), n_results=k, where=where)
    return [
        {"clause_id": cid, "text": doc, "relevance": round(1 - dist, 3), **meta}
        for cid, doc, dist, meta in zip(result["ids"][0], result["documents"][0],
                                        result["distances"][0], result["metadatas"][0],
                                        strict=True)
    ]


def run(claim: ClaimInput, vision: VisionResult, retriever=retrieve) -> PolicyResult:
    insurer, formula = parse_policy_id(claim.policy_id)
    bought = CONFIG["formulas"].get(formula)

    def result(covered, answer, clauses=()):
        return PolicyResult(claim_id=claim.claim_id, covered=covered, answer=answer,
                            clauses=list(clauses), model_version=MODEL_VERSION)

    if insurer not in CONFIG["insurers"] or bought is None:
        return result(None, f"Contrat inconnu : {claim.policy_id}.")
    if not vision.damages:
        return result(None, "Aucun dommage détecté sur les photos : vérification manuelle.")

    needed = needed_guarantees(vision)
    found = retriever(build_query(claim, vision), insurer, needed + ["franchise"],
                      CONFIG["top_k"])
    clauses = [PolicyClause(clause_id=c["clause_id"], text=c["text"][:600],
                            relevance=c["relevance"]) for c in found]
    matching = [g for g in needed if g in bought]
    titles = list(dict.fromkeys(f"{c['title']} (p. {c['page']})" for c in found))
    refs = ", ".join(titles[:2])

    if matching:
        return result(True, f"Couvert par la garantie « {matching[0]} » de la formule "
                            f"{formula} ({insurer}). Clauses : {refs}. Vérifier les "
                            "exclusions et la franchise.", clauses)
    return result(False, f"Non couvert : la formule {formula} ({insurer}) n'inclut pas "
                         f"les garanties nécessaires ({', '.join(needed)}). Clauses : {refs}.",
                  clauses)
