# Spikes da Fase 1

> Resultados dos 4 spikes de risco do plano de implementação. Cada um registra se o ADR afetado se mantém ou muda.

## Spike 3 — Modelo da faixa Lite no Vertex AI (2026-11-13)

Fonte oficial: [Vertex AI — model versions](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions). Preços: [página da Gemini API](https://aistudio.google.com/docs/pricing) — **não é a página de preços do Vertex**, que não foi lida integralmente.

| Model ID | Status | Lançamento | Descontinuação | Entrada / Saída por 1M tokens |
|----------|--------|------------|----------------|-------------------------------|
| `gemini-3.5-flash-lite` | GA | 2026-07-21 | 2027-07-21 ou posterior | não confirmado |
| `gemini-3.1-flash-lite` | GA | 2026-05-07 | 2027-05-07 ou posterior | US$ 0,25 / US$ 1,50 (Gemini API) |
| `gemini-2.5-flash-lite` | GA na tabela | 2025-07-22 | **2026-10-20 (vencida)** | US$ 0,10 / US$ 0,40 |
| `gemini-3.8-flash` (referência) | GA | 2026-09-02 | 2027-09-02 ou posterior | US$ 0,75 / US$ 3,75 até 2026-12-31; depois US$ 1,50 / US$ 7,50 |

**Conclusão:** o `gemini-2.5-flash-lite` (base da estimativa do ADR 001) está descontinuado. Candidatos: `gemini-3.5-flash-lite` (preço a confirmar) ou `gemini-3.1-flash-lite`.

**Impacto no RNF-03 (US$ 5/mês):** com `gemini-3.1-flash-lite` e a mesma hipótese de tokens (~4,5k entrada + ~0,5k saída por pergunta), o custo sobe para ~US$ 0,0019 por pergunta → ~US$ 11/mês **se** as 200 req/dia forem todas chamadas novas ao LLM. O cache (ADR 002, camada 2) reduz isso para as perguntas prontas, mas o pior caso estoura o teto.

**Decisão pendente (com o Fabio):** reduzir a cota diária de chamadas novas ao LLM (cache hits não contam) para caber em US$ 5 no pior caso, ou rever o teto. O ID do modelo fica em `settings.py`; o preço do `gemini-3.5-flash-lite` no Vertex precisa ser confirmado na página oficial de preços do Vertex.

## Spike 1 — mypy × PydanticAI (2026-11-13) — ✅ PASSA

PydanticAI `2.68.0` passa em `mypy --strict` **sem nenhuma supressão** (verificado pelo orquestrador: `Success: no issues found in 3 source files`, `3 passed`, zero ocorrências de `type: ignore`/`noqa`/`Any` em `spikes/`).

- Forma que tipa: `Agent[None, SqlDraft](model, output_type=SqlDraft)` dentro de uma função fábrica que recebe `Model`; `@agent.output_validator` síncrono levantando `ModelRetry`.
- Provider Vertex: `pydantic_ai.providers.google_cloud.GoogleCloudProvider(project=..., location=...)` + `pydantic_ai.models.google.GoogleModel`.
- Estouro de tentativas: `pydantic_ai.exceptions.UnexpectedModelBehavior`. Default: 1 retry de saída (2 chamadas no total) — compatível com o passo 4 do PRD.
- Testes offline com `FunctionModel` + `models.ALLOW_MODEL_REQUESTS = False`, respondendo `ToolCallPart` para `info.output_tools[0].name`.
- Nenhum aviso de depreciação.

**Decisão:** ADR 006 mantido; plano B descartado. Código de evidência em `spikes/`.

## Spike 2 — Dry-run real no BigQuery
*Pendente (depende da autenticação local do Fabio).*

## Spike 4 — Transpilação BigQuery → DuckDB
*Pendente (depende da amostra do spike 2).*
