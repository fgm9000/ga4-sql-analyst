# System Architecture — ga4-sql-analyst

> 🇺🇸 EN | 🇧🇷 [PT-BR](architecture.pt-BR.md)

This document details the architectural boundaries, security invariants, data flow, and degradation semantics of `ga4-sql-analyst`.

---

## 1. System Overview

`ga4-sql-analyst` is a stateless, keyless analytics backend and accompanying static playground that enables users to query Google Analytics 4 e-commerce data in BigQuery using natural language questions in English or Portuguese.

```mermaid
graph TB
    subgraph Clients
        WebClient["Static Web Playground (GitHub Pages)"]
        DirectClient["API Consumers & Swagger UI"]
    end

    subgraph "Google Cloud Run (ga4-sql-analyst)"
        API["FastAPI App Factory (api.py)"]
        Limits["Rate Limiter & Quotas (limits.py)"]
        Cache["In-Memory LRU Cache"]
        Domain["Domain Service (domain.py)"]
        Rules["AST Rules Engine (sql_rules.py)"]
        LLM["PydanticAI Client (llm.py)"]
        Warehouse["Warehouse Adapter (warehouse.py)"]
        Snapshot["Snapshot Fallback (snapshot.py)"]
    end

    subgraph "Google Cloud Services (fgm9000-portfolio)"
        VertexAI["Vertex AI (gemini-3.1-flash-lite)"]
        BigQuery["BigQuery Engine (Public GA4 Dataset)"]
    end

    WebClient -->|HTTPS /v1/ask| API
    DirectClient -->|HTTPS /v1/ask| API
    DirectClient -->|HTTPS /v1/validate| API
    API --> Limits
    Limits --> Cache
    Cache --> Domain
    Domain --> Rules
    Domain --> LLM
    LLM -->|Workload Identity ADC| VertexAI
    Domain --> Warehouse
    Warehouse -->|Dry-run & Execution| BigQuery
    Domain -.->|Degradation| Snapshot
```

---

## 2. End-to-End Sequence Diagram (`POST /v1/ask`)

The execution strictly follows an 8-step pipeline where non-deterministic LLM operations are bounded by deterministic Python checks:

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI (api.py / limits.py)
    participant Domain as Domain (domain.py)
    participant Rules as AST Guardrails (sql_rules.py)
    participant LLM as Vertex AI (llm.py)
    participant BQ as BigQuery (warehouse.py)

    Client->>API: POST /v1/ask {question, language}
    Note over API: Check IP limit (5/min) and daily cap (200 req/day)
    API->>API: Check In-Memory Cache (normalized question + lang)
    alt Cache Hit
        API-->>Client: 200 OK (cached response, 0 ms)
    end

    API->>Domain: execute_ask(payload)
    Note over Domain: Step 1: Normalize string (NFC, max 500 chars)
    Note over Domain: Step 2: C04 - Resolve date anchor against 2021-01-31

    Domain->>LLM: Step 3: generate_sql(question, date_context)
    LLM-->>Domain: SqlDraft {sql, tables, intent}

    Domain->>Rules: Step 4: C01-C03 - validate_sql(draft.sql)
    alt Syntax / Policy Violation (e.g., DROP, forbidden function)
        Rules-->>Domain: ValidationError
        Domain->>LLM: Retry with syntax error feedback (1 retry)
        LLM-->>Domain: Revised SqlDraft
        Domain->>Rules: Re-validate AST
        alt Second Failure
            Domain-->>Client: 200 OK {status: "blocked", reason: "not_select"}
        end
    end

    Domain->>BQ: Step 5: C05 - dry_run(sql)
    BQ-->>Domain: total_bytes_processed
    alt Bytes > 400 MB
        Domain-->>Client: 200 OK {status: "blocked", reason: "cost_ceiling", estimated_bytes}
    end

    Domain->>BQ: Step 6: execute(sql, maximum_bytes_billed=400MB)
    BQ-->>Domain: result_rows (up to 100 rows)

    Domain->>LLM: Step 7: generate_summary(question, rows, sql)
    LLM-->>Domain: Raw summary text

    Domain->>Domain: Step 8: C06 - ground_numbers(summary, rows)
    Note over Domain: Replace ungrounded numbers with [?]

    Domain-->>API: AskResponse {status: "answered", checks, rows, summary}
    API->>API: Store in memory cache
    API-->>Client: 200 OK
