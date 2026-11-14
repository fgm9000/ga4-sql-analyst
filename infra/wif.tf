# The pool is shared with other demos and managed elsewhere: read-only here.
data "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github-pool"
}

# This repo gets its own provider so the existing one is never modified.
resource "google_iam_workload_identity_pool_provider" "github" {
  # checkov:skip=CKV_GCP_125:False positive: the condition pins assertion.sub to this repo and main ref (no wildcards), but Checkov cannot resolve the var.github_repository interpolation in the sub claim. With the literal repo name the check passes.
  project                            = var.project_id
  workload_identity_pool_id          = data.google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-${var.service_name}"
  display_name                       = "GitHub ${var.service_name}"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only pushes to main of this repository (sub is repo:<owner/name>:ref:refs/heads/main).
  attribute_condition = "assertion.sub == 'repo:${var.github_repository}:ref:refs/heads/main' && assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  depends_on = [google_project_service.enabled]
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${data.google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}
