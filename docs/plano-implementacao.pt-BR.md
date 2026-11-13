# Plano de Implementação — ga4-sql-analyst

> Base: PRD v1.0 (aprovado 2026-11-13) · ADRs 001–007 (aceitos 2026-11-13) · Padrão Mestre de Engenharia
> Status: Aguardando aprovação (Portão 3)

## Resumo das decisões
| Ramo | Decisão | Segue o padrão? | ADR |
|------|---------|-----------------|-----|
| Base | Python 3.12, `uv`, Ruff, mypy `--strict`, Pytest, FastAPI, Pydantic v2, `sqlglot` | Sim (+`sqlglot`) | 001 |
| Persistência / CI | Sem banco em produção; DuckDB + Parquet nos testes; pandas na comparação | Sim (+DuckDB) | 001 |
| LLM | Gemini via Vertex AI, faixa Lite, keyless | Não (era OpenRouter) | 001 |
| Orquestração | PydanticAI v2 como executor de saída estruturada | Não (era pipeline próprio) | 006 |
| Avaliação | `pydantic_evals` | Não (era Promptfoo) | 004 |
| Hospedagem | Cloud Run + Terraform para os recursos do serviço | Parcial | 003 |
| Frontend | Static Web Playground no GitHub Pages | Sim | 005 |
| Custo/abuso | 5 camadas (rate limit, cache, teto de bytes, teto de tokens, alerta de orçamento) | Sim (+4) | 002 |
| Observabilidade | Logs JSON; OTel → Cloud Trace na fase "depois" | Sim (+OTel) | 007 |

## Regras transversais
- **Autoria:** todos os commits como `Fabio <9202305+fgm9000@users.noreply.github.com>`, **sem trailer `Co-authored-by`** nem menção a agente de IA (Padrão Mestre §1.4 — prevalece sobre qualquer atribuição automática).
- **Git:** `git init` com commit inicial na `main` só com `docs/` aprovados; cada fase em branch `feature/<fase>` e merge após a verificação da fase.
- **Catraca:** a partir da Fase 5, nenhuma fase fecha com Ruff/mypy/cobertura/supressões piorando.
- **Delegação** (CLAUDE.md global): o orquestrador decide e revisa o diff; Sonnet executa o que tem lógica; Haiku executa o mecânico. Delegar só quando o trabalho compensar o custo de contexto do subagente — avisar antes quando não compensar.

## Marco: recorte mínimo apresentável = fim da Fase 7

---

### Fase 1 — Esqueleto, tooling e spikes de risco
- **Objetivo:** estrutura do repo e eliminar os 4 riscos que podem mudar ADRs antes de escrever código de produto.
- **Entregáveis:** `pyproject.toml` (deps com versão exata: `fastapi`, `pydantic`, `pydantic-settings`, `pydantic-ai`, `pydantic-evals`, `sqlglot`, `google-cloud-bigquery`, `duckdb`, `pandas`, `pyarrow`; dev: `ruff`, `mypy`, `pytest`, `pytest-cov`, `pip-audit`), `uv.lock`, `src/ga4_sql_analyst/__init__.py`, `tests/`, `.gitignore`, `LICENSE`, `docs/spikes.pt-BR.md`, `scripts/extract_sample.py`, `tests/fixtures/ga4_sample.parquet`.
- **Spikes (resultado registrado em `docs/spikes.pt-BR.md` e, se mudar decisão, no ADR):**
  1. **mypy × PydanticAI:** `Agent` com `output_type` estruturado + `output_validator` + `GoogleModel` → `uv run mypy --strict spikes/` sem supressão. Falhou → ADR 006 vira plano B.
  2. **Dry-run real:** bytes estimados das perguntas dos 4 cenários e de uma varredura ampla; cobrança mínima por tabela. Define o teto final (ADR 002) e confirma o Cenário 3 (hipótese 1 do PRD). *Requer `gcloud auth application-default login` feito pelo Fabio.*
  3. **Modelo Vertex vigente:** ID do modelo da faixa Lite disponível em `us-central1` e data de descontinuação.
  4. **Transpilação:** 3 queries de referência (incluindo `UNNEST(event_params)`) reescritas e rodando no DuckDB sobre a amostra.
- **Pronto quando:** `uv run pytest` executa (mesmo com 0 testes de produto); `docs/spikes.pt-BR.md` com os 4 resultados e decisão de manter/mudar cada ADR afetado.
- **Commit:** `chore: bootstrap project tooling and risk spikes`
- **Execução:** orquestrador (spikes 1–4, leitura dos resultados) · Haiku (`pyproject`, `.gitignore`, `LICENSE`) · Fabio (autenticação local no GCP).
- **Base:** ADRs 001, 002, 006.

