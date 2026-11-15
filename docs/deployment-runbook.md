# Deployment & Operations Runbook — ga4-sql-analyst

> 🇺🇸 EN | 🇧🇷 [PT-BR](deployment-runbook.pt-BR.md)

This runbook covers infrastructure provisioning, keyless Workload Identity deployment, one-time service bootstrap, and operational troubleshooting for `ga4-sql-analyst`.

---

## 1. Architecture & Security Model

Infrastructure is managed with **Terraform** on Google Cloud project `fgm9000-portfolio` (`us-central1`), while application deployments are automated by **GitHub Actions** (`deploy.yml`).

### Principle of Least Privilege (IAM)

Unlike standard tutorials that grant broad admin privileges, this project enforces strict separation:

- **Runtime Service Account (`ga4-sql-analyst-runtime`):**
  - `roles/bigquery.jobUser` (can only run query jobs against public datasets).
  - `roles/aiplatform.user` (can only invoke Vertex AI foundation models).
  - No database write permissions, no compute permissions, no access to other project resources.
- **Deployer Service Account (`ga4-sql-analyst-deployer`):**
  - `roles/run.developer` (can update image and configuration on Cloud Run).
  - `roles/iam.serviceAccountUser` (restricted strictly to the runtime SA).
  - `roles/artifactregistry.writer` (scoped strictly to the `ga4-sql-analyst` Docker repository).
  - **No `setIamPolicy` or `run.admin`:** Cannot modify project IAM bindings or expose services.

---

## 2. Infrastructure Provisioning (Terraform)

### Step 2.1: Remote State Bucket

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

### Step 2.2: Apply Terraform Configuration

```bash
cd infra

# Copy example and configure local billing account ID (git-ignored)
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars to set your billing_account_id

terraform init
terraform fmt -check -recursive
terraform validate
terraform plan
terraform apply
```

### Step 2.3: Configure GitHub Repository Variables

Set the Terraform outputs as repository variables on GitHub (no secrets required):

```bash
gh variable set GCP_PROJECT_ID     -R fgm9000/ga4-sql-analyst -b fgm9000-portfolio
gh variable set GCP_WIF_PROVIDER   -R fgm9000/ga4-sql-analyst -b "$(terraform output -raw workload_identity_provider)"
gh variable set GCP_SERVICE_ACCOUNT -R fgm9000/ga4-sql-analyst -b "$(terraform output -raw deployer_service_account)"
```

---

## 3. One-Time Cloud Run Bootstrap

Because the deployer service account holds `roles/run.developer` (and lacks `run.services.setIamPolicy`), making a service public via `--no-invoker-iam-check` cannot be performed by the CI pipeline.

The service is bootstrapped **once** by the project owner. Subsequent CI deployments keep the existing public invocation state without requiring elevated IAM permissions:

```bash
# Push the first container image or retrieve the first digest from Artifact Registry
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

## 4. Continuous Deployment Pipeline (`deploy.yml`)

Every merge into `main` that passes the CI quality gate automatically triggers deployment:

1. **OIDC Authentication:** Requests an ephemeral token from GitHub and exchanges it with GCP Workload Identity Federation (`github-ga4-sql-analyst` provider in pool `github-pool`).
2. **Container Build & Push:** Builds multi-stage Docker image and pushes to Artifact Registry tagged with the commit SHA.
3. **Cloud Run Deploy:** Deploys new revision using `gcloud run deploy --no-invoker-iam-check`.
4. **Smoke Tests:**
   - Evaluates `GET /health` expecting `{"status":"ok"}`.
   - Evaluates `POST /v1/validate` with `{"sql": "DELETE FROM table"}` expecting `"is_valid": false` and deterministic rejection.

---

## 5. Operational Troubleshooting & Post-Mortem Log

### Incident 1: Currency Mismatch on Budget Alerts
- **Symptom:** `terraform apply` failed on `google_billing_budget` with `invalid argument`.
- **Root Cause:** Billing account is denominated in **BRL**, but the budget requested USD. The Cloud Billing API enforces matching account currency.
- **Resolution:** Updated `budget_amount` to `28` and `budget_currency` to `BRL` (~US$ 5 equivalent).

### Incident 2: WIF Rejection on Automated Deploys
- **Symptom:** `google-github-actions/auth` failed with `unauthorized_client`.
- **Root Cause:** Provider condition included an over-restrictive `assertion.sub == 'repo:...:ref:refs/heads/main'`, but tokens from `workflow_run` events contain different `sub` structures.
- **Resolution:** Simplified condition to `assertion.repository == 'fgm9000/ga4-sql-analyst' && assertion.ref == 'refs/heads/main'`.

### Incident 3: Spoofed Client IPs on Rate Limiting
- **Symptom:** Rate limiting by IP could be bypassed by sending arbitrary `X-Forwarded-For` headers.
- **Root Cause:** Code read the first hop from the header, which is client-controlled.
- **Resolution:** Modified `_client_ip` extraction in `limits.py` to read the **last non-empty hop**, which is appended directly by Google Cloud Front End edge proxies.

### Incident 4: Identity Disclosure via `SESSION_USER()`
- **Symptom:** A valid read-only query like `SELECT SESSION_USER()` would execute and return the runtime service account email.
- **Root Cause:** `sqlglot` AST validation checked only statement type (`SELECT`) and prohibited destructive commands.
- **Resolution:** Added explicit checks in C01 blocking identity and environment functions (`SESSION_USER`, `CURRENT_USER`, etc.) and enforced in C02 that at least one whitelisted GA4 table is present.
