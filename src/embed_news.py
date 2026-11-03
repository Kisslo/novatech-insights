import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BATCH_SIZE = 64
TOP_PAIRS = 20
FETCH_PAGE_SIZE = 500
SIMILARITY_BLOCK_SIZE = 100


def fetch_articles():
    """Read articles from public.news without modifying the database."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL or SUPABASE_KEY is missing in .env")

    articles = []
    offset = 0

    while True:
        request = Request(
            f"{SUPABASE_URL}/rest/v1/news"
            f"?select=id,title,source,published,description"
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


def article_text(article):
    """Combine the title and description into embedding input text."""
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()

    if description:
        return f"{title}. {description}"

    return title


def normalize_title(title):
    """Normalize titles for exact-duplicate filtering."""
    return " ".join((title or "").casefold().split())


def find_similar_pairs(articles, embeddings):
    """Find the most similar pairs from different sources."""
    total = len(articles)
    top_pairs = []

    normalized_titles = [normalize_title(article.get("title")) for article in articles]
    normalized_sources = [
        (article.get("source") or "").strip().casefold() for article in articles
    ]

    for start in range(0, total, SIMILARITY_BLOCK_SIZE):
        end = min(start + SIMILARITY_BLOCK_SIZE, total)

        scores = cosine_similarity(
            embeddings[start:end],
            embeddings,
        )

        for local_i, row in enumerate(scores):
            i = start + local_i

            # Only consider each pair once.
            for j in range(i + 1, total):
                # Ignore exact duplicate titles.
                if normalized_titles[i] == normalized_titles[j]:
                    continue

                # Require different news sources.
                if normalized_sources[i] == normalized_sources[j]:
                    continue

                score = float(row[j])
                top_pairs.append((score, i, j))

    top_pairs.sort(key=lambda item: item[0], reverse=True)
    return top_pairs[:TOP_PAIRS]


def main():
    articles = fetch_articles()

    articles = [article for article in articles if (article.get("title") or "").strip()]

    if len(articles) < 2:
        print(f"För få artiklar för att jämföra: {len(articles)}")
        return

    texts = [article_text(article) for article in articles]

    print(f"\nAntal artiklar: {len(articles)}")
    print(f"Laddar embedding-modellen: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)

    print(f"Skapar embeddings för {len(texts)} artiklar...")
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    print(f"Embedding-matrisens form: {embeddings.shape}")
    print("\nLetar efter liknande artiklar från olika källor...")

    top_pairs = find_similar_pairs(articles, embeddings)

    print("\nMEST LIKA ARTIKELPAR FRÅN OLIKA KÄLLOR")
    print("=" * 80)

    if not top_pairs:
        print("Inga matchande artikelpar hittades.")
        return

    for score, i, j in top_pairs:
        a = articles[i]
        b = articles[j]

        print(f"\nLikhet: {score:.4f}")
        print(f"A: [{a.get('source')}] {a.get('title')}")
        print(f"B: [{b.get('source')}] {b.get('title')}")
        print(f"Publicerade: {a.get('published')} | {b.get('published')}")
        print("-" * 80)


if __name__ == "__main__":
    main()
