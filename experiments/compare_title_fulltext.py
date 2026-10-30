
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sentence_transformers import SentenceTransformer

from src.group_news import MODEL_NAME, article_text

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "experiments" / "data" / "manual_review_articles.json"
LABELS_PATH = ROOT / "experiments" / "data" / "manual_review_pairs.json"


def main():
    with CASES_PATH.open("r", encoding="utf-8-sig") as file:
        cases = json.load(file)

    with LABELS_PATH.open("r", encoding="utf-8-sig") as file:
        labels = json.load(file)

    labels_by_group = {
        str(pair["group"]): pair["label"]
        for pair in labels["pairs"]
    }

    articles = []
    pair_indices = {}

    for group_id, pair in cases["groups"].items():
        if len(pair) != 2:
            raise ValueError(f"Grupp {group_id} måste innehålla två artiklar.")

        start = len(articles)
        articles.extend(pair)
        pair_indices[str(group_id)] = (start, start + 1)

    model = SentenceTransformer(MODEL_NAME)

    title_embeddings = model.encode(
        [article["title"] for article in articles],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    full_embeddings = model.encode(
        [article_text(article) for article in articles],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    results = []

    for group_id, (a, b) in pair_indices.items():
        title_sim = float(np.dot(title_embeddings[a], title_embeddings[b]))
        full_sim = float(np.dot(full_embeddings[a], full_embeddings[b]))
        label = labels_by_group[group_id]
        results.append((group_id, title_sim, full_sim, label))

    print("\nTEST AV VIKTNING AV RUBRIK OCH HELTEXT")
    print("Positivt par = same_event; negativt par = different_events")
    print("Endast lokala testartiklar används.\n")

    for title_weight in (0.0, 0.10, 0.20, 0.30, 0.40):
        false_positive = 0
        false_negative = 0
        correct = 0

        print(f"\nRubrikvikt: {title_weight:.0%} | Heltextvikt: {1-title_weight:.0%}")
        print("-" * 75)

        for group_id, title_sim, full_sim, label in results:
            score = title_weight * title_sim + (1 - title_weight) * full_sim
            predicted_same = score >= 0.75
            expected_same = label == "same_event"

            if predicted_same == expected_same:
                verdict = "KORREKT"
                correct += 1
            elif predicted_same:
                verdict = "FALSK MATCHNING"
                false_positive += 1
            else:
                verdict = "MISSAD MATCHNING"
                false_negative += 1

            print(
                f"Grupp {group_id:>2}: score={score:.3f} | "
                f"etikett={label:<15} | {verdict}"
            )

        print(
            f"Resultat: {correct}/7 korrekta, "
            f"{false_positive} falska matchningar, "
            f"{false_negative} missade matchningar"
        )


if __name__ == "__main__":
    main()
