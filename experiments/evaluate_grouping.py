import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

import src.group_news as grouping

# --------------------------------------------------
# INSTÄLLNINGAR
# --------------------------------------------------

CASES_PATH = Path("experiments/data/grouping_cases.json")

MODEL_NAME = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

THRESHOLDS_TO_TEST = [0.70, 0.75, 0.80, 0.85, 0.90]
BASELINE_THRESHOLD = 0.80


# --------------------------------------------------
# LÄS TESTFALL OCH HÄMTA ARTIKLAR
# --------------------------------------------------

def load_cases():
    with CASES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def prepare_test_data():
    cases = load_cases()

    # Hämtar artiklar från public.news via befintlig funktion.
    articles = grouping.fetch_articles()

    print(f"\nHämtade artiklar: {len(articles)}")

    articles = grouping.deduplicate_articles(articles)

    print(f"Artiklar efter deduplicering: {len(articles)}")

    def normalize_title(title):
        return " ".join(str(title or "").casefold().split())

    # Behåll samtliga artiklar med samma normaliserade rubrik.
    articles_by_title = {}

    for article in articles:
        title = article.get("title")

        if not title:
            continue

        normalized = normalize_title(title)
        articles_by_title.setdefault(normalized, []).append(article)

    selected_by_id = {}
    event_by_id = {}
    missing_titles = []
    ambiguous_titles = []

    for event in cases["events"]:
        event_id = event["id"]

        for title in event["titles"]:
            normalized = normalize_title(title)
            matches = articles_by_title.get(normalized, [])

            if not matches:
                missing_titles.append((event_id, title))
                continue

            if len(matches) > 1:
                ambiguous_titles.append(
                    (event_id, title, len(matches))
                )

            for article in matches:
                article_id = article.get("id")

                if article_id is None:
                    print(
                        "VARNING: En artikel saknar ID och kan "
                        f"inte utvärderas: {title}"
                    )
                    continue

                if article_id in event_by_id:
                    if event_by_id[article_id] != event_id:
                        raise ValueError(
                            f"Artikel-ID {article_id} matchar flera "
                            "olika förväntade händelser."
                        )
                    continue

                selected_by_id[article_id] = article
                event_by_id[article_id] = event_id

    selected_articles = list(selected_by_id.values())

    print(f"Förväntade händelser: {len(cases['events'])}")
    print(f"Matchade testartiklar: {len(selected_articles)}")

    if ambiguous_titles:
        print(
            "\nVARNING: Följande titlar matchade flera artiklar:"
        )

        for event_id, title, count in ambiguous_titles:
            print(f"  [{event_id}] {title} ({count} träffar)")

    if missing_titles:
        print(
            f"\nVARNING: {len(missing_titles)} testtitlar "
            "hittades inte i public.news:"
        )

        for event_id, title in missing_titles:
            print(f"  [{event_id}] {title}")

    if not selected_articles:
        raise ValueError(
            "Inga testartiklar hittades. Kontrollera "
            "experiments/data/grouping_cases.json och public.news."
        )

    return selected_articles, event_by_id


# --------------------------------------------------
# BERÄKNA LIKHETSMATRIS
# --------------------------------------------------

def calculate_similarity_matrix(embeddings):
    """
    Embeddingarna är normaliserade.
    Därför motsvarar skalärprodukten cosinuslikheten.
    """
    similarity_matrix = np.asarray(
        embeddings @ embeddings.T,
        dtype=np.float32,
    )

    np.clip(
        similarity_matrix,
        -1.0,
        1.0,
        out=similarity_matrix,
    )

    return similarity_matrix


# --------------------------------------------------
# DIAGNOSTIK FÖR TRÖSKELVÄRDEN
# --------------------------------------------------

def print_threshold_diagnostics(articles, embeddings):
    """
    Visar hur många artikelpar som passerar varje tröskel
    samt vilka par som ligger mellan de testade trösklarna.

    Detta analyserar endast det manuellt märkta testurvalet.
    """

    print("\n" + "=" * 80)
    print("DIAGNOSTIK: KANDIDATPAR VID OLIKA TRÖSKLAR")
    print("=" * 80)

    similarity_matrix = calculate_similarity_matrix(embeddings)

    upper_i, upper_j = np.triu_indices(
        len(articles),
        k=1,
    )

    scores = similarity_matrix[upper_i, upper_j]

    print(f"Totalt antal möjliga artikelpar: {len(scores)}")
    print()

    for threshold in THRESHOLDS_TO_TEST:
        count = int(np.sum(scores >= threshold))

        print(
            f"Tröskel {threshold:.2f}: "
            f"{count} kandidatpar"
        )

    lowest_threshold = min(THRESHOLDS_TO_TEST)
    highest_threshold = max(THRESHOLDS_TO_TEST)

    # Par som passerar den lägsta tröskeln men inte den högsta.
    between_mask = (
        (scores >= lowest_threshold)
        & (scores < highest_threshold)
    )

    between_indices = np.flatnonzero(between_mask)

    print(
        f"\nArtikelpar med likhet mellan "
        f"{lowest_threshold:.2f} och under "
        f"{highest_threshold:.2f}: "
        f"{len(between_indices)}"
    )

    if len(between_indices) == 0:
        print(
            "Inga artikelpar ligger i detta intervall. "
            "Det kan förklara varför kandidatantalet inte "
            "förändras mellan den lägsta och högsta tröskeln."
        )
        return

    # Sortera paren från högst till lägst likhet.
    between_indices = sorted(
        between_indices,
        key=lambda index: scores[index],
        reverse=True,
    )

    print("\nArtikelpar i intervallet:")

    for pair_index in between_indices:
        i = int(upper_i[pair_index])
        j = int(upper_j[pair_index])
        score = float(scores[pair_index])

        article_a = articles[i]
        article_b = articles[j]

        print(f"\nLikhet: {score:.4f}")
        print(f"A [{article_a.get('source', 'Okänd källa')}]:")
        print(f"  {article_a.get('title')}")
        print(f"B [{article_b.get('source', 'Okänd källa')}]:")
        print(f"  {article_b.get('title')}")


