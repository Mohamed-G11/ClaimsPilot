
from pathlib import Path

import pandas as pd

examples = [
    ("T001", "fr", "Mon pare-chocs avant est rayé.", "front_bumper", "consistent"),
    ("T002", "en", "The rear bumper was damaged.", "rear_bumper", "consistent"),
    ("T003", "fr", "Le pare-brise est fissuré.", "windshield", "consistent"),
    ("T004", "en", "My front bumper is broken.", "door", "inconsistent"),
    ("T005", "fr", "La portière est abîmée.", "headlight", "inconsistent"),
    ("T006", "en", "The windshield is cracked.", "rear_bumper", "inconsistent"),
    ("T007", "fr", "Ma voiture a été touchée.", "", "uncertain"),
    ("T008", "en", "Something is damaged on my car.", "", "uncertain"),
    ("T009", "fr", "Le rétroviseur gauche est cassé.", "door", "inconsistent"),
    ("T010", "en", "The bonnet has a dent.", "front_bumper", "inconsistent"),
    ("T011", "fr", "Le pare-chocs arrière et le phare sont abîmés.", "rear_bumper|headlight", "consistent"),
    ("T012", "en", "Both the front bumper and door are damaged.", "front_bumper|door", "consistent"),
    ("T013", "fr", "Le pare-chocs avant est endommagé.", "front_bumper|door", "inconsistent"),
    ("T014", "en", "My front headlamp is shattered.", "headlight", "consistent"),
    ("T015", "fr", "Le capot est enfoncé.", "hood", "consistent"),
]

df = pd.DataFrame(
    examples,
    columns=["claim_id", "language", "text", "photo_parts", "label"],
)

output = Path("data/nlp/sprint2_test.csv")
df.to_csv(output, index=False, encoding="utf-8")

print(f"Saved {len(df)} test claims to {output}")
print(df["label"].value_counts())
