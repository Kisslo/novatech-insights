import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
THRESHOLD = 0.75

group26 = [
    (
        "BleepingComputer",
        "PHP ships emergency patches for critical PHP2Shell flaws",
        "Emergency patches for CVE-2026-109618 and CVE-2026-109619, "
        "two critical remote code execution vulnerabilities tracked as PHP2Shell.",
    ),
    (
        "The Hacker News",
        "PHP Issues Emergency Patches for Two Critical PHP2Shell RCE Flaws as Exploit Attempts Emerge",
        "Emergency updates fix two critical PHP runtime flaws. "
        "Unauthenticated attackers can run code on a web server. "
        "The vulnerabilities are called PHP2Shell.",
    ),
    (
        "Help Net Security",
        "PHP2Shell: Critical PHP vulnerabilities patched, update now!",
        "Emergency security updates fix PHP2Shell, CVE-2026-109618 "
        "and CVE-2026-109619, allowing remote code execution without login.",
    ),
    (
        "Schneier on Security",
        "New Serious PHP Vulnerabilities Released and Patched",
        "PHP maintainers patched two critical vulnerabilities allowing "
        "unauthenticated remote code execution. All PHP users are urged to update.",
    ),
    (
        "SiliconANGLE",
        "Critical PHP vulnerabilities send organizations scrambling to secure their systems",
        "PHP patches two critical vulnerabilities affecting many websites. "
        "Organizations are urged to secure affected systems.",
    ),
    (
        "SecurityWeek",
        "PHP2Shell: Mass Exploitation Looms for Leaked Critical PHP Flaws",
        "CVE-2026-109618 and CVE-2026-109619 could lead to "
        "unauthenticated remote code execution.",
    ),
]

group30 = [
    (
        "WIRED",
        "'This Is Not a Drill': Critical PHP Vulnerabilities Are Setting the Internet on Fire",
        "Critical PHP vulnerabilities are putting websites at risk.",
    ),
    (
        "Computer Weekly",
        "What to do as critical PHP flaws puts millions of websites at risk",
        "Guidance about critical PHP vulnerabilities and protecting websites.",
    ),
    (
        "Krebs on Security",
        "Widespread PHP Flaw May Cause Many Site Outages Today",
        "Widespread PHP security flaws may cause website outages.",
    ),
    (
        "Tech Xplore",
        "A critical flaw affecting 70% of all websites has the cybersecurity world panicked",
        "A critical PHP flaw affects many websites and has caused security concerns.",
    ),
]


def main():
    model = SentenceTransformer(MODEL_NAME)

    articles = group26 + group30
    texts = [f"{title}. {description}" for _, title, description in articles]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    similarities = embeddings @ embeddings.T
    split = len(group26)
    cross = similarities[:split, split:]

    print("\nJÄMFÖRELSE: GRUPP 26 MOT GRUPP 30")
    print(f"Gränsvärde: {THRESHOLD:.2f}")
    print(f"Artikelpar över gränsen: {np.sum(cross >= THRESHOLD)} av {cross.size}")
    print(f"Lägsta korslikhet: {cross.min():.3f}")
    print(f"Högsta korslikhet: {cross.max():.3f}")
    print(f"Medel korslikhet: {cross.mean():.3f}")

    print("\nAlla korspar, högst likhet först:")
    pairs = []
    for i, article_a in enumerate(group26):
        for j, article_b in enumerate(group30):
            pairs.append(
                (
                    float(cross[i, j]),
                    article_a,
                    article_b,
                )
            )

    for score, a, b in sorted(pairs, key=lambda item: item[0], reverse=True):
        marker = "ÖVER" if score >= THRESHOLD else "UNDER"
        print(f"\n{score:.3f} [{marker}]")
        print(f"  Grupp 26: {a[0]} — {a[1]}")
        print(f"  Grupp 30: {b[0]} — {b[1]}")

    print(
        "\nOBS: Beskrivningarna är rekonstruerade från rapportutdraget. "
        "Resultatet är preliminärt och bevisar inte om den riktiga "
        "grupperingsalgoritmen skulle slå ihop grupperna."
    )


if __name__ == "__main__":
    main()
