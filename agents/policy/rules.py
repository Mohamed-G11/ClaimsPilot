"""Rule-based reading of a claim: cause, exclusions, photo compatibility.

Everything here is pure Python on small strings and lists: no model, no index.
All keywords and tables live in config.yaml.

    detect_cause("On a volé ma voiture")            -> "vol"
    detect_exclusions("j'avais bu de l'alcool")     -> ["alcool"]
    is_compatible("bris_de_glace", vision.damages)  -> True / False
"""
import re
import unicodedata
from functools import cache

from agents.policy.settings import CONFIG
from claimspilot.schemas import Damage


def normalize(text: str) -> str:
    """Lower case, no accents, punctuation replaced by spaces.

    "Pare-brise fissuré à l'avant !" -> "pare brise fissure a l avant"
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.replace("_", " "))
    return re.sub(r"\s+", " ", text).strip()


@cache
def _pattern(keywords: tuple[str, ...]) -> re.Pattern:
    """One regular expression matching any of the keywords as whole words."""
    words = sorted({normalize(k) for k in keywords}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + r")(?!\w)")


def _found(keywords: list[str], plain_text: str) -> bool:
    return _pattern(tuple(keywords)).search(plain_text) is not None


def _without_ignored(plain_text: str) -> str:
    """Remove expressions such as "feu arriere" that would look like a cause."""
    return _pattern(tuple(CONFIG["ignore_phrases"])).sub(" ", plain_text)


def detect_causes(text: str) -> list[str]:
    """Every cause whose keywords appear in the text, in config.yaml order."""
    plain = _without_ignored(normalize(text))
    return [cause for cause, cfg in CONFIG["causes"].items() if _found(cfg["keywords"], plain)]


def detect_cause(text: str) -> str | None:
    """The cause of the claim, or None when the text does not state one."""
    causes = detect_causes(text)
    return causes[0] if causes else None


def detect_exclusions(text: str) -> list[str]:
    """Names of the exclusions (alcool, sans_permis...) mentioned in the text."""
    plain = normalize(text)
    return [name for name, cfg in CONFIG["exclusions"].items() if _found(cfg["keywords"], plain)]


def is_compatible(cause: str, damages: list[Damage]) -> bool:
    """Do the damages seen on the photos fit the cause stated in the text?"""
    table = CONFIG["compatibility"][cause]
    if table.get("required") is False:
        return True
    parts = set(table.get("parts", []))
    types = set(table.get("damage_types", []))
    return any(d.part in parts or d.damage_type in types for d in damages)


def guarantees_for_cause(cause: str) -> list[str]:
    return list(CONFIG["causes"][cause]["guarantees"])


def guarantees_from_damages(damages: list[Damage]) -> list[str]:
    """No cause stated: which guarantees could pay for these damages."""
    cfg = CONFIG["from_damages"]
    needed: list[str] = []
    for damage in damages:
        is_glass = (damage.part in cfg["glass_parts"]
                    or damage.damage_type in cfg["glass_damage_types"])
        candidates = cfg["glass_guarantees"] if is_glass else cfg["default_guarantees"]
        needed += [g for g in candidates if g not in needed]
    return needed
