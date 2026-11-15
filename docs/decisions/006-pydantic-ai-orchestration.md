# ADR 006 — LLM Orchestration with PydanticAI

> 🇺🇸 EN | 🇧🇷 [PT-BR](006-pydantic-ai-orchestration.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
The PRD flow (P4) is linear and fixed: two model invocations (SQL generation with validation error-driven retry, followed by executive summarization), with zero autonomous tool loops. The Master Standard previously implemented custom retry parsers in Demo 1. To expand portfolio repertoire, this project evaluates PydanticAI.

## Considered Options
| Option | Pros | Cons |
|---|---|---|
| A — Custom Parser Pipeline (Standard) | 100% deterministic, zero external framework dependencies | Already proven in Demo 1 |
| **B — PydanticAI v2** | `output_validator` + `ModelRetry` directly matches Step 4; `GoogleCloudProvider` supports ADC; `FunctionModel` enables offline testing | Dynamic typing patterns can conflict with zero-suppression mypy strict rules |
| C — LangGraph / Agent Frameworks | Trendy vocabulary | Massive architectural bloat for a deterministic 2-step linear pipeline |

## Decision
Adopt PydanticAI v2 pinned to an exact version, utilized strictly as a typed structured output executor without autonomous tool loops or agent graphs.

## Boundary of Responsibilities
| PydanticAI Role | Native Python Domain Role (`domain.py`) |
|---|---|
| Schema serialization, error propagation back to LLM on retry, mock test harness | `sqlglot` AST safety rules, date anchor resolution, dry-run cost ceiling, number grounding |

The `output_validator` delegates directly to `domain.py`. Orchestrator `service.py` depends on generic `Protocol` interfaces (`SqlGenerator`, `Summarizer`), isolating PydanticAI behind adapter classes in `llm.py`.

## Divergence from Master Standard
Replaces custom parser loop with PydanticAI retries and replaces `FakeModelClient` with snapshot-backed `FunctionModel`.

## Consequences
- Positive: Demonstrates modern structured output libraries while preserving strict clean architecture boundaries.
- Trade-off: Framework dependency requiring strict verification that no `# type: ignore` suppressions leak into the codebase.
