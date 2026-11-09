
from pathlib import Path

import pandas as pd

SOURCE = Path("notebooks/nlp/synthetic_claims_v2.csv")
OUTPUT = Path("data/nlp/synthetic_claims_v3.csv")

df = pd.read_csv(SOURCE)

examples = [
    # French: synonyms and spelling mistakes
    ("fr", "Le pare choc avant est abimé.", "front_bumper", "front_bumper", "consistent"),
    ("fr", "Ma portiere gauche est enfoncée.", "door", "door", "consistent"),
    ("fr", "Le pare brise est fissuré.", "windshield", "windshield", "consistent"),
    ("fr", "Le par choc avant est cassé.", "front_bumper", "front_bumper", "consistent"),
    ("fr", "Le feu avant est endommagé.", "headlight", "headlight", "consistent"),

    # English: paraphrases and typos
    ("en", "The front bumber is damaged.", "front_bumper", "front_bumper", "consistent"),
    ("en", "My windscreen has a crack.", "windshield", "windshield", "consistent"),
    ("en", "The rear bumper has a dent.", "rear_bumper", "rear_bumper", "consistent"),
    ("en", "My car's side door was hit.", "door", "door", "consistent"),
    ("en", "The front lamp is broken.", "headlight", "headlight", "consistent"),

    # Multiple damaged parts
    ("fr", "Le pare-chocs avant et le phare sont cassés.",
     "front_bumper|headlight", "front_bumper|headlight", "consistent"),
    ("en", "The front bumper and windshield are damaged.",
     "front_bumper|windshield", "front_bumper|windshield", "consistent"),

    # Partial mismatches
    ("fr", "Le pare-chocs avant et la portière sont abîmés.",
     "front_bumper", "front_bumper|door", "inconsistent"),
    ("en", "My rear bumper and headlight are broken.",
     "rear_bumper", "rear_bumper|headlight", "inconsistent"),
    ("en", "The front bumper is damaged.",
     "front_bumper|door", "front_bumper", "inconsistent"),

    # Uncertain descriptions
    ("fr", "Ma voiture est abîmée après un accident.",
     "", "", "uncertain"),
    ("en", "There is damage somewhere on my vehicle.",
     "", "", "uncertain"),
    ("fr", "J'ai entendu un bruit pendant le choc.",
     "door", "", "uncertain"),
    ("en", "I noticed something unusual after the crash.",
     "headlight", "", "uncertain"),
    ("fr", "Je ne sais pas quelle pièce est touchée.",
     "", "", "uncertain"),
]

new_rows = []
for i, (language, claim_text, photo, described, label) in enumerate(examples, 201):
    new_rows.append({
        "claim_id": f"C{i:03d}",
        "language": language,
        "text": claim_text,
        "photo_parts": photo,
        "described_parts": described,
        "label": label,
    })

combined = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
combined.to_csv(OUTPUT, index=False, encoding="utf-8")

print(f"Dataset saved: {OUTPUT}")
print(f"Total claims: {len(combined)}")
print(combined["label"].value_counts())
