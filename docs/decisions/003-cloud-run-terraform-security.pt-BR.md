# ADR 003 — Cloud Run, Terraform e segurança de acesso

> 🇧🇷 PT-BR | 🇺🇸 [EN](003-cloud-run-terraform-security.md) · Status: Aceita (Portão 2, 2026-11-13) · Data: 2026-11-13

## Contexto
Serviço sem estado, request/response (PRD P4, P7), que acessa BigQuery e Vertex AI na mesma nuvem. As vagas-alvo (BTG, ROIT, gTech) avaliam GCP. O Padrão Mestre usa Cloud Run + WIF/OIDC, com infraestrutura criada por comandos `gcloud`/`gh` no runbook — já provado na demo 1.

## Opções consideradas
| Opção | Prós | Contras |
|-------|------|---------|
| Cloud Run no `fgm9000-portfolio` (padrão) | Mesma nuvem do BigQuery/Vertex; keyless | — |
| Outra plataforma (ex.: Cloudflare Workers) | — | Remove a prova de GCP que as vagas pedem |
| Provisionamento via `gcloud` no runbook (padrão) | Rápido, documentado | Já provado na demo 1; não revisável em PR nem reproduzível |
| **Provisionamento via Terraform** | IaC revisável e reproduzível; repertório novo; scan de IaC no CI | Mais trabalho; bucket GCS para estado; pool WIF compartilhado criado à mão |

## Decisão
Cloud Run no projeto `fgm9000-portfolio` (`--min-instances=0 --max-instances=1 --concurrency=10 --memory=512Mi --cpu=1 --timeout=30`), com os recursos do serviço provisionados por **Terraform** desde a Fase 7.

**Escopo do Terraform (`infra/`):**
- Service account de runtime `ga4-sql-analyst-runtime` com `roles/bigquery.jobUser` e `roles/aiplatform.user` (dataset público já é legível por contas autenticadas).
- Repositório no Artifact Registry.
- Ligação do provider OIDC existente com este repositório GitHub (`principalSet` por `attribute.repository`).
- Pool/provider WIF do projeto compartilhado: **`data source`, somente leitura** — não gerenciado por este repo.
- Estado remoto em bucket GCS com versionamento.

**Fora do Terraform:** deploy da imagem, que continua no `deploy.yml` (`gcloud run deploy` + smoke test em `/health`).

## Justificativa
Cloud Run é confirmado pelo PRD e pelas vagas. O repertório novo está no provisionamento: IaC revisável em PR, reproduzível, e um job a mais de DevSecOps.

## Divergência do padrão
Runbook com comandos manuais → Terraform. **O que se perde:** simplicidade e velocidade do primeiro provisionamento. **Compensação:** o runbook passa a documentar `terraform plan/apply` e o bootstrap do bucket de estado; job de scan de IaC (Checkov ou tfsec, escolha na Fase 7) no `ci.yml`.

## Consequências
- Positivas: infraestrutura auditável; menor privilégio explícito em código.
- Negativas: bootstrap do bucket de estado é manual (uma vez); risco de drift com recursos do projeto compartilhado.
- Impacto no plano: Fases 6 e 7; `docs/deployment-runbook`.

## Critério de revisão
Terraform exigir gerenciar recursos compartilhados do `fgm9000-portfolio` (ex.: pool WIF) para funcionar — nesse caso, reavaliar o escopo para não acoplar as demos.
