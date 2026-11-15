# ADR 003 — Cloud Run, Terraform, and Access Security

> 🇺🇸 EN | 🇧🇷 [PT-BR](003-cloud-run-terraform-security.pt-BR.md) · Status: Accepted (Gate 2, 2026-11-13) · Date: 2026-11-13

## Context
A stateless request/response service (PRD P4, P7) accessing BigQuery and Vertex AI within the same cloud project. Architecture demonstrates corporate cloud best practices. While the Master Standard previously used manual `gcloud` runbook scripts, this demo upgrades infrastructure provisioning to reproducible Infrastructure as Code (Terraform).

## Considered Options
| Option | Pros | Cons |
|---|---|---|
| Cloud Run on `fgm9000-portfolio` (Standard) | Co-located with BigQuery/Vertex AI; native keyless IAM | — |
| Alternative hosting (e.g., Cloudflare Workers) | — | Severed from native GCP governance and managed identity |
| Manual runbook `gcloud` scripts (Standard) | Rapid initial setup | Not peer-reviewable in PRs; prone to configuration drift |
| **Terraform IaC Provisioning** | Reviewable in PRs, repeatable, automated static scan in CI | Requires remote GCS state management and WIF pool coordination |

## Decision
Deploy on Cloud Run in `fgm9000-portfolio` (`--min-instances=0 --max-instances=1 --concurrency=10 --memory=512Mi --cpu=1 --timeout=60`), with supporting cloud infrastructure fully provisioned via **Terraform** (`infra/`).

**Terraform Scope:**
- Runtime service account `ga4-sql-analyst-runtime` with `roles/bigquery.jobUser` and `roles/aiplatform.user`.
- Artifact Registry Docker repository with automated retention policies.
- Dedicated Workload Identity Federation (WIF) provider `github-ga4-sql-analyst` inside the shared `github-pool`.
- Remote backend state in versioned private GCS bucket `gs://fgm9000-portfolio-tfstate` under prefix `ga4-sql-analyst`.
- Cloud Billing budget alert (50/90/100% thresholds).

## Security & Least Privilege Upgrades (Phase 6 Implementation)
- **Dedicated OIDC Provider:** Created a dedicated provider `github-ga4-sql-analyst` inside the existing pool rather than altering shared resources.
- **Least-Privilege Deployer:** The deployer account holds `roles/run.developer` instead of `roles/run.admin`. It cannot execute `setIamPolicy`. The service was created once by the project owner with `--no-invoker-iam-check`, allowing subsequent CI deploys to proceed under minimal privilege.
- **Budget in BRL:** Bounded to account native currency (R$ 28 ≈ US$ 5).
- **Automated IaC Scanning:** Checkov 3.4.0 integrated into CI (`iac-scan` job).
