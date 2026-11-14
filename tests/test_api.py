"""Tests for the FastAPI app: routes, limits, cache, degradation and privacy-safe logs."""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.requests import Request

from ga4_sql_analyst.api import AskHandler, _client_ip, app_factory, create_app
from ga4_sql_analyst.cache import ResponseCache
from ga4_sql_analyst.limits import StrictRateLimiter
from ga4_sql_analyst.models import AskRequest, AskResponse
from ga4_sql_analyst.offline import build_offline_service
from ga4_sql_analyst.scenarios import SCENARIOS
from ga4_sql_analyst.settings import Settings
from ga4_sql_analyst.snapshot import Snapshot, SnapshotEntry

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
MAX_BYTES = 400_000_000
QUESTION = SCENARIOS[0].question["pt"]
ORIGIN = "https://fgm9000.github.io"
LOGGER_NAME = "ga4_sql_analyst"
CLOCK_STEP = 0.25
DELETE_SQL = "DELETE FROM secret_table"
ANSWER = AskResponse(status="answered", summary="canned")
UNAVAILABLE = AskResponse(status="unavailable", reason="llm_unavailable")


class _CountingService:
    """Typed double: answers with a fixed response and counts the calls."""

    def __init__(self, response: AskResponse = ANSWER) -> None:
        self.calls = 0
        self._response = response

    async def ask(self, request: AskRequest) -> AskResponse:
        self.calls += 1
        return self._response


class _StepClock:
    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        self._now += CLOCK_STEP
        return self._now


def _limiter(rate: int = 100, daily: int = 1000, llm: int = 1000) -> StrictRateLimiter:
    return StrictRateLimiter(rate, daily, llm)


def _exhausted_limiter() -> StrictRateLimiter:
    limiter = _limiter(llm=1)
    assert limiter.try_consume_llm_call()
    return limiter


def _client(
    service: AskHandler | None = None,
    limiter: StrictRateLimiter | None = None,
    snapshot: Snapshot | None = None,
) -> TestClient:
    app = create_app(
        Settings(offline=False),
        service if service is not None else _CountingService(),
        limiter if limiter is not None else _limiter(),
        ResponseCache(),
        snapshot if snapshot is not None else Snapshot([]),
        _StepClock(),
    )
    return TestClient(app)


def _ask(client: TestClient, question: str = QUESTION, ip: str | None = None) -> Response:
    headers = {} if ip is None else {"X-Forwarded-For": ip}
    return client.post("/v1/ask", json={"question": question, "lang": "pt"}, headers=headers)


def test_root_redirects_to_docs() -> None:
    response = _client().get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health_routes(path: str) -> None:
    response = _client().get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_happy_path_with_offline_service() -> None:
    client = _client(service=build_offline_service(PARQUET, MAX_BYTES))
    response = _ask(client)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "answered"
    assert body["rows"]
    assert body["degraded"] is False


def test_ask_cache_hit_does_not_call_service_again() -> None:
    service = _CountingService()
    client = _client(service=service)
    first = _ask(client)
    second = _ask(client, f"  {QUESTION.upper()} ")
    assert first.json() == second.json()
    assert service.calls == 1


def test_ask_does_not_cache_unavailable_responses() -> None:
    service = _CountingService(UNAVAILABLE)
    client = _client(service=service)
    _ask(client)
    _ask(client)
    assert service.calls == 2


def test_ask_rate_limited_per_ip_returns_429_with_retry_after() -> None:
    client = _client(limiter=_limiter(rate=1))
    assert _ask(client).status_code == 200
    blocked = _ask(client)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "rate_limited"}
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60


def test_ask_daily_quota_returns_429() -> None:
    client = _client(limiter=_limiter(daily=1))
    assert _ask(client).status_code == 200
    blocked = _ask(client)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "daily_quota"}
    assert int(blocked.headers["Retry-After"]) >= 1


