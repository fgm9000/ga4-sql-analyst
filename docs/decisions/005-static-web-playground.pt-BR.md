# ADR 005 — Static Web Playground

> 🇧🇷 PT-BR | 🇺🇸 [EN](005-static-web-playground.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
A regra dos 30 segundos exige que a demo abra instantaneamente. As vagas-alvo (BTG, ROIT, gTech) avaliam dados, Python e GCP, não frontend. O padrão (HTML + Vanilla JS + Tailwind pré-compilado no GitHub Pages) já foi provado na demo 1.

## Opções consideradas
| Opção | Repertório novo | Problema |
|-------|-----------------|----------|
| A — Static Web Playground (padrão) | Não | — (melhor ajuste à regra dos 30 s) |
| B — React + Vite | Não (já provado no Tráfego Pago AI) | Build e dependências sem ganho de evidência |
| C — Streamlit | Sim | Segundo serviço com cold start; i18n e CSP difíceis; duas UIs |
| D — HTMX + Jinja no FastAPI | Sim | Sai do GitHub Pages; UI sofre com o cold start da API |

## Decisão
Static Web Playground no GitHub Pages, conforme o padrão.

## Justificativa
O repertório novo desta demo está no lado de dados e IA (BigQuery, PydanticAI, `pydantic_evals`, Terraform, DuckDB). No frontend, o critério é velocidade e clareza.

## Componentes específicos
- Card do caminho completo: pergunta → SQL com destaque de sintaxe → verificações com selos de autoridade (Código / LLM) → tabela → resumo.
- Medidor de bytes estimados vs. teto (Cenário 3).
- Aviso de "resposta em cache" (`degraded: true`) e de cold start (RNF-05).
- Botão "Tentar injeção" (Cenário 4).
- Destaque de sintaxe SQL por função local pequena, sem biblioteca nem CDN (CSP estrita).

## Divergência do padrão
Nenhuma — segue o padrão.

## Consequências
- Impacto no plano: Fase 8.

## Critério de revisão
Fluxo de interação exigir estado complexo ou múltiplas telas.
