# ADR 007 — Observabilidade: logs JSON + OpenTelemetry no Cloud Trace

> 🇧🇷 PT-BR | 🇺🇸 [EN](007-observability-opentelemetry.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
RNF-01 (p95 ≤ 8 s) precisa de medição por passo (LLM, dry-run, query). O ADR 004 deixou de fora os evaluators baseados em spans por falta de tracing. O padrão (logs JSON sem PII) já foi provado na demo 1.

## Opções consideradas
| Opção | Prós | Contras |
|-------|------|---------|
| A — Só logs JSON (padrão) | Simples | Sem latência por passo; sem repertório novo |
| **B — OpenTelemetry → Cloud Trace** | Nativo do GCP; latência por passo; habilita span evaluators no eval live | Dependência e configuração extras; pontos não verificados (abaixo) |
| C — Logfire (SaaS) | Integração nativa com PydanticAI | Serviço externo fora do GCP; mais um secret |

## Decisão
Logs JSON de linha única sem PII desde o recorte mínimo (padrão). OpenTelemetry com exportação para o Cloud Trace na fase "depois", junto com o eval live.

## Pontos a verificar na fase de OTel
1. PydanticAI exporta spans OpenTelemetry para destino arbitrário sem exigir a nuvem do Logfire.
2. Custo do Cloud Trace dentro da franquia gratuita, compatível com RNF-03.

Se qualquer um falhar: permanece a opção A e este ADR é atualizado.

## Divergência do padrão
Acréscimo (não substituição): tracing OTel. Logs JSON sem PII permanecem.

## Consequências
- Positivas: latência por passo mensurável; evaluators de span (ex.: "houve nova tentativa?", "chamada LLM < 2 s").
- Impacto no plano: fase "depois"; Terraform ganha permissão `roles/cloudtrace.agent` na SA de runtime.

## Critério de revisão
Os pontos 1 ou 2 acima não se confirmarem.
