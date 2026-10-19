
from SRC.group_topics import classify_topic


def test_ai_article():
    result = classify_topic(
        "New artificial intelligence model released"
    )
    assert result == "AI and LLMs"


def test_frontier_model_article():
    result = classify_topic(
        "Meta releases a new frontier model"
    )
    assert result == "AI and LLMs"


def test_ai_agents_article():
    result = classify_topic(
        "Introducing n8n agents"
    )
    assert result == "AI agents and assistants"


def test_ai_automation_article():
    result = classify_topic(
        "Build a morning AI news brief with You.com, Jev, n8n"
    )
    assert result == "AI automation and workflows"


def test_cybersecurity_article():
    result = classify_topic(
        "Major cybersecurity breach reported"
    )
    assert result == "Cybersecurity"


def test_devops_article():
    result = classify_topic(
        "11 Best DevOps Automation Tools for Engineering Teams"
    )
    assert result == "Cloud and DevOps"


def test_api_article():
    result = classify_topic(
        "How API Contract Testing Prevents Production Failures"
    )
    assert result == "Software and APIs"


def test_priority_when_multiple_topics_match():
    result = classify_topic(
        "AI agents expose a major cybersecurity vulnerability"
    )
    assert result == "Cybersecurity"


def test_unknown_article():
    result = classify_topic(
        "Local bakery opens a new shop"
    )
    assert result == "Other"


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
