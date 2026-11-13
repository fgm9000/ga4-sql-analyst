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

## Spike 2 — Dry-run real no BigQuery (2026-11-13) — ✅ hipótese 1 do PRD refutada a favor

Medido com `bq --dry_run` e 2 queries reais no projeto `fgm9000-portfolio`.

**Dataset:** 92 tabelas diárias (`events_20201101`–`events_20210131`), 4.295.584 linhas, 3.417,6 MiB.

| Query | Bytes estimados |
|-------|-----------------|
| `SELECT *` sem filtro (Cenário 3) | 3.583.657.854 (~3,6 GB) |
| Cenário 1 — canal × receita, 30 dias | 10.987.776 (~11 MB) |
| Cenário 1 sem filtro de data | 39.983.554 (~40 MB) |
| Cenário 2 — funil por dispositivo, período todo | 92.817.563 (~93 MB) |
| Funil por dispositivo, 30 dias | 25.474.732 (~25 MB) |
| `UNNEST(event_params)`, período todo | 690.556.977 (~691 MB) |
| `UNNEST(event_params)`, 30 dias | 178.365.186 (~178 MB) |
| Sessões (`ga_session_id` via subquery em `event_params`), 30 dias | 223.151.506 (~223 MB) |

**Cobrança mínima (execução real):**
- 1 tabela, 1 coluna: processado 339.894 bytes → **cobrado 10.485.760 (10 MiB)**.
- 92 tabelas (`events_*`), 1 coluna: processado 55.954.561 → cobrado 56.623.104.
- Conclusão: o mínimo de 10 MiB vale **por query**, não por tabela × 92. A contabilidade de orçamento usa `max(bytes_estimados, 10 MiB)`.

**Conclusões:**
1. O Cenário 3 bloqueia com folga com qualquer teto razoável (3,6 GB). A hipótese 1 do PRD não se confirmou.
2. **Tensão nova:** perguntas comuns de GA4 que usam `event_params` (sessões, page_location) passam de 175 MB em 30 dias. Com teto de 100 MB, seriam bloqueadas.
3. O teto não pode ser derivado de 6 mil queries/mês se a cota de chamadas novas ao LLM for 80/dia (spike 3): cada execução no BigQuery vem de uma chamada nova (cache por hash de SQL cobre o resto) → 80 × 30 = 2.400 execuções/mês → 1 TiB ÷ 2.400 ≈ **437 MiB por query**.

**Proposta (decisão do Fabio):** teto de **400 MB**, condicionado à cota de 80 chamadas novas/dia. Passam sessões e `UNNEST` em 30 dias; continuam bloqueados `SELECT *` (3,6 GB) e `UNNEST` no período todo (691 MB).

**Amostra para testes:** `tests/fixtures/ga4_sample.parquet` — 1% determinístico de usuários (`MOD(ABS(FARM_FINGERPRINT(user_pseudo_id)), 100) = 0`), 41.083 linhas, 2.713 usuários, todo o período, schema aninhado preservado no DuckDB, 2,0 MiB (zstd). Extração única cobrou 3.584.032.768 bytes (dentro da franquia). Script: `scripts/extract_sample.py`.

## Spike 4 — Transpilação BigQuery → DuckDB
*Pendente (depende da amostra do spike 2).*
