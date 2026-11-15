"""FastAPI application: routes, per-request limits, response cache and privacy-safe logging."""

import hashlib
import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from typing import NoReturn, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ga4_sql_analyst.bootstrap import build_service
from ga4_sql_analyst.cache import ResponseCache
from ga4_sql_analyst.domain import validate_sql
from ga4_sql_analyst.limits import LimitDecision, StrictRateLimiter
from ga4_sql_analyst.models import (
    AskRequest,
    AskResponse,
    ValidateRequest,
    ValidateResponse,
)
from ga4_sql_analyst.settings import Settings
from ga4_sql_analyst.snapshot import Snapshot

logger = logging.getLogger("ga4_sql_analyst")

REASON_LLM_QUOTA = "daily_llm_quota"
FORWARDED_FOR_HEADER = "x-forwarded-for"
RETRY_AFTER_HEADER = "Retry-After"
UNKNOWN_CLIENT = "unknown"
QUESTION_HASH_CHARS = 12
MILLISECONDS = 1000
HTTP_TOO_MANY_REQUESTS = 429
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
ALLOWED_METHODS = ["GET", "POST"]
ALLOWED_HEADERS = ["Content-Type"]
WEB_MOUNT = "/app"
WEB_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class AskHandler(Protocol):
    """What the API needs from the ask service."""

    async def ask(self, request: AskRequest) -> AskResponse:
        """Answer the question, or explain why it was blocked or is unavailable."""


def _client_ip(request: Request) -> str:
    """Use the last non-empty X-Forwarded-For hop, then the socket peer.

    The Google Front End in front of Cloud Run appends the real client IP to the END of
    the header, so the leading values are whatever the client sent and can be forged.
    """
    hops = [hop.strip() for hop in request.headers.get(FORWARDED_FOR_HEADER, "").split(",")]
    trusted = [hop for hop in hops if hop]
    if trusted:
        return trusted[-1]
    return request.client.host if request.client is not None else UNKNOWN_CLIENT


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:QUESTION_HASH_CHARS]


def _root() -> RedirectResponse:
    return RedirectResponse("/docs")


def _web_redirect() -> RedirectResponse:
    return RedirectResponse(f"{WEB_MOUNT}/")


def _is_web_path(path: str) -> bool:
    return path == WEB_MOUNT or path.startswith(f"{WEB_MOUNT}/")


