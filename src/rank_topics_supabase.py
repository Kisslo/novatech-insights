"""Read, rank, and optionally update topics through Supabase REST."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv

if __package__:
    from .pipeline_monitoring import (
        PipelineMonitoringError,
        build_supabase_request,
        create_pipeline_run,
        finish_pipeline_run,
    )
    from .rank_topics import rank_topics
    from .ranking_config import load_ranking_config, validate_ranking_config
    from .source_normalization import normalize_source
else:
    from pipeline_monitoring import (
        PipelineMonitoringError,
        build_supabase_request,
        create_pipeline_run,
        finish_pipeline_run,
    )
    from rank_topics import rank_topics
    from ranking_config import load_ranking_config, validate_ranking_config
    from source_normalization import normalize_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE_SIZE = 500
RANKING_FIELDS = (
    "score",
    "score_calculated_at",
    "score_version",
    "score_breakdown",
)


class SupabaseReadError(RuntimeError):
    """Raised when the complete ranking input cannot be read."""


def request_json(url, key, *, method="GET", payload=None):
    request = build_supabase_request(url, key, method=method, payload=payload)
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise SupabaseReadError(f"Supabase request failed: {error}") from error


def fetch_all(url, key, table, select, *, order="id.asc"):
    """Fetch all rows; short pages are not assumed to be the final page."""
    rows = []
    offset = 0
    while True:
        query = urlencode(
            {
                "select": select,
                "order": order,
                "limit": PAGE_SIZE,
                "offset": offset,
            }
        )
        batch = request_json(f"{url}/rest/v1/{table}?{query}", key)
        if not isinstance(batch, list):
            raise SupabaseReadError(f"Supabase returned a non-list for {table}.")
        rows.extend(batch)
        if not batch:
            return rows
        offset += len(batch)


def read_input(url, key):
    topics = fetch_all(url, key, "topics", "id")
    links = fetch_all(
        url, key, "topic_articles", "topic_id,news_id", order="topic_id.asc,news_id.asc"
    )
    news = fetch_all(
        url,
        key,
        "news",
        "id,title,description,source,source_normalized,published,link",
    )
    registry = fetch_all(
        url,
        key,
        "source_registry",
        "source_normalized,source_type",
        order="source_normalized.asc",
    )

    topic_ids = set()
    for topic in topics:
        if not isinstance(topic, dict) or type(topic.get("id")) is not int:
            raise SupabaseReadError("Topics contain an invalid id.")
        if topic["id"] in topic_ids:
            raise SupabaseReadError("Topics contain duplicate ids.")
        topic_ids.add(topic["id"])

    article_by_id = {}
    warnings = []
    source_types = {}
    for source in registry:
        if not isinstance(source, dict):
            raise SupabaseReadError("Source registry contains an invalid row.")
        key = source.get("source_normalized")
        source_type = source.get("source_type")
        if not isinstance(key, str) or not key:
            raise SupabaseReadError(
                "Source registry contains an invalid source_normalized."
            )
        if source_type not in (None, "media", "authority"):
            raise SupabaseReadError(
                f"Source registry contains an invalid source_type for {key}."
            )
        if key in source_types:
            raise SupabaseReadError(
                f"Source registry contains duplicate source_normalized: {key}."
            )
        source_types[key] = source_type
    for article in news:
        if not isinstance(article, dict) or type(article.get("id")) is not int:
            raise SupabaseReadError("News contains an invalid id.")
        if article["id"] in article_by_id:
            raise SupabaseReadError("News contains duplicate ids.")
        calculated = normalize_source(article.get("source"))
        stored = article.get("source_normalized")
        if stored is not None and stored != calculated:
            raise SupabaseReadError(
                f"Stored source normalization differs for news_id={article['id']}."
            )
        if stored is None:
            warnings.append(
                f"news_id={article['id']} has no stored source normalization."
            )
        article_by_id[article["id"]] = article

    topic_articles = {topic_id: [] for topic_id in topic_ids}
    seen_links = set()
    for link in links:
        if not isinstance(link, dict) or type(link.get("topic_id")) is not int:
            raise SupabaseReadError("Topic links contain an invalid topic_id.")
        if type(link.get("news_id")) is not int:
            raise SupabaseReadError("Topic links contain an invalid news_id.")
        pair = (link["topic_id"], link["news_id"])
        if pair in seen_links:
            raise SupabaseReadError("Topic links contain duplicate memberships.")
        seen_links.add(pair)
        if link["topic_id"] not in topic_articles:
            raise SupabaseReadError("Topic links reference an unknown topic.")
        if link["news_id"] not in article_by_id:
            raise SupabaseReadError("Topic links reference an unknown article.")
        ranking_article = dict(article_by_id[link["news_id"]])
        normalized_source = ranking_article.get(
            "source_normalized"
        ) or normalize_source(ranking_article.get("source"))
        ranking_article["source"] = normalized_source
        ranking_article["source_type"] = source_types.get(normalized_source)
        topic_articles[link["topic_id"]].append(ranking_article)

    return [
        {"id": topic_id, "articles": [a for a in articles if a is not None]}
        for topic_id, articles in topic_articles.items()
    ], warnings


def update_topic(url, key, topic_id, values):
    query = urlencode(
        {"id": f"eq.{topic_id}", "select": "id," + ",".join(RANKING_FIELDS)}
    )
    response = request_json(
        f"{url}/rest/v1/topics?{query}", key, method="PATCH", payload=values
    )
    if (
        not isinstance(response, list)
        or len(response) != 1
        or not isinstance(response[0], dict)
        or response[0].get("id") != topic_id
    ):
        raise RuntimeError(f"Supabase did not confirm the update for topic {topic_id}.")


def calculate_run_status(
    *,
    mode,
    topics_total,
    calculated,
    skipped,
    calculation_errors,
    writes_confirmed,
    writes_failed,
    run_error,
    warnings=(),
):
    if run_error is not None:
        return "failed"
    if topics_total == 0:
        return "no_data"
    if mode == "read_only":
        if not calculated:
            return "failed" if calculation_errors else "no_data"
        return "success" if len(calculated) == topics_total else "partial"

    delivered = len(set(calculated) & set(writes_confirmed))
    has_technical_error = bool(calculation_errors or writes_failed)
    if delivered == 0:
        if len(skipped) == topics_total and not has_technical_error:
            return "no_data"
        return "failed"
    if (
        delivered == topics_total
        and len(calculated) == topics_total
        and not has_technical_error
    ):
        return "success"
    return "partial"


def build_pipeline_values(
    *,
    status,
    finished_at,
    topics_total,
    calculated,
    skipped,
    calculation_errors,
    write_errors,
    writes_confirmed,
    writes_failed,
    warnings,
    run_error,
    monitoring_error=None,
):
    return {
        "status": status,
        "finished_at": finished_at,
        "metrics": {
            "topics_total": topics_total,
            "topics_calculated": len(calculated),
            "topics_skipped": len(skipped),
            "calculation_errors": len(calculation_errors),
            "writes_confirmed": len(writes_confirmed),
            "writes_failed": len(writes_failed),
            "warning_count": len(warnings),
        },
        "details": {
            "calculation_errors": calculation_errors,
            "write_errors": write_errors,
            "skipped": skipped,
            "warnings": warnings,
            "run_error": run_error,
            "monitoring_error": monitoring_error,
        },
    }


def run_ranking(*, url, key, write=False, now=None, config=None, correlation_id=None):
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY are required.")
    url = url.rstrip("/")
    run_now = now or datetime.now(timezone.utc)
    mode = "write" if write else "read_only"
    run_identity = create_pipeline_run(
        request_json,
        url=url,
        key=key,
        stage="ranking",
        mode=mode,
        correlation_id=correlation_id,
        metrics={
            "topics_total": None,
            "topics_calculated": 0,
            "topics_skipped": 0,
            "calculation_errors": 0,
            "writes_confirmed": 0,
            "writes_failed": 0,
            "warning_count": 0,
        },
        details={
            "calculation_errors": {},
            "write_errors": {},
            "skipped": {},
            "warnings": [],
            "run_error": None,
            "monitoring_error": None,
        },
    )
    run_id = run_identity["run_id"]

    results = []
    errors = {}
    calculation_errors = {}
    write_errors = {}
    skipped = {}
    calculated = []
    write_results = {"requested": write, "confirmed": [], "failed": []}
    warnings = []
    topics_total = None
    run_error = None
    try:
        config = load_ranking_config() if config is None else config
        validate_ranking_config(config)
        topics, warnings = read_input(url, key)
        topics_total = len(topics)
    except (SupabaseReadError, OSError, TypeError, ValueError) as error:
        run_error = str(error)
        topics = []

    for topic in topics:
        try:
            ranked = rank_topics(
                [topic],
                run_now,
                config["source_weights"],
                config["swedish_sources"],
                max_breadth_bonus=config["max_breadth_bonus"],
                breadth_scale=config["breadth_scale"],
                max_velocity_bonus=config["max_velocity_bonus"],
                velocity_scale=config["velocity_scale"],
                swedish_weight=config["swedish_weight"],
                score_version=config["score_version"],
                half_life_days=config["half_life_days"],
                default_weight=config["default_source_weight"],
                previous_days=config["previous_days"],
                authority_base_factor=config["authority_base_factor"],
                authority_total_start_factor=config["authority_total_start_factor"],
                authority_bonus_half_life_days=config["authority_bonus_half_life_days"],
            )
        except (
            ArithmeticError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            errors[topic["id"]] = f"calculation failed: {error}"
            calculation_errors[str(topic["id"])] = str(error)
            continue
        if ranked:
            values = {field: ranked[0][field] for field in RANKING_FIELDS}
            calculated.append(topic["id"])
        else:
            values = dict.fromkeys(RANKING_FIELDS)
            skipped[topic["id"]] = "no valid articles; ranking fields will be cleared"
        results.append({"topic_id": topic["id"], "values": values})

    if write:
        for item in results:
            try:
                update_topic(url, key, item["topic_id"], item["values"])
            except RuntimeError as error:
                write_results["failed"].append(item["topic_id"])
                errors[item["topic_id"]] = f"write failed: {error}"
                write_errors[str(item["topic_id"])] = str(error)
            else:
                write_results["confirmed"].append(item["topic_id"])
    status = calculate_run_status(
        mode=mode,
        topics_total=topics_total,
        calculated=calculated,
        skipped=skipped,
        calculation_errors=calculation_errors,
        writes_confirmed=write_results["confirmed"],
        writes_failed=write_results["failed"],
        run_error=run_error,
    )
    result = {
        "run_id": run_id,
        "correlation_id": run_identity["correlation_id"],
        "status": status,
        "details": {
            "calculation_errors": calculation_errors,
            "write_errors": write_errors,
            "skipped": skipped,
            "warnings": warnings,
            "run_error": run_error,
        },
        "topics": results,
        "errors": errors,
        "skipped": skipped,
        "warnings": warnings,
        "calculated": calculated,
        "writes": write_results,
        "written": bool(write_results["confirmed"]),
    }
    pipeline_values = build_pipeline_values(
        status=status,
        finished_at=datetime.now(timezone.utc).isoformat(),
        topics_total=topics_total,
        calculated=calculated,
        skipped=skipped,
        calculation_errors=calculation_errors,
        write_errors=write_errors,
        writes_confirmed=write_results["confirmed"],
        writes_failed=write_results["failed"],
        warnings=warnings,
        run_error=run_error,
    )
    try:
        finish_pipeline_run(
            request_json,
            url=url,
            key=key,
            run_id=run_id,
            stage="ranking",
            status=pipeline_values["status"],
            finished_at=pipeline_values["finished_at"],
            metrics=pipeline_values["metrics"],
            details=pipeline_values["details"],
        )
    except PipelineMonitoringError as error:
        result["monitoring_error"] = str(error)
        print(f"Ranking monitoring error: {error}", file=sys.stderr)
    else:
        result["monitoring_error"] = None
    return result


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Rank topics using Supabase data. Run history is persisted for both "
            "read-only and write modes."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist ranking fields; omit to run without updating topics.",
    )
    args = parser.parse_args()
    load_dotenv(os.path.join(ROOT, ".env"))
    try:
        result = run_ranking(
            url=os.getenv("SUPABASE_URL", "").strip(),
            key=os.getenv("SUPABASE_KEY", "").strip(),
            write=args.write,
        )
    except PipelineMonitoringError as error:
        print(f"Ranking monitoring error: {error}", file=sys.stderr)
        return 1
    mode = "write requested" if args.write else "read-only"
    print(
        f"Finished in {mode} mode: {len(result['topics'])} topics "
        f"(run {result['run_id']}, status {result['status']})."
    )
    if not args.write:
        print("Read-only mode: topic ranking fields were not written.")
    print(
        f"Calculated: {len(result['calculated'])}; "
        f"skipped: {len(result['skipped'])}; "
        f"writes confirmed: {len(result['writes']['confirmed'])}; "
        f"writes failed: {len(result['writes']['failed'])}."
    )
    for warning in result["warnings"]:
        print(f"Warning: {warning}")
    for topic_id, reason in result["skipped"].items():
        print(f"Skipped topic {topic_id}: {reason}")
    for topic_id, error in result["errors"].items():
        print(f"Topic {topic_id}: {error}")
    if result["details"]["run_error"]:
        print(f"Ranking run error: {result['details']['run_error']}", file=sys.stderr)
    return (
        1
        if result["errors"]
        or result["monitoring_error"]
        or result["details"]["run_error"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
