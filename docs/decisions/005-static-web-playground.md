# ADR 005 — Static Web Playground

> 🇺🇸 EN | 🇧🇷 [PT-BR](005-static-web-playground.pt-BR.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
The 30-Second Rule mandates that the demonstration interface load instantaneously without client-side lag. Technical evaluators are reviewing data engineering, Python architecture, and GCP infrastructure rather than frontend frameworks. The standard pattern (HTML + Vanilla JS + precompiled Tailwind CSS hosted on GitHub Pages) was proven in Demo 1.

## Considered Options
| Option | New Portfolio Repertoire | Trade-offs |
|---|---|---|
| **A — Static Web Playground (Standard)** | No | Best alignment with the 30-second review rule; 0 ms cold start |
| B — React + Vite | No | Build pipeline and runtime overhead without additional technical signaling |
| C — Streamlit | Yes | Secondary container cold starts, awkward internationalization and strict CSP constraints |
| D — HTMX + Jinja in FastAPI | Yes | Tied to backend cold starts; cannot be hosted on GitHub Pages |

## Decision
Maintain the Static Web Playground on GitHub Pages, adhering strictly to the Master Standard.

## Justification
New technical capabilities in this demo focus on data engineering and cloud infrastructure (BigQuery, PydanticAI, `pydantic_evals`, Terraform, DuckDB). The frontend prioritizes instantaneous availability, zero external CDNs, and strict CSP compliance.

## Key UI Components
- End-to-end audit card: question → syntax-highlighted SQL → verification badges (Code vs. LLM) → result table → grounded summary.
- Visual byte meter displaying estimated scan bytes against the 400 MB ceiling (Scenario 3).
- Cold start warning and snapshot fallback indicators (`degraded: true`).
- Interactive "Try injection" button illustrating AST defense (Scenario 4).
- Minimal local SQL syntax highlighter without external script CDNs.

## Divergence from Master Standard
Zero divergence — strictly follows standard.
