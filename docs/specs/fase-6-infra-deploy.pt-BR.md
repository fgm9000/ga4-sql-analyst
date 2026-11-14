# Especificação da Fase 6 — Terraform, container e deploy

> Base: ADR 003, ADR 002 (camada 5 — alerta de orçamento), Padrão Mestre §4.4. Escrita pelo orquestrador em 2026-11-14 após inspecionar o projeto `fgm9000-portfolio`.

## Fatos levantados (não mudar)
- Projeto: `fgm9000-portfolio` (número `<PROJECT_NUMBER>`), região `us-central1`. Billing account `XXXXXX-XXXXXX-XXXXXX` (o Fabio é `roles/billing.admin`).
- Pool WIF compartilhado: `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool`. O provider existente `github-provider` tem `attributeCondition = assertion.repository == 'fgm9000/ad-copy-grader' && assertion.ref == 'refs/heads/main'` — **não aceita este repo e NÃO deve ser alterado** (é da demo 1). Mapeamento: `google.subject=assertion.sub`, `attribute.repository=assertion.repository`, `attribute.ref=assertion.ref`; issuer `https://token.actions.githubusercontent.com`.
- Estado remoto: bucket `gs://fgm9000-portfolio-tfstate` (já criado, versionado, privado). Prefixo deste repo: `ga4-sql-analyst`.
- Padrão de nomes da demo 1: `<servico>-runtime@`, `<servico>-deployer@`, Artifact Registry `<servico>` em `us-central1`.

## Decisão do orquestrador (registrar no ADR 003)
Em vez de alterar o provider compartilhado, este repo cria **o próprio provider** no mesmo pool: `github-ga4-sql-analyst`, com condição `assertion.repository == 'fgm9000/ga4-sql-analyst' && assertion.ref == 'refs/heads/main'`. O pool continua `data source` (somente leitura). Nenhum recurso da demo 1 é tocado.

## Tarefa A — Terraform em `infra/` (Sonnet)
Arquivos: `infra/versions.tf`, `infra/backend.tf`, `infra/variables.tf`, `infra/main.tf` (ou dividido por tema: `iam.tf`, `artifact_registry.tf`, `wif.tf`, `budget.tf`, `apis.tf`), `infra/outputs.tf`, `infra/terraform.tfvars.example`, `infra/README.md` (curto, em inglês: o que cada recurso faz e os comandos).
- `required_version >= 1.9`; provider `hashicorp/google` com versão fixada **exata** (`= x.y.z`) — use a mais recente estável que `terraform init` resolver e fixe; commitar `.terraform.lock.hcl`.
- Provider com `user_project_override = true` e `billing_project = var.project_id` (necessário para a API de budgets com credenciais de usuário).
- Variáveis: `project_id` (default `fgm9000-portfolio`), `region` (`us-central1`), `github_repository` (`fgm9000/ga4-sql-analyst`), `service_name` (`ga4-sql-analyst`), `billing_account_id` (sem default; valor real no `terraform.tfvars`, que é **ignorado pelo git** — adicionar ao `.gitignore`), `budget_amount_usd` (`5`), `budget_alert_emails` (lista, default vazia — sem e-mail, o alerta vai para os admins de billing).
- APIs (`google_project_service`, `disable_on_destroy = false`): `run`, `artifactregistry`, `iamcredentials`, `sts`, `bigquery`, `aiplatform`, `billingbudgets`, `cloudresourcemanager`.
- Service accounts:
  - `ga4-sql-analyst-runtime`: `roles/bigquery.jobUser` e `roles/aiplatform.user` no projeto. Nada mais.
  - `ga4-sql-analyst-deployer`: `roles/run.developer` no projeto; `roles/iam.serviceAccountUser` **apenas na SA de runtime** (`google_service_account_iam_member`); `roles/artifactregistry.writer` **apenas no repositório** deste serviço.
