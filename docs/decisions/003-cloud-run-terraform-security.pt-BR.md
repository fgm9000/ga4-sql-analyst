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

## Atualização da Fase 6 (2026-11-14)
- **Provider OIDC próprio.** O provider compartilhado `github-provider` só aceita `fgm9000/ad-copy-grader`. Em vez de alterá-lo (recurso da demo 1), este repo cria `github-ga4-sql-analyst` no mesmo pool, com condição `sub`, `repository` e `ref == refs/heads/main`. O pool continua `data source`; nenhum recurso da demo 1 foi tocado.
- **Menor privilégio no deploy.** A demo 1 usa `roles/run.admin` no projeto. Aqui o deployer tem `roles/run.developer` (sem `setIamPolicy`); por isso o deploy usa só `--no-invoker-iam-check` (acesso público sem binding de IAM), sem `--allow-unauthenticated`. `iam.serviceAccountUser` só na SA de runtime e `artifactregistry.writer` só no repositório.
- **Orçamento em BRL.** A conta de faturamento é em reais e a API de budgets rejeita outra moeda: R$ 28 ≈ US$ 5 (R$ 5,56/US$, fechamento de 2026-11-11). Filtro = projeto inteiro (inclui a demo 1), alertas em 50/90/100%.
- **Checkov 3.4.0** no CI, com 2 skips justificados no código: `CKV_GCP_84` (CSEK no Artifact Registry; imagens públicas, chave gerenciada pelo Google basta) e `CKV_GCP_125` (falso positivo: o Checkov não resolve a variável dentro da condição do `sub`).
- **Estado** em `gs://fgm9000-portfolio-tfstate` (prefixo `ga4-sql-analyst`), privado e versionado.
- **Condição OIDC sem `sub` (2026-11-14, primeiro deploy).** A condição com `assertion.sub == 'repo:<repo>:ref:refs/heads/main'` recusou o token de um job disparado por `workflow_run` (`unauthorized_client`). Ficou igual à da demo 1: `repository` + `ref == refs/heads/main`.
- **Criação única do serviço pela conta dona (bootstrap).** Ligar `invoker_iam_disabled` exige `run.services.setIamPolicy`, que o `run.developer` não tem. Em vez de dar `run.admin` ao deployer, o serviço foi criado uma vez pelo Fabio (owner) já com `--no-invoker-iam-check`; os deploys seguintes do GitHub mantêm a mesma configuração e não precisam de `setIamPolicy`. Comando no runbook (`infra/README.md`).
