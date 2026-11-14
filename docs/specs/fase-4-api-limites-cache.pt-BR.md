# Especificação da Fase 4 — API, limites, cache e configuração

> Base: PRD v1.0 (P4, RF-08, RNF-04, RNF-05, RNF-07), ADR 002 (camadas de custo), Padrão Mestre §1.1 (Application Factory, `/health`). Escrita pelo orquestrador em 2026-11-14.
> Módulos aprovados (NÃO editar, salvo onde indicado): `models.py` (só ACRESCENTAR as classes da Tarefa B), `domain.py`, `sql_rules.py`, `errors.py`, `ports.py`, `warehouse.py`, `prompt.py`, `llm.py`, `service.py`, `snapshot.py`, `scenarios.py`.

## Regras gerais (iguais às fases anteriores)
Python 3.12, `mypy --strict`, Ruff do projeto, inglês no código, 100% de cobertura, zero supressões (`# type: ignore`, `# noqa`, `# pragma: no cover`, `pyright: ignore`, `Any`, `cast`), funções ≤ 40 linhas, constantes no topo. Nenhum teste faz rede. Testes async com `@pytest.mark.anyio` (fixture em `tests/conftest.py`).

---

## Tarefa A — `settings.py`, `limits.py`, `cache.py` (Haiku)

### `settings.py`
`class Settings(BaseSettings)` com `model_config = SettingsConfigDict(env_prefix="GA4_", env_file=None, frozen=True)`:

| Campo | Tipo | Default |
|---|---|---|
| `gcp_project` | `str` | `"fgm9000-portfolio"` |
| `vertex_location` | `str` | `"global"` |
| `model_id` | `str` | `"gemini-3.1-flash-lite"` |
| `max_bytes_billed` | `int` (> 0) | `400_000_000` |
| `rate_per_minute` | `int` (> 0) | `5` |
| `daily_requests` | `int` (> 0) | `200` |
| `daily_llm_calls` | `int` (> 0) | `80` |
| `cache_max_entries` | `int` (> 0) | `500` |
| `cors_origins` | `Annotated[list[str], NoDecode]` | `["https://fgm9000.github.io"]` |
| `offline` | `bool` | `False` |
| `sample_path` | `Path` | `Path("tests/fixtures/ga4_sample.parquet")` |

`cors_origins`: `field_validator(mode="before")` que aceita `str` separada por vírgula (strip, descarta vazios) ou lista.
Testes: defaults; leitura por env (`monkeypatch.setenv("GA4_DAILY_LLM_CALLS", "10")`); `GA4_CORS_ORIGINS="https://a.com, https://b.com"` vira lista de 2; valor ≤ 0 rejeitado.

### `limits.py`
Relógio injetável para testes: `Clock = Callable[[], float]` (segundos epoch), default `time.time`.

```text
WINDOW_SECONDS = 60
SECONDS_PER_DAY = 86_400

@dataclass(frozen=True) LimitDecision: is_allowed: bool; reason: str | None; retry_after_seconds: int

class StrictRateLimiter:
    __init__(self, rate_per_minute: int, daily_requests: int, daily_llm_calls: int, clock: Clock = time.time)
    check_request(self, client_ip: str) -> LimitDecision
    try_consume_llm_call(self) -> bool
```
- IP nunca é guardado em claro: chave = `hashlib.sha256(ip.encode()).hexdigest()[:16]`.
- Por IP: janela deslizante de 60 s (deque de timestamps; descartar os mais antigos que `now − 60`). Estourou → `reason="rate_limited"`, `retry_after` = segundos até o timestamp mais antigo sair da janela (arredondar para cima, mínimo 1).
- Global diário: contador zerado quando muda o dia UTC (`int(now // SECONDS_PER_DAY)`). Estourou → `reason="daily_quota"`, `retry_after` = segundos até a meia-noite UTC.
- Ordem: checa o diário primeiro, depois o por IP; só registra a requisição se permitida.
- `try_consume_llm_call`: contador diário separado (mesma virada de dia); devolve `False` sem consumir se chegou em `daily_llm_calls`.
- Limpeza de memória: ao virar o dia, limpar o dicionário de IPs.
Testes com relógio falso: 5 passam e a 6ª bloqueia; passa de novo após 60 s; `retry_after` correto; cota diária; virada de dia zera tudo; IP guardado só como hash (inspecionar o atributo interno é aceitável no teste); `try_consume_llm_call` até o limite.

### `cache.py`
1. `class ResponseCache`: LRU em memória (`collections.OrderedDict`), `max_entries`.
   - Chave: `(question normalizada, lang)` — normalização: NFC + strip + colapso de espaços + `casefold`.
   - `get(question, lang) -> AskResponse | None` (move para o fim ao ler); `put(question, lang, response)` **só** guarda se `response.degraded is False` e `response.status in {"answered", "blocked"}`; despeja o mais antigo acima de `max_entries`.
   - Seguro sem TTL porque o dataset é congelado (ADR 002, camada 2) — escrever isso na docstring.
2. `class CachingWarehouse` (implementa `ports.Warehouse`): decorator de outro `Warehouse`; cacheia `dry_run` por `sql` e `execute` por `(sql, max_bytes_billed)` em dicts com o mesmo limite LRU; erros (`WarehouseUnavailableError`) não são cacheados.
Testes: hit/miss, normalização, LRU despeja o mais antigo, não guarda degradado/unavailable; `CachingWarehouse` chama o interno 1 vez para 2 chamadas iguais e não cacheia erro.

