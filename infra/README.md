# Infrastructure (Terraform)

Provisions what `ga4-sql-analyst` needs on GCP project `fgm9000-portfolio`. Cloud Run itself is deployed by GitHub Actions, not Terraform.

| File | What it does |
|------|--------------|
| `apis.tf` | Enables the required Google APIs (never disabled on destroy). |
| `iam.tf` | Runtime SA (BigQuery job user, Vertex AI user) and deployer SA (Cloud Run developer, act-as on the runtime SA only, writer on this repository only). |
| `artifact_registry.tf` | Docker repository with cleanup policies: keep the 5 newest versions, delete the rest after 7 days. |
| `wif.tf` | Own provider in the shared `github-pool` (read-only data source), restricted to this repo on `main`; lets the deployer SA be impersonated from GitHub Actions. |
| `budget.tf` | USD budget alert (50 / 90 / 100 %). The filter is the whole project, so it also counts other demos (conservative). |
| `outputs.tf` | Values to set as GitHub repository variables. |

State lives in `gs://fgm9000-portfolio-tfstate` under prefix `ga4-sql-analyst`.

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars   # set billing_account_id (git-ignored)
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan
terraform apply
```

Uses your Application Default Credentials. The IaC scan runs in CI (`iac-scan` job, Checkov).

## One-time bootstrap of the Cloud Run service (owner account)

The deployer service account has `roles/run.developer`, which cannot change `invoker_iam_disabled`
(that needs `run.services.setIamPolicy`). The service is therefore created once by a project owner,
already public via `--no-invoker-iam-check`; later GitHub deploys keep the same setting.

```bash
IMG=us-central1-docker.pkg.dev/fgm9000-portfolio/ga4-sql-analyst/ga4-sql-analyst:<sha pushed by deploy.yml>
gcloud run deploy ga4-sql-analyst --project=fgm9000-portfolio --region=us-central1 --image=$IMG \
  --service-account=ga4-sql-analyst-runtime@fgm9000-portfolio.iam.gserviceaccount.com \
  --min-instances=0 --max-instances=1 --concurrency=10 --memory=512Mi --cpu=1 --timeout=60 \
  --no-invoker-iam-check --labels=app=ga4-sql-analyst \
  --set-env-vars="GA4_GCP_PROJECT=fgm9000-portfolio,GA4_CORS_ORIGINS=https://fgm9000.github.io,PYDANTIC_AI_NO_BANNER=1"
```
