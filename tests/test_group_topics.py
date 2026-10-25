import csv
import sys

from src import group_topics
from src.group_topics import classify_topic


def test_ai_article():
    result = classify_topic("New artificial intelligence model released")
    assert result == "AI and LLMs"


def test_frontier_model_article():
    result = classify_topic("Meta releases a new frontier model")
    assert result == "AI and LLMs"


def test_ai_agents_article():
    result = classify_topic("Introducing n8n agents")
    assert result == "AI agents and assistants"


def test_ai_automation_article():
    result = classify_topic("Build a morning AI news brief with You.com, Jev, n8n")
    assert result == "AI automation and workflows"


def test_cybersecurity_article():
    result = classify_topic("Major cybersecurity breach reported")
    assert result == "Cybersecurity"


def test_devops_article():
    result = classify_topic("11 Best DevOps Automation Tools for Engineering Teams")
    assert result == "Cloud and DevOps"


def test_api_article():
    result = classify_topic("How API Contract Testing Prevents Production Failures")
    assert result == "Software and APIs"


def test_api_does_not_match_inside_capital():
    assert classify_topic("The capital city expands") == "Other"


def test_api_does_not_match_inside_therapist():
    assert classify_topic("Japan's therapist shortage") == "Other"


def test_venture_capital_gets_funding_topic():
    assert (
        classify_topic("Venture capital firm backs rapid growth")
        == "Startups and funding"
    )


def test_facebook_shares_new_feature():
    assert classify_topic("Facebook shares new feature") == "Other"


def test_swedish_borsen_keyword():
    assert classify_topic("Börsen stiger efter ny rapport") == "Business and Finance"


def test_generic_bolag_does_not_match_finance():
    assert classify_topic("Ett bolag lanserar en ny tjänst") == "Other"


def test_generic_foretag_does_not_match_finance():
    assert classify_topic("Ett företag öppnar ett nytt kontor") == "Other"


def test_priority_when_multiple_topics_match():
    result = classify_topic("AI agents expose a major cybersecurity vulnerability")
    assert result == "Cybersecurity"


def test_unknown_article():
    result = classify_topic("Local bakery opens a new shop")
    assert result == "Other"


def test_main_preserves_existing_subject_and_classifies_empty_subject(
    tmp_path, monkeypatch
):
    input_file = tmp_path / "news.csv"
    output_file = tmp_path / "news_with_topics.csv"

    fieldnames = [
        "title",
        "link",
        "source",
        "published",
        "subject",
        "description",
    ]

    articles = [
        {
            "title": "Local bakery opens a new shop",
            "link": "https://example.com/1",
            "source": "Example",
            "published": "2026-10-20T12:00:00Z",
            "subject": "Cybersecurity",
            "description": "",
        },
        {
            "title": "Major cybersecurity breach reported",
            "link": "https://example.com/2",
            "source": "Example",
            "published": "2026-10-21T12:00:00Z",
            "subject": "",
            "description": "",
        },
    ]

    with input_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(articles)

    monkeypatch.setattr(group_topics, "INPUT_FILE", input_file)
    monkeypatch.setattr(group_topics, "OUTPUT_FILE", output_file)
    monkeypatch.setattr(sys, "argv", ["group_topics.py"])

    group_topics.main()

    with output_file.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        result = list(reader)
        assert reader.fieldnames == fieldnames

    assert result[0]["subject"] == "Cybersecurity"
    assert result[1]["subject"] == "Cybersecurity"
    assert result[1]["description"] == ""


def test_main_reclassify_overwrites_existing_subject(tmp_path, monkeypatch):
    input_file = tmp_path / "news.csv"
    output_file = tmp_path / "news_with_topics.csv"

    fieldnames = [
        "title",
        "link",
        "source",
        "published",
        "subject",
        "description",
    ]

    with input_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "title": "Local bakery opens a new shop",
                "link": "https://example.com/1",
                "source": "Example",
                "published": "2026-10-20T12:00:00Z",
                "subject": "Cybersecurity",
                "description": "",
            }
        )

    monkeypatch.setattr(group_topics, "INPUT_FILE", input_file)
    monkeypatch.setattr(group_topics, "OUTPUT_FILE", output_file)
    monkeypatch.setattr(
        sys,
        "argv",
        ["group_topics.py", "--reclassify"],
    )

    group_topics.main()

    with output_file.open("r", encoding="utf-8-sig", newline="") as file:
        result = list(csv.DictReader(file))

    assert result[0]["subject"] == "Other"


def test_main_supports_legacy_csv_without_description(tmp_path, monkeypatch):
    input_file = tmp_path / "news.csv"
    output_file = tmp_path / "news_with_topics.csv"

    fieldnames = ["title", "link", "source", "published", "subject"]

    with input_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "title": "Local bakery opens a new shop",
                "link": "https://example.com/legacy",
                "source": "Example",
                "published": "2026-10-20T12:00:00Z",
                "subject": "",
            }
        )

    monkeypatch.setattr(group_topics, "INPUT_FILE", input_file)
    monkeypatch.setattr(group_topics, "OUTPUT_FILE", output_file)
    monkeypatch.setattr(sys, "argv", ["group_topics.py"])

    group_topics.main()

    with output_file.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        result = list(reader)

        assert reader.fieldnames == fieldnames + ["description"]

    assert len(result) == 1
    assert result[0]["link"] == "https://example.com/legacy"
    assert result[0]["subject"] == "Other"
    assert result[0]["description"] == ""


if __name__ == "__main__":
    test_ai_article()
    test_frontier_model_article()
    test_ai_agents_article()
    test_ai_automation_article()
    test_cybersecurity_article()
    test_devops_article()
    test_api_article()
    test_priority_when_multiple_topics_match()
    test_unknown_article()
    print("All topic classification tests passed!")
