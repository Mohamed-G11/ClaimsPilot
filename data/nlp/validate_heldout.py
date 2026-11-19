
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from claimspilot.schemas import PARTS

DATA_DIR = Path(__file__).resolve().parent

FILES = [
    "independent_claims.csv",
    "wiem_claims.csv",
    "mohamed_claims.csv",
]

REQUIRED = [
    "claim_id",
    "language",
    "text",
    "photo_parts",
    "true_parts",
    "label",
]

LABELS = {"consistent", "inconsistent", "uncertain"}
VALID_PARTS = set(PARTS) - {"other"}
MIN_TOTAL = 120
MIN_PER_CLASS = 40


def parse_parts(value):
    """Parse vehicle parts separated by | or ;."""
    return {
        part.strip()
        for part in re.split(r"[|;]", value or "")
        if part.strip()
    }


def validate():
    all_rows = []
    errors = []
    ids = set()
    descriptions = set()
    contributions = Counter()

    for filename in FILES:
        path = DATA_DIR / filename

        if not path.exists():
            errors.append(f"Missing file: {filename}")
            continue

        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames != REQUIRED:
                errors.append(f"{filename}: invalid columns")
                continue

            for line, row in enumerate(reader, start=2):
                prefix = f"{filename}:{line}"
                claim_id = (row["claim_id"] or "").strip()
                text = (row["text"] or "").strip()

                if not claim_id or claim_id in ids:
                    errors.append(
                        f"{prefix}: missing or duplicate claim ID"
                    )

                ids.add(claim_id)

                if row["language"] not in {"fr", "en"}:
                    errors.append(
                        f"{prefix}: invalid language"
                    )

                if row["label"] not in LABELS:
                    errors.append(
                        f"{prefix}: invalid label"
                    )

                photo = parse_parts(row["photo_parts"])
                true = parse_parts(row["true_parts"])

                if not photo <= VALID_PARTS:
                    errors.append(
                        f"{prefix}: invalid photo parts"
                    )

                if not true <= VALID_PARTS:
                    errors.append(
                        f"{prefix}: invalid true parts"
                    )

                # Empty text is allowed for photo-only claims.
                # Both text and photo parts cannot be empty.
                if not text and not photo:
                    errors.append(
                        f"{prefix}: both text and photo parts are empty"
                    )

                # Detect duplicate nonempty descriptions.
                normalized_text = " ".join(text.lower().split())

                if normalized_text:
                    if normalized_text in descriptions:
                        errors.append(
                            f"{prefix}: duplicate description"
                        )

                    descriptions.add(normalized_text)

                all_rows.append(row)
                contributions[filename] += 1

    labels = Counter(
        row["label"] for row in all_rows
    )

    languages = Counter(
        row["language"] for row in all_rows
    )

    print("\n=== ClaimsPilot Held-Out Validation ===")

    print(f"\nTotal claims: {len(all_rows)}/{MIN_TOTAL}")

    print("\nClass distribution:")
    for label in sorted(LABELS):
        print(f"  {label}: {labels[label]}/{MIN_PER_CLASS}")

    print("\nLanguage distribution:")
    for language in ["fr", "en"]:
        print(f"  {language}: {languages[language]}")

    print("\nContributions:")
    for filename in FILES:
        print(f"  {filename}: {contributions[filename]}")

    if contributions["wiem_claims.csv"] < 15:
        errors.append("Wiem must contribute at least 15 claims")

    if contributions["mohamed_claims.csv"] < 15:
        errors.append("Mohamed must contribute at least 15 claims")

    if len(all_rows) < MIN_TOTAL:
        errors.append(
            f"Dataset incomplete: {len(all_rows)}/{MIN_TOTAL}"
        )

    for label in LABELS:
        if labels[label] < MIN_PER_CLASS:
            errors.append(
                f"Insufficient {label} claims: "
                f"{labels[label]}/{MIN_PER_CLASS}"
            )

    if languages["fr"] == 0 or languages["en"] == 0:
        errors.append(
            "Dataset must contain both French and English"
        )

    print(f"\nValidation errors: {len(errors)}")

    for error in errors:
        print(f"  - {error}")

    print(
        "\nManual review still required for:\n"
        "  - Independent authorship\n"
        "  - Correct consistency labels\n"
        "  - Negation and synonyms\n"
        "  - Typos and informal language\n"
        "  - Multiple damaged parts\n"
        "  - Vague and irrelevant descriptions\n"
        "  - Photo-only and text-only cases"
    )

    if errors:
        print("\nSTATUS: NOT READY")
        return False

    print("\nSTATUS: STRUCTURALLY VALID")
    print("Human review is still required before freezing.")
    return True


if __name__ == "__main__":
    sys.exit(0 if validate() else 1)

