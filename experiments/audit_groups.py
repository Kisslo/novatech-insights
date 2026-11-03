from collections import Counter
from itertools import combinations

import numpy as np
from sentence_transformers import SentenceTransformer

import src.group_news as grouping

MODEL_NAME = grouping.MODEL_NAME
LOW_COHESION_THRESHOLD = 0.80
LARGE_GROUP_SIZE = 5
MAX_GROUPS_TO_PRINT = 30


def audit_group(group, embeddings, article_index):
    """Beräkna kvalitetsmått och artikelpar för en nyhetsgrupp."""
    articles = group["articles"]
    indices = [article_index[id(article)] for article in articles]

    group_embeddings = embeddings[indices]
    similarity_matrix = group_embeddings @ group_embeddings.T

    if len(articles) > 1:
        upper_indices = np.triu_indices(len(articles), k=1)
        pair_similarities = similarity_matrix[upper_indices]

        minimum_similarity = float(pair_similarities.min())
        average_similarity = float(pair_similarities.mean())
    else:
        minimum_similarity = 1.0
        average_similarity = 1.0

    sources = [(article.get("source") or "").strip() for article in articles]
    source_counts = Counter(source.casefold() for source in sources if source)

    # Beräkna likheten mellan varje artikelpar.
    pairs = []
    for i, j in combinations(range(len(articles)), 2):
        pairs.append(
            {
                "article_a": articles[i],
                "article_b": articles[j],
                "similarity": float(similarity_matrix[i, j]),
            }
        )

    pairs.sort(key=lambda pair: pair["similarity"])

    return {
        "group": group,
        "minimum_similarity": minimum_similarity,
        "average_similarity": average_similarity,
        "duplicate_sources": [
            source for source, count in source_counts.items() if count > 1
        ],
        "pairs": pairs,
    }


def print_article(article):
    """Skriv ut artikelns källa, rubrik, beskrivning och länk."""
    print(f"    Källa: {article.get('source') or 'Okänd källa'}")
    print(f"    Rubrik: {article.get('title') or 'Ingen rubrik'}")

    description = (
        article.get("description")
        or article.get("subject")
        or "Ingen beskrivning tillgänglig."
    )

    print(f"    Beskrivning: {description}")
    print(f"    Länk: {article.get('link') or 'Ingen länk'}")


def print_group_audit(number, item):
    """Skriv ut en grupp och dess svagaste artikelpar."""
    group = item["group"]

    print(
        f"\nGrupp {number}: {group['article_count']} artiklar, "
        f"{group['source_count']} källor"
    )
    print(f"Genomsnittlig parlikhet: {item['average_similarity']:.3f}")
    print(f"Lägsta parlikhet: {item['minimum_similarity']:.3f}")

    if item["duplicate_sources"]:
        print("VARNING – upprepade källor: " + ", ".join(item["duplicate_sources"]))

    print("\n  Artiklar:")
    for article in group["articles"]:
        print_article(article)
        print()

    print("  Artikelpar, från lägst till högst likhet:")
    for pair in item["pairs"]:
        print(f"\n  Likhet: {pair['similarity']:.3f}")
        print("  Artikel A:")
        print_article(pair["article_a"])
        print("  Artikel B:")
        print_article(pair["article_b"])


def main():
    print("Hämtar artiklar från public.news (endast läsning)...")
    articles = grouping.fetch_articles()
    articles = grouping.deduplicate_articles(articles)

    if len(articles) < 2:
        print("För få artiklar att analysera.")
        return

    print(f"\nArtiklar att analysera: {len(articles)}")
    print(f"Likhetströskel: {grouping.SIMILARITY_THRESHOLD}")
    print(f"Tidsfönster: {grouping.MAX_DAYS_APART} dagar")

    print("\nLaddar modellen och beräknar embeddings...")
    model = SentenceTransformer(MODEL_NAME)

    embeddings = model.encode(
        [grouping.article_text(article) for article in articles],
        batch_size=grouping.BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    print("\nBygger nyhetsgrupper...")
    groups = grouping.build_groups(articles, embeddings)

    article_index = {id(article): index for index, article in enumerate(articles)}

    audits = [audit_group(group, embeddings, article_index) for group in groups]

    audits.sort(
        key=lambda item: (
            item["minimum_similarity"],
            -item["group"]["article_count"],
        )
    )

    print("\n" + "=" * 80)
    print("GRANSKNING AV NYHETSGRUPPER")
    print("=" * 80)
    print(f"Analyserade artiklar: {len(articles)}")
    print(f"Grupper med minst två källor: {len(groups)}")

    low_cohesion = [
        item for item in audits if item["minimum_similarity"] < LOW_COHESION_THRESHOLD
    ]
    large_groups = [
        item for item in audits if item["group"]["article_count"] >= LARGE_GROUP_SIZE
    ]
    repeated_sources = [item for item in audits if item["duplicate_sources"]]

    print(
        f"Grupper med minsta parlikhet under "
        f"{LOW_COHESION_THRESHOLD:.2f}: {len(low_cohesion)}"
    )
    print(f"Grupper med minst {LARGE_GROUP_SIZE} artiklar: {len(large_groups)}")
    print(f"Grupper med upprepade källor: {len(repeated_sources)}")

    print("\nLÄGSTA SAMMANHÅLLNING – GRANSKA DESSA FÖRST")
    print("-" * 80)

    for number, item in enumerate(audits[:MAX_GROUPS_TO_PRINT], start=1):
        print_group_audit(number, item)

    # Skriv ut grupper med upprepade källor separat om de inte
    # redan finns bland de 30 grupper som visats.
    printed_group_ids = {id(item["group"]) for item in audits[:MAX_GROUPS_TO_PRINT]}

    remaining_repeated = [
        item for item in repeated_sources if id(item["group"]) not in printed_group_ids
    ]

    if remaining_repeated:
        print("\nGRUPPER MED UPPREPADE KÄLLOR")
        print("-" * 80)

        for number, item in enumerate(remaining_repeated, start=1):
            print_group_audit(number, item)

    print("\n" + "=" * 80)
    print("GRANSKNING KLAR – INGA DATABASÄNDRINGAR HAR GJORTS")


if __name__ == "__main__":
    main()
