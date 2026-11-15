# ADR 001 — Stack and Tooling

> 🇺🇸 EN | 🇧🇷 [PT-BR](001-stack-and-tooling.pt-BR.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
The PRD v1.0 requires advanced Python, FastAPI, and pandas for a robust analytical data pipeline on GCP. The service operates via request/response (`POST /v1/ask`) without streaming, targeting p95 latency ≤ 8 s (NFR-01). Validating SQL AST syntax (FR-02) and transpiling queries for offline test execution against local engines (P8 risk) requires a robust multi-dialect SQL parser.

## Considered Options
| Branch | Option | Pros | Cons |
|---|---|---|---|
| S1 | **Python 3.12** (Standard) | Modern type hinting, high performance, mature data ecosystem | — |
| S2 | **`uv` + Ruff + mypy `--strict` + Pytest** (Standard) | Established quality ratchet with 100.0% coverage enforcement | — |
| S3 | **FastAPI** (Standard) | Automatic OpenAPI docs at `/docs`, Pydantic serialization, native async | — |
| S4 | **Pydantic v2** (Standard) | Typed structured outputs for LLM and response envelope | — |
| S2+ | **`sqlglot`** | Multi-dialect parser/AST, transpiles BigQuery → DuckDB, pure Python | Incomplete coverage of custom BigQuery functions (to be validated) |

## Decision
Adopt Python 3.12 + `uv` + Ruff + mypy `--strict` + Pytest + FastAPI + Pydantic v2, introducing `sqlglot` as the core dependency for SQL validation and offline AST transpilation.

**S6 — LLM Provider:** Gemini via **Vertex AI** in the **Lite** tier, with the model ID configured in `settings.py`. Authentication leverages Cloud Run runtime Service Account (Workload Identity / ADC) with zero static API keys. Default model: **`gemini-3.1-flash-lite`** (GA).

**S5 — Persistence & Local Warehouse:**
- Production: Stateless service with versioned repository snapshot fallbacks. Official `google-cloud-bigquery` client for dry-run estimation and execution.
- CI / Offline Tests: **DuckDB** querying a 1% deterministic Parquet sample versioned in `tests/fixtures/`. BigQuery SQL is transpiled with `sqlglot` after custom AST rewriting of `events_*` + `_TABLE_SUFFIX` into `event_date` filters.
- Result comparison in evaluations using `pandas.testing` (value tolerance and order-agnostic matching unless `ORDER BY` is explicit).
- **Supabase: Excluded.** External network dependency unsuitable for offline CI, and production requires no state storage.

## Justification
The chosen stack represents corporate best practices in GCP analytics engineering. `sqlglot` satisfies both AST safety validation (FR-02) and local offline execution transpilation with a single dependency.

## Divergence from Master Standard
- **S6:** The Master Standard uses OpenRouter. This project selects Vertex AI. **Reason:** Keyless authentication via Cloud Run service account identity (eliminating secret leakage vectors), native GCP cloud integration, and demonstrating multi-provider abstraction behind a typed `ModelClient` protocol.
- Addition: `sqlglot`.

## Consequences
- Positive: Direct re-use of DevSecOps workflows and 100% coverage quality ratchet.
- Trade-offs: Dependency on `sqlglot` AST coverage for BigQuery dialect security (mitigated by extensive adversarial test suites).

## Review Triggers
If `sqlglot` fails to accurately parse standard GA4 BigQuery constructs (`UNNEST(event_params)`, `_TABLE_SUFFIX`) in a way that compromises FR-02 safety.