- WIF: `data "google_iam_workload_identity_pool" "github"` (pool `github-pool`) + `google_iam_workload_identity_pool_provider` `github-ga4-sql-analyst` (mapeamento igual ao existente, condição deste repo). `roles/iam.workloadIdentityUser` na SA deployer para `principalSet://iam.googleapis.com/${pool.name}/attribute.repository/${var.github_repository}`.
- Artifact Registry `ga4-sql-analyst` (docker, `us-central1`), labels `app = ga4-sql-analyst`, **cleanup policies**: manter as 5 versões mais recentes (`keep`, `most_recent_versions { keep_count = 5 }`) e apagar o resto com mais de 7 dias (`delete`, `condition { older_than = "604800s" }`); `cleanup_policy_dry_run = false`.
- Budget `google_billing_budget`: nome `ga4-sql-analyst — fgm9000-portfolio`, filtro `projects = ["projects/${project_number}"]` (obter com `data "google_project"`), valor `budget_amount_usd` USD, thresholds 0.5, 0.9, 1.0 (`CURRENT_SPEND`). Comentário no código: o filtro é o projeto inteiro (inclui a demo 1), o que torna o alerta conservador.
- Outputs: `workload_identity_provider` (nome completo do provider), `deployer_service_account`, `runtime_service_account`, `artifact_registry_repository` (URL `us-central1-docker.pkg.dev/<proj>/<repo>`).
- Verificação local obrigatória (sem `apply`, sem `plan` contra o GCP real se não quiser — mas `init` usa o backend GCS real, isso é permitido):
  ```
  TF=terraform
  cd infra && $TF init && $TF fmt -check -recursive && $TF validate && $TF plan -var="billing_account_id=XXXXXX-XXXXXX-XXXXXX" -out=/tmp/ga4.tfplan
  ```
  O `plan` usa as credenciais ADC do Fabio (já configuradas) — **NÃO rode `apply`**. Cole o resumo do plan (`Plan: N to add, 0 to change, 0 to destroy`). Qualquer `to change`/`to destroy` em recurso existente = PARE e relate.
- Scan de IaC: rode **Checkov** localmente (`uvx checkov@<versão exata> -d infra --quiet --compact`; escolha uma versão publicada há ≥ 2 semanas e cite-a). Corrija achados reais; para achados que não se aplicam, use o mecanismo de skip **por recurso com justificativa** do Checkov (`#checkov:skip=CKV_...:<motivo>`) — liste cada skip na resposta para revisão (o orquestrador decide se aceita; o grep de supressões da catraca só varre `.py`).
- Acrescente ao `.github/workflows/ci.yml` o job `iac-scan` com a mesma versão do Checkov (via `uvx` após `astral-sh/setup-uv@v5`, ou a imagem oficial com tag exata). NÃO altere os outros jobs.

## Tarefa B — Container e workflow de deploy (Haiku)
- `Dockerfile`: porte o da demo 1 (`demo-1/Dockerfile`) trocando o CMD por `uvicorn ga4_sql_analyst.api:app_factory --factory --host 0.0.0.0 --port ${PORT:-8080}`. Mantenha multi-stage, `uv sync --frozen --no-dev --no-editable`, usuário não-root 10001. Use a mesma imagem do uv da demo 1.
- `.dockerignore`: ignorar `.venv`, `.git`, `tests`, `spikes`, `evals`, `docs`, `infra`, `web`, `scripts`, caches, `*.parquet`, mas com `!README.md`.
- `.github/workflows/deploy.yml`: porte o da demo 1 trocando `SERVICE_NAME`/`ARTIFACT_REPO` para `ga4-sql-analyst`, a SA de runtime para `ga4-sql-analyst-runtime@...`, removendo `--set-secrets` (não há secret: Vertex é keyless), `--timeout=60` (latência live medida de 12–15 s por pergunta nova), e `--set-env-vars="GA4_GCP_PROJECT=${{ vars.GCP_PROJECT_ID }},GA4_CORS_ORIGINS=${{ vars.GA4_CORS_ORIGINS || 'https://fgm9000.github.io' }},PYDANTIC_AI_NO_BANNER=1"`. Mantenha o check de variáveis, o auth WIF e o smoke test em `/health`. Acrescente um segundo smoke test: `POST /v1/validate` com `{"sql":"DELETE FROM x"}` deve conter `"is_valid":false`.
- `.github/dependabot.yml`: acrescentar ecossistemas `terraform` (diretório `/infra`) e `docker` (diretório `/`), semanais.
- Verificação: `docker` pode não estar rodando localmente — não é obrigatório buildar. Valide os YAML com `uv run python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/deploy.yml .github/dependabot.yml` (se `yaml` não existir no venv, use `uvx --from pyyaml python -c ...`).

## Fora desta fase
Configurar variáveis do repositório no GitHub, `terraform apply` e o primeiro deploy — o orquestrador faz.