```

---

## 3. Deterministic Invariants & Verification Suite

### C01: Single Statement & Read-Only AST
- Built using `sqlglot` parser for Google BigQuery dialect.
- Must parse into exactly one SQL statement.
- Root expression must be `Select`, `Union`, `Intersect`, or `Except`.
- Disallowed AST nodes: `Insert`, `Update`, `Delete`, `Merge`, `Drop`, `Create`, `Alter`, `Command`, `TruncateTable`.
- Prohibited environment/identity functions: `SESSION_USER`, `CURRENT_USER`, `EXTERNAL_QUERY`, `EXTERNAL_OBJECT_TRANSFORM`, `VECTOR_SEARCH`, `ML.*`, `AI.*`, `KEYS.*`, `AEAD.*`, `DETERMINISTIC_ENCRYPT`, `DETERMINISTIC_DECRYPT`, and system variables (`@@...`).

### C02: Table Whitelist Enforcement
- Scans all table references in the AST.
- Must include at least one allowed table.
- All referenced tables must belong to:
  `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` or
  `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_YYYYMMDD` (or locally defined CTEs within `WITH` expressions).

### C03: Bounded Query Results (`LIMIT 100`)
- Detects the top-level `LIMIT` clause.
- Injects `LIMIT 100` if absent.
- Clamps values exceeding 100 down to 100.
- Never blocks valid queries; acts as an idempotent AST transform.

### C04: Deterministic Relative Date Anchor
- The public GA4 sample ends on **January 31, 2021** (92 partitioned daily tables from `2020-11-01` to `2021-01-31`).
- Queries requesting "today", "yesterday", "last 30 days", "last month", or "last quarter" are resolved deterministically before prompt rendering:
  - `"today"` / `"hoje"` = `2021-01-31`
  - `"yesterday"` / `"ontem"` = `2021-01-30`
  - `"last 30 days"` / `"últimos 30 dias"` = `2021-01-02` to `2021-01-31`
  - `"last month"` / `"último mês"` = Previous calendar month (`2020-12-01` to `2020-12-31`)
  - `"last quarter"` / `"último trimestre"` = `2020-11-01` to `2020-12-31` (clamped to dataset start)

### C05: Pre-Execution Dry-Run Cost Ceiling
- Performs a free dry-run against BigQuery API with `use_query_cache=False`.
- Evaluates: `max(estimated_bytes, 10_485_760) <= 400_000_000`.
- Queries exceeding 400 MB (e.g., unbounded scans across all 92 tables) are rejected with HTTP 200, returning `status: "blocked"` and the exact estimated bytes.

### C06: Executive Summary Number Grounding
- Parses all numeric tokens in the generated summary.
- Verifies that every number matches:
  - Exact cell values from result rows.
  - Derived ratios and percentages within a 0.5% tolerance.
  - Row counts (e.g., "top 10").
  - Formatted dates and timestamp components.
- Any fabricated number that lacks grounding in query output is deterministically replaced with `[?]`.

---

## 4. Graceful Degradation Semantics

The system is designed never to crash or show an unhandled error during service disruptions:

| Failure Mode | Preloaded Scenario | Free Natural Language Query |
|---|---|---|
| **Vertex AI Unavailable / Quota Exhaustion** | Serves static snapshot with `degraded: true` | Returns HTTP 200 with `status: "unavailable"` |
| **BigQuery API Down / Network Error** | Serves static snapshot with `degraded: true` | Returns generated SQL and AST check results with empty rows and `degraded: true` |
| **Executive Summary Failure** | Serves static snapshot | Returns query results with `summary: null` and `reason: "summary_unavailable"` |
| **Daily LLM Quota Exhausted (80/day)** | Serves static snapshot with `degraded: true` | Returns HTTP 429 with `daily_llm_quota` |
| **Client Rate Limit Exceeded (5 req/min)** | Returns HTTP 429 with `Retry-After` | Returns HTTP 429 with `Retry-After` |

---

## 5. Security & Deployment Architecture

1. **Keyless Cloud Run:** Container runs under a dedicated service account `ga4-sql-analyst-runtime` granted only `roles/bigquery.jobUser` and `roles/aiplatform.user`.
2. **Workload Identity Federation (WIF):** GitHub Actions deploys via OIDC federation without any persistent JSON service account keys.
3. **Hardened Container:** Multi-stage build with non-root user `appuser` (UID 10001), read-only virtual environment, and zero write permissions on root filesystem.
4. **Content Security Policy (CSP):** The web playground is served with strict CSP headers, zero external CDN scripts, and complete separation between data and executable code.
