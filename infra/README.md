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
