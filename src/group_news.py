import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

FETCH_PAGE_SIZE = 500
BATCH_SIZE = 64

SIMILARITY_THRESHOLD = 0.75
MAX_DAYS_APART = 7
TOP_GROUPS = 20
MAX_ARTICLES_PER_GROUP = 5

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def fetch_articles():
    """Hämta artiklar från public.news utan att ändra databasen."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL eller SUPABASE_KEY saknas i .env")

    articles = []
    offset = 0

    while True:
        request = Request(
            f"{SUPABASE_URL}/rest/v1/news"
            f"?select=id,title,link,source,published,description"
            f"&order=id.asc&limit={FETCH_PAGE_SIZE}&offset={offset}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            method="GET",
        )

        with urlopen(request, timeout=60) as response:
            batch = json.loads(response.read().decode("utf-8"))

        if not batch:
            break

        articles.extend(batch)
        print(f"Hämtade {len(articles)} artiklar...")

        if len(batch) < FETCH_PAGE_SIZE:
            break

        offset += FETCH_PAGE_SIZE

    return articles


def normalize_url(url):
    """Ta bort vanliga spårningsparametrar från URL:er."""
    if not url:
        return ""

    url = url.strip()

    try:
        parts = urlsplit(url)
        scheme = parts.scheme.casefold() or "https"
        hostname = (parts.hostname or "").casefold()

        if not hostname:
            return url.rstrip("/")

        if hostname.startswith("www."):
            hostname = hostname[4:]

        if parts.port:
            hostname = f"{hostname}:{parts.port}"

        path = re.sub(r"/+", "/", parts.path).rstrip("/")

        query_items = []

        for key, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        ):
            key_lower = key.casefold()

            if key_lower.startswith("utm_"):
                continue

            if key_lower in TRACKING_PARAMS:
                continue

            query_items.append((key, value))

        query_items.sort()

        return urlunsplit(
            (
                scheme,
                hostname,
                path,
                urlencode(query_items, doseq=True),
                "",
            )
        )

    except ValueError, TypeError:
        return url


def normalize_title(title):
    return " ".join((title or "").casefold().split())


def deduplicate_articles(articles):
    """Ta bort URL-dubbletter i minnet, utan att ändra databasen."""
    unique_articles = {}
    duplicate_count = 0

    for article in articles:
        title = (article.get("title") or "").strip()

        if not title:
            continue

        normalized_link = normalize_url(article.get("link"))
        source = (article.get("source") or "").strip().casefold()
        normalized = normalize_title(title)

        if normalized_link:
            key = ("url", normalized_link)
        else:
            key = ("source_title", source, normalized)

        existing = unique_articles.get(key)

        if existing is None:
            unique_articles[key] = article
            continue

        duplicate_count += 1

        existing_length = len(
            (existing.get("title") or "") + (existing.get("description") or "")
        )
        new_length = len(
            (article.get("title") or "") + (article.get("description") or "")
        )

        if new_length > existing_length:
            unique_articles[key] = article

    result = list(unique_articles.values())

    print(f"Artiklar före lokal deduplicering: {len(articles)}")
    print(f"Dubbletter som hoppades över: {duplicate_count}")
    print(f"Unika artiklar efter deduplicering: {len(result)}")

    return result


def article_text(article):
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()

    if description:
        return f"{title}. {description}"

    return title


def parse_published(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed
    except ValueError, TypeError:
        return None


def clusters_within_date_window(indices_a, indices_b, dates):
    """
    Kontrollera tidsavståndet mellan samtliga artiklar i två grupper.
    Om ett datum saknas ignoreras just det datumet.
    """
    valid_dates = [
        dates[index] for index in indices_a + indices_b if dates[index] is not None
    ]

    if len(valid_dates) < 2:
        return True

    return (
        max(valid_dates) - min(valid_dates)
    ).total_seconds() <= MAX_DAYS_APART * 24 * 60 * 60


def build_groups(articles, embeddings):
    """
    Skapa grupper med constrained complete-link clustering.

    Två grupper slås bara ihop om alla korsvisa artikelpar uppfyller
    likhetströskeln och gruppen håller sig inom tidsfönstret.
    """
    total = len(articles)

    if total < 2:
        return []

    print("Beräknar likheter mellan alla artiklar...")

    # Embeddingarna är normaliserade, så cosinuslikhet kan beräknas
    # direkt genom matrisprodukten.
    similarity_matrix = np.asarray(
        embeddings @ embeddings.T,
        dtype=np.float32,
    )
    np.clip(similarity_matrix, -1.0, 1.0, out=similarity_matrix)

    dates = [parse_published(article.get("published")) for article in articles]
    titles = [normalize_title(article.get("title")) for article in articles]

    # Skapa kandidatpar över tröskeln. Bearbeta de starkaste likheterna
    # först, vilket ger mer stabila startgrupper.
    upper_i, upper_j = np.triu_indices(total, k=1)
    candidate_mask = similarity_matrix[upper_i, upper_j] >= SIMILARITY_THRESHOLD

    candidate_i = upper_i[candidate_mask]
    candidate_j = upper_j[candidate_mask]
    candidate_scores = similarity_matrix[
        candidate_i,
        candidate_j,
    ]

    order = np.argsort(candidate_scores)[::-1]
    candidate_i = candidate_i[order]
    candidate_j = candidate_j[order]
    candidate_scores = candidate_scores[order]

    print(f"Artikelpar över tröskeln: {len(candidate_i)}")
    print("Bygger grupper utan svaga länkar mellan grupper...")

    parent = list(range(total))
    members = {index: [index] for index in range(total)}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]

        return item

    merged_count = 0

    for a, b, score in zip(
        candidate_i,
        candidate_j,
        candidate_scores,
    ):
        a = int(a)
        b = int(b)

        root_a = find(a)
        root_b = find(b)

        if root_a == root_b:
            continue

        group_a = members[root_a]
        group_b = members[root_b]

        # Samma normaliserade rubrik skapar inte i sig en grupplänk.
        # Dubbletter av URL:er har redan filtrerats bort.
        if titles[a] == titles[b]:
            continue

        if not clusters_within_date_window(group_a, group_b, dates):
            continue

        # Complete-link-kontroll:
        # Varje artikel i A måste likna varje artikel i B tillräckligt.
        cross_scores = similarity_matrix[np.ix_(group_a, group_b)]

        if float(cross_scores.min()) < SIMILARITY_THRESHOLD:
            continue

        # Slå ihop de två grupperna.
        # Den mindre gruppen flyttas in i den större för att minska kopiering.
        if len(group_a) < len(group_b):
            root_a, root_b = root_b, root_a
            group_a, group_b = group_b, group_a

        parent[root_b] = root_a
        members[root_a] = group_a + group_b
        del members[root_b]

        merged_count += 1

    print(f"Godkända sammanslagningar: {merged_count}")

    groups = []

    for indices in members.values():
        if len(indices) < 2:
            continue

        group_articles = [articles[index] for index in indices]

        sources = {
            (article.get("source") or "").strip().casefold()
            for article in group_articles
            if (article.get("source") or "").strip()
        }

        if len(sources) < 2:
            continue

        group_similarities = similarity_matrix[np.ix_(indices, indices)]
        upper = group_similarities[np.triu_indices(len(indices), k=1)]

        cohesion = float(upper.mean())

        # Representanten är den artikel som i genomsnitt liknar
        # de övriga artiklarna mest.
        average_similarity = (group_similarities.sum(axis=1) - 1.0) / (len(indices) - 1)

        representative_local_index = int(np.argmax(average_similarity))
        representative_index = indices[representative_local_index]

        valid_dates = [dates[index] for index in indices if dates[index] is not None]

        groups.append(
            {
                "articles": group_articles,
                "source_count": len(sources),
                "article_count": len(group_articles),
                "cohesion": cohesion,
                "representative": articles[representative_index],
                "latest_published": (max(valid_dates) if valid_dates else None),
            }
        )

    groups.sort(
        key=lambda group: (
            group["source_count"],
            group["cohesion"],
            group["article_count"],
            group["latest_published"] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    return groups


def print_groups(groups):
    print("\nNYHETSGRUPPER")
    print("=" * 80)

    if not groups:
        print("Inga grupper hittades. Vi kan behöva utvärdera likhetströskeln.")
        return

    for number, group in enumerate(groups[:TOP_GROUPS], start=1):
        representative = group["representative"]

        sources = sorted(
            {
                (article.get("source") or "Okänd källa").strip()
                for article in group["articles"]
            }
        )

        print(f"\nGRUPP {number}")
        print(f"Representativ rubrik: {representative.get('title')}")
        print(f"Artiklar: {group['article_count']}")
        print(f"Unika källor: {group['source_count']}")
        print(f"Sammanhållning: {group['cohesion']:.3f}")
        print(f"Källor: {', '.join(sources)}")
        print("Artiklar:")

        sorted_members = sorted(
            group["articles"],
            key=lambda article: (
                parse_published(article.get("published"))
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )

        for article in sorted_members[:MAX_ARTICLES_PER_GROUP]:
            source = article.get("source") or "Okänd källa"
            title = article.get("title") or "(Rubrik saknas)"

            print(f"  - [{source}] {title}")

            link = article.get("link")
            if link:
                print(f"    {link}")

        if len(sorted_members) > MAX_ARTICLES_PER_GROUP:
            remaining = len(sorted_members) - MAX_ARTICLES_PER_GROUP
            print(f"  ... och {remaining} ytterligare artiklar")

        print("-" * 80)


def main():
    articles = fetch_articles()
    print(f"\nArtiklar hämtade från databasen: {len(articles)}")

    articles = deduplicate_articles(articles)

    if len(articles) < 2:
        print(f"För få unika artiklar: {len(articles)}")
        return

    print(f"\nAntal artiklar att analysera: {len(articles)}")
    print(f"Embedding-modell: {MODEL_NAME}")
    print(f"Likhetströskel: {SIMILARITY_THRESHOLD}")
    print(f"Max tidsskillnad mellan en grupps artiklar: {MAX_DAYS_APART} dagar")

    model = SentenceTransformer(MODEL_NAME)

    texts = [article_text(article) for article in articles]

    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    print(f"Embedding-matrisens form: {embeddings.shape}")

    groups = build_groups(articles, embeddings)

    print(f"\nAntal grupper med minst två källor: {len(groups)}")
    print_groups(groups)


if __name__ == "__main__":
    main()
