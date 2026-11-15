# ADR 002 — Core Architecture and Deterministic Guardrails

> 🇺🇸 EN | 🇧🇷 [PT-BR](002-core-architecture-and-guardrails.pt-BR.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
PRD thesis: The LLM generates SQL and prose summaries; code enforces absolute authority over execution safety, cloud cost, temporal coherence, and numerical grounding (FR-02 through FR-06). Operates via a fixed 8-step pipeline, snapshot fallback degradation, a US$ 5/month cost ceiling, and a frozen public dataset (Nov 2020 – Jan 2021).

## Decision

### Module Decomposition (Single Responsibility Principle)
| Module | Responsibility |
|---|---|
| `models.py` | Pydantic v2 schemas: request contracts, structured LLM drafts (`sql`, `tables`, `intent`), response envelopes (`status`, `period`, `checks`, `rows`, `summary`, `degraded`). |
| `sql_rules.py` | AST inspection rules for C01–C03 (re-exported by `domain.py`). |
| `domain.py` | Pure business logic: AST evaluation, date anchoring, `_TABLE_SUFFIX` rewriting for DuckDB, summary number grounding. |
| `prompt.py` | Bilingual templates, GA4 table schema grounding, XML payload isolation tags. |
| `llm.py` | PydanticAI model integration (`SqlGenerator`, `Summarizer`) with schema validation retries. |
| `warehouse.py` | `Warehouse` Protocol with `dry_run()` and `execute()`; BigQuery and DuckDB implementations. |
| `service.py` | 8-step pipeline orchestration, status determination, and degradation logic. |
| `cache.py` | In-memory LRU response cache keyed by normalized question and language. |
| `limits.py` | Sliding-window IP rate limiter and daily usage quotas. |
| `settings.py` | Strongly typed environment settings via `pydantic-settings`. |
| `api.py` | FastAPI application endpoints: `/docs`, `/health`, `/v1/ask`, `/v1/validate` (FR-08: AST check only, zero LLM overhead). |

### Deterministic Invariants (Code Authority)
| ID | Check | Action on Failure |
|---|---|---|
| **C01** | AST: Single `SELECT`, no DML/DDL; prohibits identity/system functions (`SESSION_USER`, `CURRENT_USER`, `EXTERNAL_QUERY`, `ML.*`, `AI.*`, `KEYS.*`, `AEAD.*`, `@@...`). | 1 retry attempt with error feedback → `status: "blocked"`. |
| **C02** | Tables strictly restricted to `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` or local CTEs. | 1 retry attempt → `status: "blocked"`. |
| **C03** | Injects `LIMIT 100` if missing; clamps values > 100 down to 100. | Rewrites AST; never blocks. |
| **C04** | Resolves relative date expressions deterministically against `2021-01-31`. | Deterministic resolution before prompt construction. |
| **C05** | Dry-run byte estimation must not exceed 400 MB. | Immediate rejection with `status: "blocked"` (no retry). |
| **C06** | Numbers cited in executive summary must exist in query results. | Masks ungrounded numerals with `[?]`. |

### Status Semantics
- `answered`: Query executed successfully, summary grounded.
- `blocked`: Rejected by deterministic code check (HTTP 200 with reason and rejected query).
- `unavailable`: LLM offline during an ad-hoc query.
- `degraded: true`: Served from precomputed snapshot or BigQuery unreachable.

### 5-Layer Cost and Abuse Guardrails
1. **IP Rate Limit:** 5 req/min per IP, 200 req/day global cap, and **maximum 80 new LLM calls/day**.
2. **In-Memory Cache:** Unbounded TTL within instance lifecycle (safe because public dataset is frozen).
3. **BigQuery Thresholds:** `maximum_bytes_billed = 400_000_000` (400 MB). Evaluates `max(estimated_bytes, 10 MiB)`.
4. **Token Bounds:** Strict output `max_tokens` limits on all model completions.
5. **Budget Alerts:** Cloud Billing alerts configured at 50%, 90%, and 100% of target budget.

## Justification
Verifiable constraints belong in tested deterministic code; the model is confined to semantic translation. Multi-layered cost boundaries protect against traffic surges and unexpected query scans.

## Divergence from Master Standard
Zero structural divergence. Additions: `warehouse.py` and `cache.py`.
