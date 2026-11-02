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


def main():
    with CASES_PATH.open("r", encoding="utf-8-sig") as file:
        cases = json.load(file)

    with LABELS_PATH.open("r", encoding="utf-8-sig") as file:
        labels = json.load(file)

    articles_by_group = cases["groups"]
    labels_by_group = {str(pair["group"]): pair for pair in labels["pairs"]}

    model = SentenceTransformer(MODEL_NAME)
    results = []

    for group_id, articles in articles_by_group.items():
        if len(articles) != 2:
            raise ValueError(f"Grupp {group_id} måste innehålla exakt två artiklar.")

        texts = [article_text(article) for article in articles]
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        similarity = float(np.dot(embeddings[0], embeddings[1]))
        label = labels_by_group[str(group_id)]["label"]
        results.append((int(group_id), similarity, label))

    print("\nMANUELL GRANSKNING – LIKHETSTEST")
    print(f"Nuvarande tröskel: {THRESHOLD:.2f}\n")
    print("Grupp  Likhet  Över tröskel  Manuell etikett")
    print("-" * 55)

    for group_id, similarity, label in results:
        above = "Ja" if similarity >= THRESHOLD else "Nej"
        print(f"{group_id:>5}  {similarity:.3f}   {above:<13} {label}")

    print("\nObs: Detta mäter enbart parlikhet, inte slutlig gruppering.")


if __name__ == "__main__":
    main()
