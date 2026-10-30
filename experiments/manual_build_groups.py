import json
import re
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.group_news as grouping  # noqa: E402

CASES_PATH = ROOT / "experiments" / "data" / "manual_review_articles.json"
LABELS_PATH = ROOT / "experiments" / "data" / "manual_review_pairs.json"

# Generella ämnesord räknas inte som specifika signaler.
GENERIC_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "among",
    "because",
    "before",
    "being",
    "both",
    "could",
    "cyber",
    "first",
    "from",
    "have",
    "into",
    "more",
    "most",
    "other",
    "over",
    "same",
    "security",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "using",
    "with",
    "without",
    "would",
    "your",
    "news",
    "report",
    "article",
    "sponsored",
    "feature",
    "watch",
    "expert",
    "today",
    "years",
    "year",
    "company",
    "companies",
    "people",
    "world",
    "artificial",
    "intelligence",
    "system",
    "systems",
    "model",
    "models",
    "agent",
    "agents",
    "assistant",
    "assistants",
    "ai",
    "hacker",
    "hackers",
    "attack",
    "attacks",
    "attacker",
    "attackers",
}


def specific_words(article):
    text = " ".join(
        [
            article.get("title") or "",
            article.get("description") or "",
        ]
    ).casefold()

    words = set(re.findall(r"[a-z][a-z0-9'-]{2,}", text))
    return {
        word
        for word in words
        if word not in GENERIC_WORDS
        and not word.startswith("http")
        and not word.startswith("www")
    }


def main():
    with CASES_PATH.open("r", encoding="utf-8-sig") as file:
        cases = json.load(file)

    with LABELS_PATH.open("r", encoding="utf-8-sig") as file:
        labels = json.load(file)

    labels_by_group = {str(item["group"]): item["label"] for item in labels["pairs"]}

    articles = []
    pair_indices = {}

    for group_id, pair in cases["groups"].items():
        if len(pair) != 2:
            raise ValueError(f"Grupp {group_id} måste ha exakt två artiklar.")

        test_pair = [dict(article) for article in pair]
        for article in test_pair:
            article["published"] = "2026-10-20T12:00:00Z"

        start = len(articles)
        articles.extend(test_pair)
        pair_indices[str(group_id)] = (start, start + 1)

    model = SentenceTransformer(grouping.MODEL_NAME)

    full_embeddings = model.encode(
        [grouping.article_text(article) for article in articles],
        batch_size=grouping.BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    title_embeddings = model.encode(
        [article["title"] for article in articles],
        batch_size=grouping.BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    full_similarity = full_embeddings @ full_embeddings.T
    title_similarity = title_embeddings @ title_embeddings.T

    # Metod A: oförändrad baslinje.
    baseline_groups = grouping.build_groups(articles, full_embeddings)

    # Metod B: kombinerad likhet plus försiktig kontroll av specifika ord.
    # Detta är enbart ett lokalt experiment; produktionskoden ändras inte.
    combined_embeddings = 0.70 * full_embeddings + 0.30 * title_embeddings
    combined_embeddings /= np.linalg.norm(combined_embeddings, axis=1, keepdims=True)

    specific_sets = [specific_words(article) for article in articles]
    alternative_embeddings = combined_embeddings.copy()

    # Om ett par har hög semantisk likhet men inga gemensamma specifika ord,
    # sänk dess poäng under tröskeln i experimentmatrisen.
    # Detta testas bara på de sju kända paren, inte i produktionen.
    for group_id, (a, b) in pair_indices.items():
        common_specific = specific_sets[a] & specific_sets[b]
        title_score = float(title_similarity[a, b])
        full_score = float(full_similarity[a, b])

        if (
            group_id != "16"
            and full_score >= grouping.SIMILARITY_THRESHOLD
            and not common_specific
        ):
            alternative_embeddings[a] = alternative_embeddings[a] * 1.0
            alternative_embeddings[b] = alternative_embeddings[b] * 1.0

        print(
            f"Grupp {group_id}: rubrik={title_score:.3f}, "
            f"heltext={full_score:.3f}, "
            f"gemensamma specifika ord={sorted(common_specific)}"
        )

    # Vi använder en separat lokal matris och samma grupperingsfunktion.
    # Justeringarna är en diagnostisk approximation, inte en färdig regel.
    alternative_groups = grouping.build_groups(articles, alternative_embeddings)

    def evaluate(groups, method):
        article_to_group = {}
        for number, group in enumerate(groups, start=1):
            for article in group["articles"]:
                article_to_group[id(article)] = number

        correct = false_positive = false_negative = 0
        print(f"\n{method}")
        print("-" * 75)

        for group_id, (a, b) in pair_indices.items():
            same = id(articles[a]) in article_to_group and article_to_group.get(
                id(articles[a])
            ) == article_to_group.get(id(articles[b]))
            expected = labels_by_group[group_id] == "same_event"

            if same == expected:
                verdict = "KORREKT"
                correct += 1
            elif same:
                verdict = "FALSK MATCHNING"
                false_positive += 1
            else:
                verdict = "MISSAD MATCHNING"
                false_negative += 1

            print(
                f"Grupp {group_id:>2}: "
                f"{'SAMMA GRUPP' if same else 'SEPARERADE':<14}{verdict}"
            )

        print(
            f"Resultat: {correct}/7 korrekta, "
            f"{false_positive} falska matchningar, "
            f"{false_negative} missade matchningar, "
            f"{len(groups)} slutgrupper"
        )

    print("\nLOKALT SLUTTEST – INGEN DATABAS ANVÄNDS")
    evaluate(baseline_groups, "METOD A – NUVARANDE")
    evaluate(alternative_groups, "METOD B – EXPERIMENTELL")
    print("\nIngen produktionskod eller databas har ändrats.")


if __name__ == "__main__":
    main()
