# ADR 007 — Observability: JSON Logs + OpenTelemetry on Cloud Trace

> 🇺🇸 EN | 🇧🇷 [PT-BR](007-observability-opentelemetry.pt-BR.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
NFR-01 (p95 latency ≤ 8 s) requires breakdown across each pipeline stage (LLM draft, AST check, dry-run, BigQuery execution, summary). ADR 004 deferred span-based evaluators due to lack of distributed tracing. Single-line structured JSON logging without PII was proven in Demo 1.

## Considered Options
| Option | Pros | Cons |
|---|---|---|
| A — JSON Structured Logs Only (Standard) | Lightweight, reliable | Lacks per-span waterfall breakdown |
| **B — OpenTelemetry → Cloud Trace** | Native GCP Cloud Trace integration; per-step latency spans; enables span evaluators | Additional telemetry packages; verification needed for free-tier fit |
| C — Logfire SaaS | Turnkey integration with PydanticAI | External third-party SaaS; introduces additional API key |

## Decision
Enforce single-line structured JSON logging without PII across all components from the initial release (standard). OpenTelemetry with trace export to Google Cloud Trace is scheduled as a future roadmap phase (Phase 9) alongside live evaluations.

## Verification Points for Phase 9
1. Verify PydanticAI exports OpenTelemetry spans to generic OTLP exporters without requiring Logfire SaaS.
2. Confirm Cloud Trace ingestion volume stays within GCP free tier allowances, compliant with NFR-03.

If either check fails, Option A remains the permanent strategy.

## Consequences
- Positive: Step-by-step latency profiling and span assertions.
- Roadmap: Runtime Service Account receives `roles/cloudtrace.agent` in Terraform when Phase 9 is implemented.