# --------------------------------------------------
# UTVÄRDERA GRUPPER
# --------------------------------------------------

def evaluate_groups(articles, groups, event_by_id):
    """
    TP: samma händelse, grupperade tillsammans.
    FP: olika händelser, grupperade tillsammans.
    FN: samma händelse, inte grupperade tillsammans.
    TN: olika händelser, inte grupperade tillsammans.

    Utvärderingen görs på artikelpar inom testurvalet.
    """

    predicted_group_by_id = {}

    for group_number, group in enumerate(groups):
        for article in group["articles"]:
            article_id = article.get("id")

            if article_id is not None:
                predicted_group_by_id[article_id] = group_number

    tp = fp = fn = tn = 0

    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            article_a = articles[i]
            article_b = articles[j]

            id_a = article_a["id"]
            id_b = article_b["id"]

            same_event = event_by_id[id_a] == event_by_id[id_b]

            same_predicted_group = (
                id_a in predicted_group_by_id
                and id_b in predicted_group_by_id
                and predicted_group_by_id[id_a]
                == predicted_group_by_id[id_b]
            )

            if same_event and same_predicted_group:
                tp += 1
            elif not same_event and same_predicted_group:
                fp += 1
            elif same_event and not same_predicted_group:
                fn += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "predicted_group_by_id": predicted_group_by_id,
    }


def print_metrics(threshold, metrics):
    print(
        f"{threshold:.2f}  "
        f"{metrics['tp']:>3}  "
        f"{metrics['fp']:>3}  "
        f"{metrics['fn']:>3}  "
        f"{metrics['tn']:>3}  "
        f"{metrics['precision']:.3f}  "
        f"{metrics['recall']:.3f}  "
        f"{metrics['f1']:.3f}"
    )


# --------------------------------------------------
# DATUMANALYS
# --------------------------------------------------

def parse_article_date(article):
    try:
        return grouping.parse_published(
            article.get("published")
        )
    except (ValueError, TypeError, AttributeError):
        return None


def date_gap_days(article_a, article_b):
    date_a = parse_article_date(article_a)
    date_b = parse_article_date(article_b)

    if date_a is None or date_b is None:
        return None

    try:
        difference = abs(
            (date_a - date_b).total_seconds()
        )
    except TypeError:
        date_a = date_a.replace(tzinfo=None)
        date_b = date_b.replace(tzinfo=None)

        difference = abs(
            (date_a - date_b).total_seconds()
        )

    return difference / 86400


# --------------------------------------------------
# VISA MISSADE POSITIVA PAR
# --------------------------------------------------

def print_missed_pairs(
    articles,
    embeddings,
    event_by_id,
    metrics,
    threshold,
):
    print("\n" + "=" * 80)
    print(f"MISSADE POSITIVA PAR VID TRÖSKEL {threshold:.2f}")
    print("=" * 80)

    predicted_groups = metrics["predicted_group_by_id"]

    similarity_matrix = calculate_similarity_matrix(embeddings)

    max_days = getattr(grouping, "MAX_DAYS_APART", 7)
    missed_count = 0

    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            article_a = articles[i]
            article_b = articles[j]

            id_a = article_a["id"]
            id_b = article_b["id"]

            if event_by_id[id_a] != event_by_id[id_b]:
                continue

            group_a = predicted_groups.get(id_a)
            group_b = predicted_groups.get(id_b)

            if group_a is not None and group_a == group_b:
                continue

            missed_count += 1

            similarity = float(similarity_matrix[i, j])
            gap = date_gap_days(article_a, article_b)

            reasons = []

            if similarity < threshold:
                reasons.append(
                    "likheten ligger under tröskeln"
                )

            if gap is not None and gap > max_days:
                reasons.append(
                    f"datumskillnaden överstiger {max_days} dagar"
                )

            if not reasons:
                reasons.append(
                    "möjlig complete-link-begränsning eller "
                    "annan begränsning i gruppens sammansättning"
                )

            print(f"\nHändelse: {event_by_id[id_a]}")
            print(f"A: {article_a.get('title')}")
            print(f"B: {article_b.get('title')}")
            print(f"Cosinuslikhet: {similarity:.3f}")

            if gap is None:
                print("Datumskillnad: okänd")
            else:
                print(f"Datumskillnad: {gap:.2f} dagar")

            print(f"Källa A: {article_a.get('source')}")
            print(f"Källa B: {article_b.get('source')}")
            print(f"Möjlig förklaring: {'; '.join(reasons)}")

    if missed_count == 0:
        print("Inga missade positiva artikelpar vid denna tröskel.")

    print(f"\nTotalt antal missade positiva par: {missed_count}")


