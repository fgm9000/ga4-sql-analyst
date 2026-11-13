# ADR 006 — Orquestração de LLM com PydanticAI

> 🇧🇷 PT-BR | 🇺🇸 [EN](006-pydantic-ai-orchestration.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
O fluxo do PRD (P4) é fixo: 2 chamadas de LLM (geração de SQL com nova tentativa guiada pelo erro de validação; resumo), sem ferramentas nem loop de agente. O Padrão Mestre implementa isso com `llm.py` + `parser.py` próprios, já provados na demo 1. Para o portfólio, repetir não traz evidência nova.

## Opções consideradas
| Opção | Prós | Contras |
|-------|------|---------|
| A — Pipeline próprio (padrão) | Determinístico, sem dependência | Já provado na demo 1 |
| B — PydanticAI v2 | `output_validator` + `ModelRetry` é exatamente o passo 4 (exemplo oficial é validar SQL); `GoogleCloudProvider()` usa ADC (keyless, ADR 001/S6); `FunctionModel` + `ALLOW_MODEL_REQUESTS = False` para testes offline | Exemplo oficial usa `# type: ignore` em `output_type` (conflito com zero supressões); v2 recente com releases frequentes |
| C — LangGraph / ADK | Vocabulário de "agentes" | Grafo para fluxo linear; excesso |

## Decisão
PydanticAI v2 (versão exata fixada), usado como executor de saída estruturada — sem tools, sem loop de agente, sem multi-agente.

## Fronteira de responsabilidade
| PydanticAI | Código próprio (`domain.py`) |
|------------|------------------------------|
| Saída estruturada tipada, nova tentativa com erro devolvido ao modelo, modelo de teste | AST (`sqlglot`), âncora de data, dry-run de custo, conferência de números |

O `output_validator` apenas chama as verificações de `domain.py`; a decisão é do código. `service.py` depende de `Protocol`s (`SqlGenerator`, `Summarizer`); os agentes do PydanticAI ficam atrás de um adaptador em `llm.py`.

## Divergência do padrão
`parser.py` deixa de ter loop de retry próprio; `FakeModelClient` é substituído por `FunctionModel` alimentado pelo snapshot. **O que se perde:** controle total sobre o loop e zero dependência. **Compensação:** `Protocol` preservado — o pipeline próprio pode voltar sem tocar em `service.py`.

## Consequências
- Positivas: repertório novo; menos código de infraestrutura; integração com `pydantic_evals` (ADR 004).
- Negativas: dependência de framework em evolução rápida (v2 desde 2026-06-23 — changelog oficial).
- Impacto no plano: Fase 1 (spike de tipagem), Fase 3.

## Critério de revisão / plano B
**Spike obrigatório na Fase 1:** `Agent` com `output_type` estruturado + `output_validator` + `GoogleModel` passando em `mypy --strict` **sem nenhuma supressão**. Se não passar, volta o pipeline próprio (opção A) e o `pydantic_evals` avalia a função diretamente. A catraca não é negociável.
