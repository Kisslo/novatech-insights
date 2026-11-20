from datetime import datetime, timezone

import pytest

import pipeline_monitoring as monitoring

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def test_create_run_identity_uses_two_separate_uuid_calls():
    run_id, correlation_id = monitoring.create_run_identity()

    assert run_id != correlation_id


def test_create_standalone_run_creates_separate_correlation_id():
    calls = []

    def request_json(url, key, *, method="GET", payload=None):
        calls.append((method, url, payload))
        return [{"run_id": payload["run_id"]}]

    result = monitoring.create_pipeline_run(
        request_json,
        url="https://example.test",
        key="secret",
        stage="ranking",
        mode="read_only",
        run_id="10000000-0000-0000-0000-000000000001",
        started_at=NOW.isoformat(),
        metrics={"topics_total": None},
        details={"run_error": None},
    )

    assert result["run_id"] == "10000000-0000-0000-0000-000000000001"
    assert result["correlation_id"] != result["run_id"]
    payload = calls[0][2]
    assert payload["correlation_id"] == result["correlation_id"]
    assert payload["status"] == "running"


def test_create_related_run_reuses_correlation_id():
    calls = []

    def request_json(url, key, *, method="GET", payload=None):
        calls.append((method, url, payload))
        return [{"run_id": payload["run_id"]}]

    result = monitoring.create_pipeline_run(
        request_json,
        url="https://example.test",
        key="secret",
        stage="ranking",
        mode="write",
        run_id="10000000-0000-0000-0000-000000000002",
        correlation_id="10000000-0000-0000-0000-000000000003",
    )

    assert result["run_id"] != result["correlation_id"]
    assert result["correlation_id"] == "10000000-0000-0000-0000-000000000003"
    assert calls[0][2]["correlation_id"] == result["correlation_id"]


@pytest.mark.parametrize("response", [[], [{"run_id": "wrong"}], [{}, {}]])
def test_create_requires_exact_confirmed_run_id(response):
    def request_json(url, key, *, method="GET", payload=None):
        return response

    with pytest.raises(monitoring.PipelineMonitoringError):
        monitoring.create_pipeline_run(
            request_json,
            url="https://example.test",
            key="secret",
            stage="ranking",
            mode="read_only",
            run_id="10000000-0000-0000-0000-000000000004",
        )


def test_create_reports_request_failure():
    def request_json(url, key, *, method="GET", payload=None):
        raise RuntimeError("connection failed")

    with pytest.raises(
        monitoring.PipelineMonitoringError, match="Could not create ranking run"
    ):
        monitoring.create_pipeline_run(
            request_json,
            url="https://example.test",
            key="secret",
            stage="ranking",
            mode="read_only",
            run_id="10000000-0000-0000-0000-000000000005",
        )


def test_finish_requires_exact_confirmed_run_id():
    calls = []

    def request_json(url, key, *, method="GET", payload=None):
        calls.append((method, url, payload))
        return [{"run_id": "10000000-0000-0000-0000-000000000006"}]

    result = monitoring.finish_pipeline_run(
        request_json,
        url="https://example.test",
        key="secret",
        run_id="10000000-0000-0000-0000-000000000006",
        stage="ranking",
        status="success",
        finished_at=NOW.isoformat(),
        metrics={"topics_total": 2},
        details={"calculation_errors": {}},
    )

    assert result["status"] == "success"
    assert calls[0][0] == "PATCH"


@pytest.mark.parametrize("response", [[], [{"run_id": "wrong"}], [{}, {}]])
def test_finish_requires_exact_confirmed_run_id_or_monitoring_error(response):
    def request_json(url, key, *, method="GET", payload=None):
        return response

    with pytest.raises(monitoring.PipelineMonitoringError):
        monitoring.finish_pipeline_run(
            request_json,
            url="https://example.test",
            key="secret",
            run_id="10000000-0000-0000-0000-000000000007",
            stage="ranking",
            status="failed",
        )


def test_finish_reports_request_failure():
    def request_json(url, key, *, method="GET", payload=None):
        raise RuntimeError("connection failed")

    with pytest.raises(
        monitoring.PipelineMonitoringError, match="Could not finish ranking run"
    ):
        monitoring.finish_pipeline_run(
            request_json,
            url="https://example.test",
            key="secret",
            run_id="10000000-0000-0000-0000-000000000008",
            stage="ranking",
            status="failed",
        )


def test_legacy_jwt_receives_apikey_and_bearer_headers():
    key = "eyJhbGciOiJIUzI1NiJ9.test.signature"
    request = monitoring.build_supabase_request(
        "https://example.test/rest/v1/pipeline_runs",
        key,
        method="POST",
        payload={"run_id": "10000000-0000-0000-0000-000000000009"},
    )

    assert request.get_header("Apikey") == key
    assert request.get_header("Authorization") == f"Bearer {key}"
    assert request.get_header("Prefer") == "return=representation"


def test_secret_key_receives_apikey_without_bearer():
    key = "sb_secret_test123"
    request = monitoring.build_supabase_request(
        "https://example.test/rest/v1/pipeline_runs",
        key,
        method="POST",
        payload={"run_id": "10000000-0000-0000-0000-000000000010"},
    )

    assert request.get_header("Apikey") == key
    assert not request.has_header("Authorization")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("run_id", "not-a-uuid"), ("correlation_id", "not-a-uuid")],
)
def test_invalid_uuid_is_a_monitoring_error(field_name, value):
    kwargs = {
        "run_id": "10000000-0000-0000-0000-000000000011",
        "correlation_id": None,
    }
    kwargs[field_name] = value

    with pytest.raises(monitoring.PipelineMonitoringError):
        monitoring.create_pipeline_run(
            lambda *args, **kwargs: [],
            url="https://example.test",
            key="secret",
            stage="ranking",
            mode="read_only",
            **kwargs,
        )