# --------------------------------------------------
# VISA GRUPPER
# --------------------------------------------------

def print_groups(groups):
    print("\nGRUPPER SOM HITTADEs")
    print("=" * 80)

    if not groups:
        print("Inga grupper hittades.")
        return

    for index, group in enumerate(groups, start=1):
        group_articles = group["articles"]

        print(
            f"\nGrupp {index} – "
            f"{len(group_articles)} artiklar, "
            f"{group['source_count']} källor, "
            f"sammanhållning {group['cohesion']:.3f}"
        )

        for article in group_articles:
            print(
                f"  - [{article.get('source', 'okänd källa')}] "
                f"{article.get('title')}"
            )


# --------------------------------------------------
# HUVUDPROGRAM
# --------------------------------------------------

def main():
    articles, event_by_id = prepare_test_data()

    if len(articles) < 2:
        print("\nFör få artiklar för utvärdering.")
        return

    print("\nLaddar modellen och beräknar embeddings...")

    model = SentenceTransformer(MODEL_NAME)

    # Samma textrepresentation som i produktionsmodulen:
    # titel + beskrivning när beskrivning finns.
    embeddings = model.encode(
        [
            grouping.article_text(article)
            for article in articles
        ],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    # Diagnostik innan själva grupperingstestet.
    print_threshold_diagnostics(articles, embeddings)

    original_threshold = grouping.SIMILARITY_THRESHOLD

    results = {}
    groups_by_threshold = {}

    try:
        print("\n" + "=" * 80)
        print("JÄMFÖRELSE AV TRÖSKELVÄRDEN")
        print("=" * 80)

        print(
            "Tröskel   TP   FP   FN   TN   "
            "Precision  Recall  F1"
        )
        print("-" * 65)

        for threshold in THRESHOLDS_TO_TEST:
            grouping.SIMILARITY_THRESHOLD = threshold

            print(
                f"\nKör gruppering med tröskel {threshold:.2f}..."
            )

            groups = grouping.build_groups(
                articles,
                embeddings,
            )

            metrics = evaluate_groups(
                articles,
                groups,
                event_by_id,
            )

            results[threshold] = metrics
            groups_by_threshold[threshold] = groups

            print_metrics(threshold, metrics)

        if BASELINE_THRESHOLD not in results:
            raise ValueError(
                "Baslinjetröskeln måste finnas i "
                "THRESHOLDS_TO_TEST."
            )

        baseline_groups = groups_by_threshold[BASELINE_THRESHOLD]
        baseline_metrics = results[BASELINE_THRESHOLD]

        print_groups(baseline_groups)

        print_missed_pairs(
            articles,
            embeddings,
            event_by_id,
            baseline_metrics,
            BASELINE_THRESHOLD,
        )

        # Sammanfattning
        print("\n" + "=" * 80)
        print("SAMMANFATTNING")
        print("=" * 80)

        best_f1 = max(
            metrics["f1"]
            for metrics in results.values()
        )

        best_thresholds = [
            threshold
            for threshold, metrics in results.items()
            if np.isclose(metrics["f1"], best_f1)
        ]

        print(f"Högsta F1 i testet: {best_f1:.3f}")

        print(
            "Trösklar med högsta F1: "
            + ", ".join(
                f"{threshold:.2f}"
                for threshold in best_thresholds
            )
        )

        for threshold in best_thresholds:
            metrics = results[threshold]

            print(
                f"Tröskel {threshold:.2f} — "
                f"Precision: {metrics['precision']:.3f}, "
                f"Recall: {metrics['recall']:.3f}, "
                f"F1: {metrics['f1']:.3f}"
            )

        print(
            "\nObservera: resultatet gäller bara det manuellt "
            "märkta testurvalet. Det bevisar inte att samma "
            "tröskel är bäst för alla nyhetsartiklar."
        )

    finally:
        # Återställ tröskeln även om testet avbryts med ett fel.
        grouping.SIMILARITY_THRESHOLD = original_threshold


if __name__ == "__main__":
    main()