---

## Tarefa B — `offline.py`, `bootstrap.py`, `api.py`, `/v1/validate` (Sonnet)

### `models.py` (acrescentar, sem alterar o existente)
- `ValidateRequest`: `sql: str` (1..`SQL_MAX_CHARS`), frozen, extra forbid.
- `ValidateResponse`: `is_valid: bool`, `sql: str`, `checks: list[CheckResult]`, `reason: str | None = None`, frozen.

### `offline.py`
Mover para `src/` a lógica offline de `scripts/build_snapshot.py` (`_prompt_text`, `_scenario_sql`, `_summary_text`, `_offline_handler`) como `build_offline_model() -> FunctionModel` e `build_offline_service(sample_path: Path, max_bytes: int) -> AskService`. Depois, **editar `scripts/build_snapshot.py`** para importar daqui (sem duplicar lógica). Pergunta fora dos cenários no modo offline → o handler devolve SQL `SELECT event_name, COUNT(*) AS n FROM \`...events_*\` GROUP BY event_name ORDER BY n DESC LIMIT 10` (comportamento "demo offline").

### `bootstrap.py`
- `build_service(settings: Settings) -> AskService`:
  - `settings.offline` → `build_offline_service(settings.sample_path, settings.max_bytes_billed)`;
  - senão → `CachingWarehouse(create_bigquery_warehouse(settings.gcp_project))` + `PydanticAiSqlGenerator`/`PydanticAiSummarizer` com `build_vertex_model(settings.model_id, settings.gcp_project, settings.vertex_location)` + `Snapshot.load()`.
- Testes: offline real; live com `monkeypatch` de `create_bigquery_warehouse` e `build_vertex_model` (sem rede).

### `api.py`
`create_app(settings: Settings, service: AskService, limiter: StrictRateLimiter, cache: ResponseCache, clock: Callable[[], float] = time.perf_counter) -> FastAPI` e `app_factory() -> FastAPI` (zero argumentos, lê `Settings()`, usa `build_service`; é o alvo do `uvicorn --factory`).

Rotas:
| Método e rota | Comportamento |
|---|---|
| `GET /` | `RedirectResponse("/docs")` |
| `GET /health` e `GET /healthz` | `{"status": "ok"}` |
| `POST /v1/ask` (`AskRequest` → `AskResponse`) | 1) `limiter.check_request(ip)`; negado → **429** com header `Retry-After` e corpo `{"detail": reason}`. 2) `cache.get` → hit devolve. 3) miss → `limiter.try_consume_llm_call()`; sem cota → se `service` tiver o cenário no snapshot (expor `AskService.snapshot_lookup(request)` NÃO — use `Snapshot.load()` injetado? **Decisão:** `create_app` recebe também `snapshot: Snapshot`; sem cota → `snapshot.find(...)` com `degraded=True` via `model_copy(update=...)`, senão 429 `{"detail": "daily_llm_quota"}`. 4) `await service.ask(request)` → `cache.put` → devolve. |
| `POST /v1/validate` (`ValidateRequest` → `ValidateResponse`) | só `limiter.check_request(ip)` (não consome cota de LLM); `domain.validate_sql(sql)` → `ValidateResponse(is_valid, sql, list(checks), reason)`. Nenhuma execução, nenhum LLM. |

- IP do cliente: primeiro valor de `X-Forwarded-For` (Cloud Run) se existir; senão `request.client.host`; senão `"unknown"`.
- CORS: `CORSMiddleware(allow_origins=settings.cors_origins, allow_methods=["GET","POST"], allow_headers=["Content-Type"])`.
- Log: uma linha JSON por requisição de `/v1/*` via `logging.getLogger("ga4_sql_analyst")`: `event` (`ask`/`validate`), `status`, `lang` (ask), `degraded`, `cache_hit`, `latency_ms` (int, via `clock`), `question_len`, `question_hash` (`sha256(...)[:12]`). **Proibido** logar a pergunta, o SQL, o IP ou o hash do IP.
- `422` do FastAPI para entrada inválida fica como está.

Testes (`tests/test_api.py`, `httpx.AsyncClient` com `ASGITransport` ou `fastapi.testclient.TestClient`): `/`, `/health`, `/healthz`; ask feliz (serviço offline real); cache hit não chama o serviço de novo (dublê contador); 429 por IP com `Retry-After`; 429 diário; sem cota de LLM com snapshot → `degraded=True`; sem cota e sem snapshot → 429 `daily_llm_quota`; validate de `DELETE ...` → `is_valid=False`, `checks[0].detail == "not_select"`, e de um SELECT válido → `is_valid=True`; validate não consome cota de LLM; `X-Forwarded-For` usado; 422 com pergunta curta; log JSON capturado com `caplog` contém `question_hash` e NÃO contém a pergunta; `app_factory` com `GA4_OFFLINE=1`.

---

## Verificação (cada tarefa)
```
uv run ruff format --check . && uv run ruff check .
uv run mypy && uv run mypy --strict scripts/
uv run pytest --cov=ga4_sql_analyst --cov-report=term-missing -q
grep -rnE "type: ignore|noqa|pragma: no cover|pyright: ignore|\bAny\b|cast\(" src tests scripts || echo zero
```