### Fase 2 — Contratos e domínio puro
- **Entregáveis:** `models.py` (requisição, saída do LLM, envelope de resposta), `domain.py` (C01–C06, âncora de data, reescrita `_TABLE_SUFFIX`), testes unitários exaustivos com casos adversariais de AST.
- **Pronto quando:** `uv run pytest tests/test_domain.py tests/test_models.py --cov=src` → 100% das linhas de `domain.py` e `models.py`; `uv run mypy --strict src tests` → 0 erros.
- **Commit:** `feat: add data contracts and deterministic SQL guardrails`
- **Execução:** orquestrador (design de C01–C06 e casos adversariais) · Sonnet (implementação e testes de `domain.py`) · Haiku (`models.py` a partir dos contratos do ADR 002).
- **Base:** ADR 002, RF-02, RF-04, RF-06.

### Fase 3 — Warehouse, LLM e orquestração
- **Entregáveis:** `warehouse.py` (`Protocol` + `BigQueryWarehouse` + `DuckDbWarehouse`), `prompt.py` (PT/EN, isolamento XML), `llm.py` (agentes PydanticAI atrás de `SqlGenerator`/`Summarizer`), `service.py` (8 passos, status, degradação), `snapshot/` (4 cenários validados) e `FunctionModel` alimentado pelo snapshot.
- **Pronto quando:** `uv run pytest` com `models.ALLOW_MODEL_REQUESTS = False` cobre os 4 cenários + LLM fora + BigQuery fora contra DuckDB; cobertura 100% em `src/`.
- **Commit:** `feat: add warehouse adapters, PydanticAI generation and pipeline`
- **Execução:** orquestrador (fronteiras e `service.py`) · Sonnet (`warehouse.py`, `llm.py`, testes) · Haiku (`prompt.py` a partir do template aprovado).
- **Base:** ADRs 001, 002, 006; RF-01, RF-05, RF-06, P8.

### Fase 4 — API, limites, cache e configuração
- **Entregáveis:** `settings.py` (`Annotated[..., NoDecode]` em listas), `limits.py`, `cache.py`, `api.py` (`GET /` → `/docs`, `/health` + `/healthz`, `POST /v1/ask`, CORS para o GitHub Pages, log JSON sem PII), `create_app(...)` com injeção.
- **Pronto quando:** testes de API com `TestClient` cobrem 200 `answered`/`blocked`/`unavailable`, 422, 429 e cache hit; `uv run uvicorn ... --factory` responde `/health` local.
- **Commit:** `feat: expose ask endpoint with rate limiting and cache`
- **Execução:** Sonnet (implementação e testes) · orquestrador (revisão).
- **Base:** ADR 002 (S11), RNF-04, RNF-07.

### Fase 5 — Catraca e esteira DevSecOps
- **Entregáveis:** `scripts/quality_baseline.py`, `scripts/quality_check.py`, `quality-baseline.json` (100,0% cobertura, 0 supressões), `.github/workflows/ci.yml` (`ratchet`, `security`, `sast`, `secrets`, `eval-offline` mínimo: só bloqueio adversarial + âncora como gate), `codeql.yml`, `.github/dependabot.yml` (pip, github-actions).
- **Pronto quando:** `uv run python scripts/quality_check.py` → exit 0 local; todos os jobs verdes no primeiro push.
- **Commit:** `ci: add quality ratchet and DevSecOps pipeline`
- **Execução:** Haiku (portar scripts e workflows do `ad-copy-grader`, trocando o job Promptfoo por `eval-offline`) · orquestrador (revisão do diff e primeiro push).
- **Base:** Padrão Mestre §2 e §4; ADR 004.

### Fase 6 — Infraestrutura (Terraform), container e deploy
- **Entregáveis:** `infra/` (SA de runtime com `bigquery.jobUser` e `aiplatform.user`, Artifact Registry, binding WIF por repositório, `data source` do pool compartilhado, alerta de orçamento, backend GCS), `Dockerfile` multi-stage não-root, `.dockerignore` (`!README.md`), `.github/workflows/deploy.yml` (smoke test em `/health`), job `iac-scan` no `ci.yml`, Dependabot para Terraform.
- **Pronto quando:** `terraform plan` sem mudanças após `apply`; `iac-scan` verde; deploy verde com smoke test; `POST /v1/ask` do Cenário 1 responde em produção.
- **Commit:** `feat: provision service infrastructure with Terraform and deploy to Cloud Run`
- **Execução:** orquestrador (escopo IAM, revisão do `plan`) · Sonnet (módulos Terraform, Dockerfile, workflow) · Fabio (bootstrap do bucket de estado, `terraform apply`, permissão de billing).
- **Base:** ADR 003; ADR 002 (camada 5).

