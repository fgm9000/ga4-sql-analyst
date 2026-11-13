# ADR 001 — Stack e tooling

> 🇧🇷 PT-BR | 🇺🇸 [EN](001-stack-and-tooling.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
O PRD v1.0 mira o BTG (Digital Analytics / AI Enablement), que exige "Python avançado", e a ROIT, que pede Python, FastAPI e pandas. O fluxo é request/response (`POST /v1/ask`), sem streaming, com p95 alvo ≤ 8 s (RNF-01). A validação sintática de SQL (RF-02) e a transpilação para banco local nos testes (risco do P8) exigem um parser de SQL multi-dialeto.

## Opções consideradas
| Ramo | Opção | Prós | Contras |
|------|-------|------|---------|
| S1 | **Python 3.12** (padrão) | Requisito literal das vagas-alvo; ecossistema de dados | — |
| S2 | **`uv` + Ruff + mypy `--strict` + Pytest** (padrão) | Catraca já pronta no `ad-copy-grader` | — |
| S3 | **FastAPI** (padrão) | Requisito da ROIT; OpenAPI em `/docs` | — |
| S4 | **Pydantic v2** (padrão) | Saída estruturada do LLM e envelope de resposta tipados | — |
| S2+ | **`sqlglot`** | Parser/AST multi-dialeto, transpila BigQuery → outros dialetos, puro Python | Cobertura incompleta de funções específicas do BigQuery (a validar) |

## Decisão
Python 3.12 + `uv` + Ruff + mypy `--strict` + Pytest + FastAPI + Pydantic v2, com `sqlglot` como dependência central de validação e transpilação de SQL.

**S6 — Provedor de LLM (fechado em 2026-11-13):** Gemini via **Vertex AI**, faixa **Lite**, com o ID exato do modelo em variável de configuração (`settings.py`). Autenticação pela service account de runtime do Cloud Run (sem API key). **Atualização 2026-11-13 (spike 3):** `gemini-2.5-flash-lite` descontinuado (2026-10-20); default **`gemini-3.1-flash-lite`** (GA, descontinuação ≥ 2027-05-07); trocar por `gemini-3.5-flash-lite` se o preço no Vertex for ≤. Preço do Vertex confirmado na Fase 3; se acurácia live < 85%, sobe para a faixa Flash e a cota diária cai para manter RNF-03.

**S5 — Persistência e banco local (fechado em 2026-11-13):**
- Produção: sem banco (serviço sem estado; snapshot versionado no repositório). Cliente oficial `google-cloud-bigquery` para dry-run e execução.
- CI/testes/evals offline: **DuckDB** sobre amostra do dataset em **Parquet** versionada em `tests/fixtures/`. SQL BigQuery transpilado com `sqlglot`, após reescrita própria na AST de `events_*` + `_TABLE_SUFFIX` para filtro sobre `event_date`.
- Comparação de resultados no eval com `pandas.testing` (ordem só com `ORDER BY`, tolerância numérica).
- **Supabase: fora.** Não resolve o CI (rede externa no caminho dos testes) e a produção não tem estado. Reabrir só se S11 exigir rate limit compartilhado.
- Alternativas descartadas: emulador de BigQuery em Docker (projeto comunitário, cobertura parcial, CI mais pesado); sem execução no CI (inviabiliza acurácia por resultado offline).
- Risco: se a transpilação falhar em muitas queries de referência, manter também queries de referência escritas para DuckDB (sem trocar de banco).

### Dados de preço consultados (2026-11-13)
| Modelo | Entrada / 1M tokens | Saída / 1M tokens | Fonte |
|--------|---------------------|-------------------|-------|
| Gemini 2.5 Flash | US$ 0,30 | US$ 2,50 | Agregadores (OpenRouter blog, LLM Reference) — não oficial |
| Gemini 2.5 Flash-Lite | US$ 0,10 | US$ 0,40 | Página oficial de preços do Vertex AI / Gemini API |

Estimativa (hipótese: ~4,5k tokens de entrada + ~0,5k de saída por pergunta): Flash ≈ US$ 16/mês a 200 req/dia (estoura RNF-03); faixa Lite ≈ US$ 4/mês. Fórum do Google cita EOL do Flash-Lite 2.5 em 2026-07-22 — verificar o ciclo de vida antes da Fase 3.

## Justificativa
Nenhum requisito do PRD tensiona o padrão; as vagas-alvo pedem exatamente essa stack. `sqlglot` atende RF-02 (AST) e a transpilação de testes com uma única dependência.

## Divergência do padrão
- **S6:** o Padrão Mestre usa OpenRouter. Este projeto usa Vertex AI. **Motivo:** autenticação keyless pela mesma identidade do Cloud Run (nenhum secret de LLM), aderência ao ecossistema GCP das vagas-alvo (gTech, ROIT) e portfólio com dois provedores atrás do mesmo `ModelClient`. **O que se perde:** troca de modelo entre fabricantes sem mudar código. **Compensação:** `ModelClient` continua sendo `Protocol`; um `OpenRouterClient` pode ser reintroduzido sem tocar em `service.py`.
- Acréscimo: `sqlglot`.

## Consequências
- Positivas: reuso direto da catraca, dos workflows e da estrutura de módulos do `ad-copy-grader`.
- Negativas / dívidas aceitas: dependência de `sqlglot` para segurança (RF-02) — a cobertura de AST para BigQuery precisa de testes adversariais próprios.
- Impacto no plano: Fases 1, 2 e 6.

## Critério de revisão
`sqlglot` falhar em parsear construções comuns do GA4 (`UNNEST(event_params)`, `_TABLE_SUFFIX`) de forma que comprometa RF-02.
