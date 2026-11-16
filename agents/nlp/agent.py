
import re
import unicodedata

from claimspilot.schemas import PARTS, ClaimInput, NLPResult, VisionResult


def normalize_text(text: str) -> str:
    """Normalize French and English claim descriptions."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()



PART_KEYWORDS = {
    "front_bumper": [
        "pare-chocs avant", "pare choc avant",
        "par choc avant", "devant de ma voiture",
        "front bumper", "front bumber", "front of my car",
    ],
   "rear_bumper": [
    "pare-chocs arri\u00e8re",
    "pare choc arri\u00e8re",
    "arri\u00e8re de ma voiture",
    "rear bumper",
    "back bumper",
],
    
    "door": [
     "portière", "portiere", "porte de mon véhicule",
     "porte du véhicule", "car door", "my door",
     "side door", "door",
    ],

    "hood": [
        "capot", "capot moteur", "hood", "bonnet",
    ],
    "trunk": [
        "coffre", "hayon", "trunk", "boot",
    ],
    "fender": [
        "aile avant", "aile arrière", "aile gauche",
        "aile droite", "fender", "wing panel",
    ],
    "headlight": [
        "phare", "feu avant", "headlight",
        "headlamp", "front lamp",
    ],
    "taillight": [
        "feu arrière", "phare arrière",
        "taillight", "tail light", "rear light",
    ],
    "windshield": [
        "pare-brise", "pare brise",
        "windshield", "windscreen",
    ],
    "side_mirror": [
        "rétroviseur", "retro", "side mirror",
        "wing mirror", "door mirror",
    ],
    "wheel": [
        "roue", "jante", "pneu", "wheel", "tire", "tyre",
    ],
}

assert set(PART_KEYWORDS) == set(PARTS) - {"other"}


def extract_damaged_parts(text: str) -> list[str]:
    """Extract damaged vehicle parts from a claim description."""
    normalized = normalize_text(text)
    detected = []

    for part, keywords in PART_KEYWORDS.items():
        for keyword in keywords:
            normalized_keyword = normalize_text(keyword)

            pattern = (
                r"(?<!\w)"
                + re.escape(normalized_keyword)
                + r"(?!\w)"
            )

            if re.search(pattern, normalized):
                detected.append(part)
                break

    return detected

def check_consistency(
    described_parts: list[str],
    vision_parts: list[str],
) -> str:
    """Compare text and vision parts with tolerance for partial matches."""

    described = set(described_parts) - {"other"}
    detected = set(vision_parts) - {"other"}

    if not described or not detected:
        return "uncertain"

    overlap = described & detected

    if not overlap:
        return "inconsistent"

    if described == detected:
        return "consistent"

    return "uncertain"

def analyze_claim(text: str, vision_parts: list[str]) -> dict:
    """Analyze a claim description against detected visual damage."""

    described_parts = extract_damaged_parts(text)

    consistency = check_consistency(
        described_parts,
        vision_parts
    )

    return {
        "described_parts": described_parts,
        "consistency": consistency,
    }

def run(claim: ClaimInput, vision: VisionResult) -> NLPResult:
    """Analyze a claim using the shared ClaimsPilot schemas."""

    if claim.claim_id != vision.claim_id:
        raise ValueError("Claim and vision result IDs do not match")

    described_parts = extract_damaged_parts(claim.text)

    vision_parts = [
        damage.part
        for damage in vision.damages
        if damage.part in PARTS and damage.part != "other"
    ]

    consistency = check_consistency(
        described_parts,
        vision_parts,
    )

    described = set(described_parts) - {"other"}
    detected = set(vision_parts) - {"other"}

    if described and detected:
        score = len(described & detected) / len(described | detected)
    else:
        score = 0.0

    return NLPResult(
        claim_id=claim.claim_id,
        described_parts=described_parts,
        consistency=consistency,
        score=round(score, 4),
        model_version="nlp-keywords-v2",
    )

