
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

articles = [
    {
        "id": 3364,
        "source": "TechCrunch",
        "title": "1Password launches a way for AI agents to log in without seeing your password",
        "description": "The feature protects private credentials when AI agents log into accounts.",
    },
    {
        "id": 3310,
        "source": "SiliconANGLE",
        "title": "1Password for Agents lets personal AI agents log in without ever seeing the password",
        "description": "1Password launched a secure sign-in platform for personal AI agents.",
    },
    {
        "id": 3189,
        "source": "n8n Blog",
        "title": "AI Agent Memory: How LLM Agents Manage State in Production",
        "description": "Learn how AI agent memory works and how workflows retain context.",
    },
    {
        "id": 3521,
        "source": "Unite.AI",
        "title": "What Is the EU AI Act? A Practical Guide to General-Purpose AI Rules",
        "description": "A guide to the risk-based legal framework and obligations for AI providers.",
    },
]

texts = [
    f"{article['title']}. {article['description']}"
    for article in articles
]

embeddings = model.encode(texts, normalize_embeddings=True)
similarities = cosine_similarity(embeddings)

# Visa de mest lika artikelparen
pairs = []

for i in range(len(articles)):
    for j in range(i + 1, len(articles)):
        pairs.append(
            (
                similarities[i, j],
                articles[i],
                articles[j],
            )
        )

pairs.sort(key=lambda item: item[0], reverse=True)

print("\nMEST LIKA ARTIKELPAR:\n")

for score, article_a, article_b in pairs:
    print(f"Likhet: {score:.4f}")
    print(f"A: [{article_a['source']}] {article_a['title']}")
    print(f"B: [{article_b['source']}] {article_b['title']}")
    print("-" * 80)
