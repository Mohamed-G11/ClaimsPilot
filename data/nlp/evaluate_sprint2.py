
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from agents.nlp.agent import analyze_claim

df = pd.read_csv("data/nlp/sprint2_test.csv").copy()
predictions = []

for _, row in df.iterrows():
    photo_parts = (
        []
        if pd.isna(row["photo_parts"])
        else str(row["photo_parts"]).split("|")
    )

    result = analyze_claim(row["text"], photo_parts)
    predictions.append(result["consistency"])

    print(
        f'{row["claim_id"]}: '
        f'Expected={row["label"]}, '
        f'Predicted={result["consistency"]}'
    )

print("\nClassification report:")
print(
    classification_report(
        df["label"],
        predictions,
        labels=["consistent", "inconsistent", "uncertain"],
        zero_division=0,
    )
)

print("\nConfusion matrix:")
print(
    confusion_matrix(
        df["label"],
        predictions,
        labels=["consistent", "inconsistent", "uncertain"],
    )
)
