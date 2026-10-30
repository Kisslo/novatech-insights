import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sentence_transformers import SentenceTransformer

from src.group_news import MODEL_NAME, article_text

CASES_PATH = Path("experiments/data/manual_review_articles.json")
LABELS_PATH = Path("experiments/data/manual_review_pairs.json")
THRESHOLD = 0.75

# Andelen av den kombinerade poängen som kommer från rubriken.
TITLE_WEIGHTS = (0.25, 0.50, 0.75)


def main():
    with CASES_PATH.open("r", encoding="utf-8-sig") as file:
        cases = json.load(file)

    with LABELS_PATH.open("r", encoding="utf-8-sig") as file:
        labels = json.load(file)

    labels_by_group = {
        str(pair["group"]): pair["label"]
        for pair in labels["pairs"]
    }

    model = SentenceTransformer(MODEL_NAME)
    results = []

    for group_id, articles in cases["groups"].items():
        if len(articles) != 2:
            raise ValueError(
                f"Grupp {group_id} måste innehålla exakt två artiklar."
            )

        title_embeddings = model.encode(
            [article["title"] for article in articles],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        full_embeddings = model.encode(
            [article_text(article) for article in articles],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        title_sim = float(
            np.dot(title_embeddings[0], title_embeddings[1])
        )
        full_sim = float(
            np.dot(full_embeddings[0], full_embeddings[1])
        )

        results.append({
            "group": int(group_id),
            "title": title_sim,
            "full": full_sim,
            "label": labels_by_group[str(group_id)],
        })

    print("\nKOMBINATIONSTEST – RUBRIK + HELTEXT")
    print(f"Jämförelsetröskel: {THRESHOLD:.2f}")
    print("Vikter anger rubrikens andel av den kombinerade poängen.\n")

    for weight in TITLE_WEIGHTS:
        print(f"\nRubrikvikt: {weight:.0%} | Heltextvikt: {1-weight:.0%}")
        print("Grupp  Poäng  Över 0.75  Etikett")
        print("-" * 52)

        for result in results:
            score = (
                weight * result["title"]
                + (1 - weight) * result["full"]
            )
            above = "Ja" if score >= THRESHOLD else "Nej"

            print(
                f"{result['group']:>5}  {score:.3f}  "
                f"{above:<10}  {result['label']}"
            )

        # Par över tröskeln behandlas som positiva matchningskandidater.
        tp = sum(
            1 for r in results
            if (
                weight * r["title"] + (1 - weight) * r["full"]
            ) >= THRESHOLD and r["label"] == "same_event"
        )
        fp = sum(
            1 for r in results
            if (
                weight * r["title"] + (1 - weight) * r["full"]
            ) >= THRESHOLD and r["label"] == "different_events"
        )
        fn = sum(
            1 for r in results
            if (
                weight * r["title"] + (1 - weight) * r["full"]
            ) < THRESHOLD and r["label"] == "same_event"
        )

        print(f"Rätt positiva: {tp} | Felaktigt positiva: {fp} | "
              f"Missade positiva: {fn}")

    print(
        "\nOBS: Detta är ett litet diagnostiskt test. "
        "Samma tröskel används endast för jämförelse; "
        "den är inte validerad för kombinerade poäng."
    )


if __name__ == "__main__":
    main()