def test_ask_without_llm_quota_serves_snapshot_as_degraded() -> None:
    recorded = AskResponse(status="answered", summary="recorded")
    entry = SnapshotEntry(scenario=1, lang="pt", question=QUESTION, response=recorded)
    service = _CountingService()
    client = _client(service=service, limiter=_exhausted_limiter(), snapshot=Snapshot([entry]))
    response = _ask(client)
    assert response.status_code == 200
    assert response.json()["summary"] == "recorded"
    assert response.json()["degraded"] is True
    assert service.calls == 0


def test_ask_without_llm_quota_and_snapshot_returns_429() -> None:
    response = _ask(_client(limiter=_exhausted_limiter()))
    assert response.status_code == 429
    assert response.json() == {"detail": "daily_llm_quota"}


def test_ask_rejects_short_question_with_422() -> None:
    assert _ask(_client(), "ab").status_code == 422


def test_validate_rejects_delete_statement() -> None:
    response = _client().post("/v1/validate", json={"sql": "DELETE FROM x"})
    body = response.json()
    assert response.status_code == 200
    assert body["is_valid"] is False
    assert body["checks"][0]["detail"] == "not_select"
    assert body["reason"] == "not_select"


def test_validate_accepts_select_on_allowed_table() -> None:
    body = _client().post("/v1/validate", json={"sql": SCENARIOS[0].offline_sql}).json()
    assert body["is_valid"] is True
    assert body["reason"] is None
    assert [check["passed"] for check in body["checks"]] == [True, True, True]


def test_validate_does_not_consume_llm_quota() -> None:
    limiter = _limiter(llm=1)
    client = _client(limiter=limiter)
    for _ in range(3):
        client.post("/v1/validate", json={"sql": "DELETE FROM x"})
    assert limiter.try_consume_llm_call() is True


def test_validate_is_rate_limited() -> None:
    client = _client(limiter=_limiter(rate=1))
    assert client.post("/v1/validate", json={"sql": "DELETE FROM x"}).status_code == 200
    blocked = client.post("/v1/validate", json={"sql": "DELETE FROM x"})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"].isdigit()


def test_forwarded_for_identifies_the_client() -> None:
    client = _client(limiter=_limiter(rate=1))
    assert _ask(client, ip="1.1.1.1, 2.2.2.2").status_code == 200
    assert _ask(client, ip="3.3.3.3").status_code == 200
    assert _ask(client, ip="1.1.1.1").status_code == 429


def test_client_ip_without_peer_is_unknown() -> None:
    request = Request({"type": "http", "headers": [], "client": None})
    assert _client_ip(request) == "unknown"


def test_cors_allows_configured_origin() -> None:
    response = _client().options(
        "/v1/ask", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
    )
    assert response.headers["access-control-allow-origin"] == ORIGIN


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        json.loads(record.getMessage()) for record in caplog.records if record.name == LOGGER_NAME
    ]


def test_ask_log_has_hash_and_never_the_question(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _ask(client)
        _ask(client)
    first, second = _records(caplog)
    assert first["event"] == "ask"
    assert first["status"] == "answered"
    assert first["lang"] == "pt"
    assert first["degraded"] is False
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert first["latency_ms"] == 250
    assert first["question_len"] == len(QUESTION)
    assert isinstance(first["question_hash"], str)
    assert len(first["question_hash"]) == 12
    assert first["question_hash"] == second["question_hash"]
    assert QUESTION not in caplog.text
    assert "testclient" not in caplog.text


def test_validate_and_denied_logs_do_not_leak_sql(caplog: pytest.LogCaptureFixture) -> None:
    client = _client(limiter=_limiter(rate=1))
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.post("/v1/validate", json={"sql": DELETE_SQL})
        client.post("/v1/validate", json={"sql": DELETE_SQL})
    allowed, denied = _records(caplog)
    assert allowed["event"] == "validate"
    assert allowed["status"] == "invalid"
    assert allowed["question_hash"] is None
    assert denied["status"] == "rate_limited"
    assert "secret_table" not in caplog.text


def test_app_factory_offline_builds_working_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA4_OFFLINE", "1")
    monkeypatch.setenv("GA4_SAMPLE_PATH", str(PARQUET))
    client = TestClient(app_factory())
    assert client.get("/health").json() == {"status": "ok"}
    assert _ask(client).json()["status"] == "answered"
