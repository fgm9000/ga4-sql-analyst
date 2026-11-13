# ADR 004 — Estratégia de avaliação do LLM

> 🇧🇷 PT-BR | 🇺🇸 [EN](004-llm-evaluation-strategy.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
O PRD (seção 8) define 4 métricas: acurácia por resultado, bloqueio adversarial (gate de CI), números do resumo sem lastro e âncora de data; mais a comparação entre 3 variantes (só prompt, pipeline completo, modo degradado). A acurácia por resultado executa SQL e compara DataFrames (`pandas.testing`), lógica naturalmente em Python. O Padrão Mestre usa Promptfoo, que já está provado na demo 1 (`ad-copy-grader`).

## Opções consideradas
| Opção | Prós | Contras |
|-------|------|---------|
| A — Promptfoo 0.109.0 (padrão) | Mais conhecido; viewer lado a lado pronto | Já provado na demo 1 (sem ganho de repertório); YAML fora da catraca; Node/npx no CI; bug do SQLite exige `--no-write`; lógica real ficaria em `provider.py` de qualquer forma |
| B — `pydantic_evals` | Datasets e evaluators em Python tipado, dentro do mypy `--strict` e da cobertura; sem Node no CI; `PrecisionRecallEvaluator`/`ConfusionMatrixEvaluator` medem também falso bloqueio; integra com `FunctionModel` (ADR 006) | Menos conhecido; sem viewer lado a lado (relatório comparativo é nosso); API recente (v2, 2026-06-23); mesmo ecossistema do framework de LLM |
| C — Ambos | — | Dois frameworks de eval no mesmo repositório: excesso |

## Decisão
`pydantic_evals` no lugar do Promptfoo, com versão exata fixada no `uv.lock`.

## Justificativa
- Repertório: demo 1 com Promptfoo, demo 2 com `pydantic_evals` — comparação por experiência própria.
- A métrica central (equivalência de resultado) é código Python; com `pydantic_evals` ela é um `Evaluator` tipado e coberto pela catraca.
- O guardrail vira classificador medido nos dois sentidos: recall (ataques bloqueados = 100%, gate) e precisão (perguntas legítimas bloqueadas por engano).
- Fonte consultada: documentação oficial PydanticAI v2.0.0 via Context7, 2026-11-13.

## Desenho
- `evals/dataset.py` (ou YAML versionado): ~20 perguntas canônicas PT/EN com query de referência + casos adversariais + casos de âncora de data.
- Evaluators próprios: `ResultEquivalence` (pandas, tolerância numérica, ordem só com `ORDER BY`), `SummaryNumbersGrounded`, `DateAnchorCorrect`.
- Report evaluators: `PrecisionRecallEvaluator` / `ConfusionMatrixEvaluator` para bloqueio; `ReportEvaluator` de acurácia agregada.
- 3 variantes = 3 rodadas do mesmo dataset (`prompt_only`, `full_pipeline`, `degraded`); script gera relatório comparativo em Markdown.
- CI (`eval-offline`): `FunctionModel` alimentado pelo snapshot + DuckDB; falha se bloqueio adversarial < 100% ou âncora < 100%.
- Live (`eval-live.yml`, `workflow_dispatch`): Vertex AI + BigQuery reais; relatório publicado como artefato.
- Fora: evaluators baseados em spans (exigem OTel/Logfire) — reabrir só se S13 adotar tracing.

## Divergência do padrão
Promptfoo → `pydantic_evals`. **O que se perde:** viewer pronto lado a lado e reconhecimento imediato da ferramenta. **Compensação:** relatório comparativo em Markdown como artefato da Action e seção no README explicando a escolha. O job `eval-fake` do `ci.yml` passa a se chamar `eval-offline` e roda via `uv run`, sem `npx`.

## Consequências
- Positivas: eval dentro da catraca; CI sem Node; métrica de falso bloqueio.
- Negativas: relatório comparativo é código nosso; acoplamento ao ecossistema Pydantic.
- Impacto no plano: Fases 5 e 6; `tests/test_evals.py`.

## Critério de revisão
Quebra de API do `pydantic_evals` que exija supressão de tipo ou reescrita relevante dos evaluators.