### Fase 7 — Static Web Playground
- **Entregáveis:** `web/index.html`, `web/app.js`, `web/styles.css` (Tailwind pré-compilado), `web/examples.json` (4 cenários), banner de 3 passos, card do caminho completo com selos, medidor de bytes, aviso de cache e cold start, botão "Tentar injeção", destaque SQL local, seção "Under the Hood", `pages.yml`.
- **Pronto quando:** página no GitHub Pages carrega sem nenhuma requisição a CDN (aba Network); os 4 cenários funcionam contra a API em produção e, com a API fora, pelo snapshot; EN/PT alternam sem recarregar.
- **Commit:** `feat: add bilingual static playground`
- **Execução:** Sonnet (UI) · orquestrador (revisão contra a regra dos 30 s).
- **Base:** ADR 005; PRD §5.
- **➡ Marco: recorte mínimo apresentável.** Link pronto para demonstração pública e portfólio.

### Fase 8 — Evals completas e eval live
- **Entregáveis:** `evals/dataset.py` (~20 perguntas PT/EN com query de referência + adversariais + âncora), evaluators `ResultEquivalence`, `SummaryNumbersGrounded`, `DateAnchorCorrect`, report evaluators (precisão/recall do bloqueio, acurácia), runner das 3 rodadas + relatório comparativo em Markdown, `eval-live.yml`, `tests/test_evals.py`.
- **Pronto quando:** `eval-offline` no CI com as 4 métricas; `eval-live` manual publica o relatório como artefato; acurácia live medida e registrada (hipótese 4 do PRD confirmada ou ajuste de modelo/cota feito).
- **Commit:** `feat: add result-equivalence evals and live evaluation workflow`
- **Execução:** orquestrador (dataset canônico e queries de referência) · Sonnet (evaluators, runner, workflow).
- **Base:** ADR 004; PRD §8.

### Fase 9 — Observabilidade com OpenTelemetry
- **Entregáveis:** instrumentação OTel dos 8 passos com exportação para Cloud Trace, `roles/cloudtrace.agent` no Terraform, evaluators de span no eval live.
- **Pronto quando:** trace de uma requisição mostra os 8 passos no Cloud Trace; p95 do RNF-01 medido e registrado. Se os pontos de verificação do ADR 007 falharem, a fase é encerrada registrando a decisão de ficar só com logs.
- **Commit:** `feat: add OpenTelemetry tracing to Cloud Trace`
- **Execução:** orquestrador (verificação dos 2 pontos do ADR 007) · Sonnet (instrumentação).
- **Base:** ADR 007; RNF-01.

### Fase 10 — Documentação bilíngue e publicação
- **Entregáveis:** `README.md` + `README.pt-BR.md` (diagrama Mermaid, links, explicação das escolhas de tooling vs. demo 1), `docs/architecture*.md`, `docs/deployment-runbook*.md` (Terraform, bootstrap, troubleshooting), versões EN do PRD e dos 7 ADRs a partir dos `.pt-BR.md` aceitos.
- **Pronto quando:** todos os links cruzados resolvem; todos os workflows verdes; repo público.
- **Commit:** `docs: add bilingual documentation and EN ADRs`
- **Execução:** Sonnet (tradução EN a partir dos PT aceitos) · Haiku (links cruzados) · orquestrador (README e revisão final).
- **Base:** Padrão Mestre §6.

## Paralelização
- Após a Fase 2: **Fase 6 (Terraform/Dockerfile)** e **Fase 7 (HTML/CSS do playground contra o snapshot)** podem andar em paralelo com as Fases 3–4 — arquivos disjuntos (`infra/`, `web/` vs. `src/`).
- Fase 8 (dataset e queries de referência) pode começar junto com a Fase 3, usando o DuckDB.

## Riscos e pontos frágeis
| Risco | Origem | Mitigação | Gatilho de revisão |
|-------|--------|-----------|--------------------|
| PydanticAI exige supressão de tipo | ADR 006 | Spike na Fase 1; plano B = pipeline próprio | mypy falha sem `# type: ignore` |
| Dataset cabe abaixo do teto | PRD hipótese 1, ADR 002 | Teto propositalmente baixo e exibido no playground | Dry-run da Fase 1 |
| Cobrança mínima por tabela × 92 tabelas | ADR 002 | Medir no dry-run; forçar filtro de `_TABLE_SUFFIX` | Custo por query > teto |
| Modelo Lite descontinuado | ADR 001 | ID em `settings.py`; confirmar na Fase 1 | Página de ciclo de vida do Vertex |
| Transpilação BigQuery → DuckDB falha | ADR 001 | Queries de referência também em DuckDB | Spike 4 / Fase 8 |
| Acurácia live < 85% | PRD hipótese 4 | Subir faixa de modelo e baixar cota | 1º eval live |
| US$ 5/mês não basta | PRD hipótese 3, RNF-03 | Cache + cota; alerta de orçamento | Alerta de 50% |
| Permissão de billing para o alerta via Terraform | ADR 002 | Alerta manual documentado | Fase 6 |
| OTel exige Logfire SaaS ou estoura custo | ADR 007 | Ficar só com logs JSON | Fase 9 |

## Fora deste plano
Conversa multi-turno, gráficos/dashboard/Looker Studio, outros datasets, login de usuário, escrita no warehouse, Turnstile, Supabase, frameworks de agente com tools.
