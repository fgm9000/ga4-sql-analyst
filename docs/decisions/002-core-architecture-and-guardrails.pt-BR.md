# ADR 002 — Arquitetura central e guardrails

> 🇧🇷 PT-BR | 🇺🇸 [EN](002-core-architecture-and-guardrails.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
Tese do PRD: o LLM gera SQL e resumo; o código tem autoridade sobre segurança, custo, período e números (RF-02 a RF-06). Fluxo fixo de 8 passos (P4), degradação por snapshot (P8), teto de US$ 5/mês (RNF-03) e dataset congelado (nov/2020–jan/2021).

## Decisão

### Camadas (SRP do Padrão Mestre, ajustado pelos ADRs 001 e 006)
| Módulo | Responsabilidade |
|--------|------------------|
| `models.py` | Contratos Pydantic: requisição, saída estruturada do LLM (`sql`, `tables`, `intent`), envelope de resposta (`status`, `period`, `checks`, `rows`, `summary`, `degraded`) |
| `sql_rules.py` | Regras de AST de C01–C03 (reexportadas por `domain.py`) |
| `domain.py` | Lógica pura, sem I/O: validação de AST (`sqlglot`), âncora de data, reescrita `_TABLE_SUFFIX` → DuckDB, conferência de números do resumo |
| `prompt.py` | Templates PT/EN, schema do dataset no prompt, isolamento XML do texto do usuário |
| `llm.py` | Adaptadores PydanticAI (`SqlGenerator`, `Summarizer`) com `output_validator` chamando `domain.py` |
| `warehouse.py` | `Protocol` `Warehouse` com `dry_run()` e `execute()`; implementações BigQuery e DuckDB |
| `service.py` | Orquestração dos 8 passos, status e degradação |
| `cache.py` | Cache em memória por pergunta normalizada + idioma e por hash do SQL |
| `limits.py` | `StrictRateLimiter` por IP + cota diária |
| `settings.py` | `pydantic-settings` (ID do modelo, teto de bytes, cotas) |
| `api.py` | `GET /` → `/docs`, `GET /health` + `/healthz`, `POST /v1/ask`, `POST /v1/validate` (RF-08: só C01–C03, sem LLM nem execução; não consome a cota de LLM, só o rate limit por IP) |

### Verificações (autoridade do código)
| ID | Verificação | Ação em falha |
|----|-------------|---------------|
| C01 | AST: um único `SELECT`, sem DML/DDL; **sem funções de identidade/ambiente/conexão externa** (`SESSION_USER`, `CURRENT_USER`, `EXTERNAL_QUERY`, `ML.*`, `AI.*`, `KEYS.*`, `AEAD.*`, `@@variáveis`...) — achado na revisão da Fase 2: leitura pura ainda vaza a identidade da SA | Nova tentativa (1x) → `blocked` |
| C02 | Tabelas somente `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` (ou diárias `events_YYYYMMDD`); **ao menos 1 tabela permitida** (`no_allowed_table`) | Nova tentativa (1x) → `blocked` |
| C03 | `LIMIT` ausente → injetado (máx. 100) | Corrige, não bloqueia |
| C04 | Âncora de data: relativas resolvidas contra 2021-01-31 | Determinístico, antes do LLM |
| C05 | Dry-run: bytes estimados ≤ teto | `blocked` (sem nova tentativa) |
| C06 | Números do resumo existem no resultado | Remove/marca números sem lastro |

### Semântica de status
`answered` | `blocked` (200, com motivo e SQL recusado) | `unavailable` (LLM fora, pergunta livre). `degraded: true` para snapshot ou BigQuery fora. `4xx` só para entrada inválida; `5xx` só para falha real.

### Proteção de custo e abuso (S11, fechado em 2026-11-13)
1. Rate limit: 5 req/min por IP, 200 req/dia global e **máx. 80 req/dia com chamada nova ao LLM** (memória; válido porque `max-instances=1`).
2. Cache em memória sem expiração além do restart — seguro **porque o dataset é congelado**. Com dados vivos, exigiria TTL amarrado à atualização do warehouse.
3. `maximum_bytes_billed`: **400 MB** (fechado em 2026-11-13, spike 2): ≤ 80 execuções novas/dia × 30 = 2.400/mês → 1 TiB ÷ 2.400 ≈ 437 MiB. Orçamento contabiliza `max(bytes_estimados, 10 MiB)` (mínimo cobrado por query, medido).
4. `max_tokens` de saída limitado por chamada; pergunta com tamanho máximo.
5. Alerta de orçamento no Cloud Billing via Terraform (50/90/100% de US$ 5). Hipótese: permissão na conta de faturamento; senão, manual e documentado no runbook.
- Fora: Turnstile (atrito nos 30 s; camadas 1–3 bastam). Supabase: fora (rate limit não precisa de store compartilhado).
- Verificado na Fase 1 (spike 2): mínimo de 10 MiB cobrado **por query**, não por tabela; 92 tabelas não multiplicam o mínimo.

## Justificativa
Cada verificação verificável é código; o LLM só julga o semântico (tradução da pergunta e redação). As camadas de custo vão do request à conta do GCP, e a última vale mesmo com bug no código.

## Divergência do padrão
Nenhuma estrutural. Acréscimos: `warehouse.py` e `cache.py`; `parser.py` absorvido pelo PydanticAI (ADR 006).

## Consequências
- Impacto no plano: Fases 2, 3 e 4.

## Critério de revisão
Teto de bytes real tornar o Cenário 3 inviável (hipótese 1 do PRD) ou o cache não segurar o custo dentro do RNF-03.
