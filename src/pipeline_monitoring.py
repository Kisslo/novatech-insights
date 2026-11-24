"""Shared start and finish helpers for public.pipeline_runs."""

import json
import uuid
from datetime import datetime, timezone
from urllib.request import Request

SUPPORTED_STAGES = (
    "collection",
    "upload",
    "grouping",
    "ranking",
    "labeling",
    "draft_generation",
    "telegram",
)
SUPPORTED_MODES = ("read_only", "write")
SUPPORTED_STATUSES = ("running", "success", "partial", "failed", "no_data")


class PipelineMonitoringError(RuntimeError):
    """Raised when a pipeline run cannot be confirmed in Supabase."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_uuid(value, *, field_name):
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as error:
        raise PipelineMonitoringError(
            f"Invalid {field_name}: {value!r} is not a UUID."
        ) from error


def create_run_identity(correlation_id=None, *, run_id=None):
    normalized_run_id = normalize_uuid(run_id, field_name="run_id")
    normalized_correlation_id = normalize_uuid(
        correlation_id, field_name="correlation_id"
    )
    if normalized_run_id is None:
        normalized_run_id = str(uuid.uuid4())
    if normalized_correlation_id is None:
        normalized_correlation_id = str(uuid.uuid4())
    return normalized_run_id, normalized_correlation_id


def build_supabase_headers(key, *, method="GET"):
    headers = {"apikey": key, "Content-Type": "application/json"}
    if method in {"POST", "PATCH"}:
        headers["Prefer"] = "return=representation"
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def build_supabase_request(url, key, *, method="GET", payload=None):
    return Request(
        url,
        headers=build_supabase_headers(key, method=method),
        method=method,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
    )


def create_pipeline_run(
    request_json,
    *,
    url,
    key,
    stage,
    mode,
    correlation_id=None,
    run_id=None,
    started_at=None,
    metrics=None,
    details=None,
):
    if stage not in SUPPORTED_STAGES:
        raise PipelineMonitoringError(f"Unsupported pipeline stage: {stage}")
    if mode not in SUPPORTED_MODES:
        raise PipelineMonitoringError(f"Unsupported pipeline mode: {mode}")

    run_id, normalized_correlation_id = create_run_identity(
        correlation_id, run_id=run_id
    )
    started_at = started_at or utc_now()

    payload = {
        "run_id": run_id,
        "correlation_id": normalized_correlation_id,
        "stage": stage,
        "mode": mode,
        "status": "running",
        "started_at": started_at,
        "finished_at": None,
        "metrics": metrics if metrics is not None else {},
        "details": details if details is not None else {},
    }
    try:
        response = request_json(
            f"{url}/rest/v1/pipeline_runs",
            key,
            method="POST",
            payload=payload,
        )
    except Exception as error:
        raise PipelineMonitoringError(
            f"Could not create {stage} run {run_id}: {error}"
        ) from error

    if (
        not isinstance(response, list)
        or len(response) != 1
        or not isinstance(response[0], dict)
        or response[0].get("run_id") != run_id
    ):
        raise PipelineMonitoringError(
            f"Supabase did not confirm creation of {stage} run {run_id}."
        )
    return {
        "run_id": run_id,
        "correlation_id": normalized_correlation_id,
        "started_at": started_at,
    }


def finish_pipeline_run(
    request_json,
    *,
    url,
    key,
    run_id,
    status,
    stage="pipeline",
    finished_at=None,
    metrics=None,
    details=None,
):
    if status not in SUPPORTED_STATUSES or status == "running":
        raise PipelineMonitoringError(f"Unsupported pipeline status: {status}")
    run_id = normalize_uuid(run_id, field_name="run_id")
    payload = {
        "status": status,
        "finished_at": finished_at or utc_now(),
    }
    if metrics is not None:
        payload["metrics"] = metrics
    if details is not None:
        payload["details"] = details

    try:
        response = request_json(
            f"{url}/rest/v1/pipeline_runs?run_id=eq.{run_id}&status=eq.running&select=run_id",
            key,
            method="PATCH",
            payload=payload,
        )
    except Exception as error:
        raise PipelineMonitoringError(
            f"Could not finish {stage} run {run_id}: {error}"
        ) from error

    if (
        not isinstance(response, list)
        or len(response) != 1
        or not isinstance(response[0], dict)
        or response[0].get("run_id") != run_id
    ):
        raise PipelineMonitoringError(
            f"Supabase did not confirm completion of {stage} run {run_id}."
        )
    return payload
