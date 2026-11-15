# Runbook Operacional e de Deploy — ga4-sql-analyst

> 🇧🇷 PT-BR | 🇺🇸 [EN](deployment-runbook.md)

Este runbook orienta o provisionamento de infraestrutura, deploy automatizado sem chaves estáticas via Workload Identity, bootstrap único do serviço e resolução de incidentes operacionais do `ga4-sql-analyst`.

---

## 1. Arquitetura e Modelo de Segurança

A infraestrutura é gerenciada com **Terraform** no projeto Google Cloud `fgm9000-portfolio` (`us-central1`), enquanto os deploys da aplicação são automatizados pelo **GitHub Actions** (`deploy.yml`).

### Princípio do Menor Privilégio (IAM)

Diferente de tutoriais comuns que concedem privilégios amplos de administração, este projeto aplica segregação estrita:

- **Service Account de Execução (`ga4-sql-analyst-runtime`):**
  - `roles/bigquery.jobUser` (pode apenas executar jobs de consulta contra datasets públicos).
  - `roles/aiplatform.user` (pode apenas invocar modelos fundacionais da Vertex AI).
  - Zero permissões de escrita em banco, zero privilégios de computação e zero acesso a outros recursos do projeto.
- **Service Account de Deploy (`ga4-sql-analyst-deployer`):**
  - `roles/run.developer` (pode atualizar imagem e configurações no Cloud Run).
  - `roles/iam.serviceAccountUser` (restrita exclusivamente à SA de runtime).
  - `roles/artifactregistry.writer` (escopo restrito estritamente ao repositório Docker `ga4-sql-analyst`).
  - **Sem `setIamPolicy` ou `run.admin`:** Não pode modificar bindings de IAM do projeto nem abrir serviços arbitrariamente.

---

## 2. Provisionamento de Infraestrutura (Terraform)

### Passo 2.1: Bucket de Estado Remoto

```bash
gcloud storage buckets create gs://fgm9000-portfolio-tfstate \
  --project=fgm9000-portfolio \
  --location=us-central1 \
  --uniform-bucket-level-access \
  --public-access-prevention

gcloud storage buckets update gs://fgm9000-portfolio-tfstate \
  --versioning \
  --update-labels=purpose=terraform-state
```

### Passo 2.2: Execução do Terraform

```bash
cd infra

# Copie o exemplo e preencha o ID da sua conta de faturamento (ignorado pelo git)
cp terraform.tfvars.example terraform.tfvars
# Edite o terraform.tfvars definindo o billing_account_id

terraform init
terraform fmt -check -recursive
terraform validate
terraform plan
terraform apply
```

### Passo 2.3: Configuração das Variáveis do Repositório no GitHub

Defina as saídas do Terraform como variáveis no repositório GitHub (sem necessidade de secrets estáticos):

```bash
gh variable set GCP_PROJECT_ID     -R fgm9000/ga4-sql-analyst -b fgm9000-portfolio
gh variable set GCP_WIF_PROVIDER   -R fgm9000/ga4-sql-analyst -b "$(terraform output -raw workload_identity_provider)"
gh variable set GCP_SERVICE_ACCOUNT -R fgm9000/ga4-sql-analyst -b "$(terraform output -raw deployer_service_account)"
```

---

## 3. Bootstrap Único do Cloud Run

Como a service account de deploy possui `roles/run.developer` (e não possui `run.services.setIamPolicy`), tornar o serviço público com `--no-invoker-iam-check` não pode ser feito pelo pipeline de CI.

O serviço é criado **uma única vez** pelo proprietário do projeto. Os deploys subsequentes do CI preservam a configuração pública existente sem exigir permissões elevadas de IAM:

```bash
# Obtenha o digest ou envie a primeira imagem ao Artifact Registry
IMG="us-central1-docker.pkg.dev/fgm9000-portfolio/ga4-sql-analyst/ga4-sql-analyst:<sha>"

gcloud run deploy ga4-sql-analyst \
  --project=fgm9000-portfolio \
  --region=us-central1 \
  --image="$IMG" \
  --service-account="ga4-sql-analyst-runtime@fgm9000-portfolio.iam.gserviceaccount.com" \
  --min-instances=0 \
  --max-instances=1 \
  --concurrency=10 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=60 \
  --no-invoker-iam-check \
  --labels=app=ga4-sql-analyst \
  --set-env-vars="GA4_GCP_PROJECT=fgm9000-portfolio,GA4_CORS_ORIGINS=https://fgm9000.github.io,PYDANTIC_AI_NO_BANNER=1"
```

---

## 4. Esteira de Deploy Contínuo (`deploy.yml`)

Todo merge na branch `main` com o CI verde dispara a publicação automática:

1. **Autenticação OIDC:** Requisita token efêmero ao GitHub e troca com o Workload Identity Federation da GCP (provider `github-ga4-sql-analyst` no pool `github-pool`).
2. **Build e Push do Container:** Constrói a imagem Docker multi-stage e envia para o Artifact Registry com a tag do SHA do commit.
3. **Deploy no Cloud Run:** Publica a nova revisão utilizando `gcloud run deploy --no-invoker-iam-check`.
4. **Smoke Tests:**
   - Verifica `GET /health` esperando `{"status":"ok"}`.
   - Verifica `POST /v1/validate` com `{"sql": "DELETE FROM table"}` esperando `"is_valid": false` e recusa determinística.

---

## 5. Resolução de Incidentes e Histórico Operacional

### Incidente 1: Divergência de Moeda no Alerta de Orçamento
- **Sintoma:** `terraform apply` falhava no recurso `google_billing_budget` com erro de argumento inválido.
- **Causa Raiz:** A conta de faturamento do projeto opera em **BRL**, mas a configuração solicitava USD. A API da GCP exige que o orçamento use a moeda nativa da conta de faturamento.
- **Resolução:** Atualizado `budget_amount` para `28` e `budget_currency` para `BRL` (equivalente a ~US$ 5).

### Incidente 2: Rejeição no WIF durante Deploys Automatizados
- **Sintoma:** A action `google-github-actions/auth` falhava com erro `unauthorized_client`.
- **Causa Raiz:** A condição do provider exigia restrição extra de `assertion.sub == 'repo:...:ref:refs/heads/main'`, mas tokens gerados por eventos `workflow_run` possuem formato diferente no campo `sub`.
- **Resolução:** Condição ajustada para `assertion.repository == 'fgm9000/ga4-sql-analyst' && assertion.ref == 'refs/heads/main'`.

### Incidente 3: Burla de Limite por IP com Header Falsificado
- **Sintoma:** O rate limit por IP podia ser contornado enviando headers arbitrários de `X-Forwarded-For`.
- **Causa Raiz:** O código lia o primeiro valor do header, controlado pelo cliente.
- **Resolução:** A extração do `_client_ip` em `limits.py` foi corrigida para usar o **último valor não-vazio**, adicionado pelos proxies de borda do Google Front End.

### Incidente 4: Vazamento de Identidade via `SESSION_USER()`
- **Sintoma:** Uma consulta somente leitura com `SELECT SESSION_USER()` executava com sucesso e retornava o e-mail da service account de runtime.
- **Causa Raiz:** A validação sintática verificava apenas se o comando era `SELECT` e ausência de comandos de escrita.
- **Resolução:** Inclusão de checagem explícita no C01 bloqueando funções de ambiente/identidade (`SESSION_USER`, `CURRENT_USER`, etc.) e exigência no C02 de pelo menos uma tabela permitida do GA4.
