"""Tests for the static playground served by the API under /app."""

from pathlib import Path

from fastapi.testclient import TestClient

from ga4_sql_analyst.api import create_app
from ga4_sql_analyst.cache import ResponseCache
from ga4_sql_analyst.limits import StrictRateLimiter
from ga4_sql_analyst.models import AskRequest, AskResponse
from ga4_sql_analyst.scenarios import SCENARIOS
from ga4_sql_analyst.settings import Settings
from ga4_sql_analyst.snapshot import Snapshot

WEB_DIR = Path(__file__).parent.parent / "web"
CSP = "content-security-policy"
CSP_HEADERS = (CSP, "x-content-type-options", "referrer-policy")


class _FixedService:
    async def ask(self, request: AskRequest) -> AskResponse:
        return AskResponse(status="answered", summary="canned")


def _client(web_dir: Path) -> TestClient:
    app = create_app(
        Settings(web_dir=web_dir),
        _FixedService(),
        StrictRateLimiter(100, 1000, 1000),
        ResponseCache(),
        Snapshot([]),
    )
    return TestClient(app)


def test_app_index_is_served_with_strict_csp() -> None:
    response = _client(WEB_DIR).get("/app/")
    assert response.status_code == 200
    assert "GA4 SQL Analyst" in response.text
    csp = response.headers[CSP]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_app_without_trailing_slash_redirects() -> None:
    response = _client(WEB_DIR).get("/app", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/"


def test_app_assets_are_served() -> None:
    client = _client(WEB_DIR)
    script = client.get("/app/app.js")
    assert script.status_code == 200
    assert "API_BASE" in script.text
    assert CSP in script.headers
    assert client.get("/app/styles.css").status_code == 200
    assert client.get("/app/examples.json").status_code == 200


def test_examples_match_the_backend_scenarios() -> None:
    examples = _client(WEB_DIR).get("/app/examples.json").json()
    assert [example["question"] for example in examples] == [
        dict(scenario.question) for scenario in SCENARIOS
    ]


def test_api_routes_do_not_get_the_csp() -> None:
    client = _client(WEB_DIR)
    ask = client.post("/v1/ask", json={"question": SCENARIOS[0].question["pt"], "lang": "pt"})
    assert ask.status_code == 200
    for header in CSP_HEADERS:
        assert header not in ask.headers
    assert CSP not in client.get("/health").headers


def test_root_still_redirects_to_docs_with_the_playground_mounted() -> None:
    response = _client(WEB_DIR).get("/", follow_redirects=False)
    assert response.headers["location"] == "/docs"


def test_app_without_web_dir_is_not_mounted(tmp_path: Path) -> None:
    client = _client(tmp_path / "missing")
    assert client.get("/app/").status_code == 404
    assert client.get("/app", follow_redirects=False).status_code == 404