async def _add_web_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach the strict CSP and hardening headers to the playground responses only."""
    response = await call_next(request)
    if _is_web_path(request.url.path):
        response.headers.update(WEB_SECURITY_HEADERS)
    return response


def _health() -> dict[str, str]:
    return {"status": "ok"}


class _Handlers:
    """Route handlers sharing the limiter, cache, snapshot and clock."""

    def __init__(
        self,
        service: AskHandler,
        limiter: StrictRateLimiter,
        cache: ResponseCache,
        snapshot: Snapshot,
        clock: Callable[[], float],
    ) -> None:
        self._service = service
        self._limiter = limiter
        self._cache = cache
        self._snapshot = snapshot
        self._clock = clock

    async def ask(self, payload: AskRequest, request: Request) -> AskResponse:
        started = self._clock()
        decision = self._limiter.check_request(_client_ip(request))
        if not decision.is_allowed:
            self._deny("ask", started, decision, payload.question, payload.lang)
        cached = self._cache.get(payload.question, payload.lang)
        if cached is not None:
            self._log_ask(started, payload, cached, cache_hit=True)
            return cached
        response = await self._produce(started, payload)
        self._log_ask(started, payload, response, cache_hit=False)
        return response

    async def validate(self, payload: ValidateRequest, request: Request) -> ValidateResponse:
        started = self._clock()
        decision = self._limiter.check_request(_client_ip(request))
        if not decision.is_allowed:
            self._deny("validate", started, decision, None, None)
        validation = validate_sql(payload.sql)
        status = STATUS_VALID if validation.is_valid else STATUS_INVALID
        self._log("validate", started, status, None, None)
        return ValidateResponse(
            is_valid=validation.is_valid,
            sql=validation.sql,
            checks=list(validation.checks),
            reason=validation.reason,
        )

    async def _produce(self, started: float, payload: AskRequest) -> AskResponse:
        """Serve a cache miss: the service while LLM quota remains, else the snapshot."""
        if not self._limiter.try_consume_llm_call():
            recorded = self._snapshot.find(payload.question, payload.lang)
            if recorded is None:
                self._log("ask", started, REASON_LLM_QUOTA, payload.question, payload.lang)
                raise HTTPException(HTTP_TOO_MANY_REQUESTS, REASON_LLM_QUOTA)
            return recorded.model_copy(update={"degraded": True})
        response = await self._service.ask(payload)
        self._cache.put(payload.question, payload.lang, response)
        return response

    def _deny(
        self,
        event: str,
        started: float,
        decision: LimitDecision,
        question: str | None,
        lang: str | None,
    ) -> NoReturn:
        reason = decision.reason or ""
        self._log(event, started, reason, question, lang)
        headers = {RETRY_AFTER_HEADER: str(decision.retry_after_seconds)}
        raise HTTPException(HTTP_TOO_MANY_REQUESTS, reason, headers=headers)

    def _log_ask(
        self, started: float, payload: AskRequest, response: AskResponse, *, cache_hit: bool
    ) -> None:
        self._log(
            "ask",
            started,
            response.status,
            payload.question,
            payload.lang,
            degraded=response.degraded,
            cache_hit=cache_hit,
        )

    def _log(
        self,
        event: str,
        started: float,
        status: str,
        question: str | None,
        lang: str | None,
        *,
        degraded: bool = False,
        cache_hit: bool = False,
    ) -> None:
        """Emit one JSON line. The question is only measured and hashed, never written."""
        record = {
            "event": event,
            "status": status,
            "lang": lang,
            "degraded": degraded,
            "cache_hit": cache_hit,
            "latency_ms": int((self._clock() - started) * MILLISECONDS),
            "question_len": None if question is None else len(question),
            "question_hash": None if question is None else _hash_text(question),
        }
        logger.info(json.dumps(record, ensure_ascii=False))


def create_app(
    settings: Settings,
    service: AskHandler,
    limiter: StrictRateLimiter,
    cache: ResponseCache,
    snapshot: Snapshot,
    clock: Callable[[], float] = time.perf_counter,
) -> FastAPI:
    """Wire the routes and CORS around already-built collaborators (Application Factory)."""
    app = FastAPI(title="GA4 SQL Analyst")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
    )
    handlers = _Handlers(service, limiter, cache, snapshot, clock)
    app.add_api_route("/", _root, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health", _health, methods=["GET"])
    app.add_api_route("/healthz", _health, methods=["GET"])
    app.add_api_route("/v1/ask", handlers.ask, methods=["POST"], response_model=AskResponse)
    app.add_api_route(
        "/v1/validate", handlers.validate, methods=["POST"], response_model=ValidateResponse
    )
    if settings.web_dir.is_dir():
        app.middleware("http")(_add_web_security_headers)
        app.add_api_route(WEB_MOUNT, _web_redirect, methods=["GET"], include_in_schema=False)
        app.mount(WEB_MOUNT, StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app


def _configure_logging() -> None:
    """Send the JSON request lines to stdout (Cloud Logging reads it); idempotent."""
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def app_factory() -> FastAPI:
    """Zero-argument factory for `uvicorn --factory`; reads GA4_* settings."""
    settings = Settings()
    _configure_logging()
    limiter = StrictRateLimiter(
        settings.rate_per_minute, settings.daily_requests, settings.daily_llm_calls
    )
    return create_app(
        settings,
        build_service(settings),
        limiter,
        ResponseCache(settings.cache_max_entries),
        Snapshot.load(),
    )
