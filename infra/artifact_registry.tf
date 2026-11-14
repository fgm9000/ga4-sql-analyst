resource "google_artifact_registry_repository" "service" {
  # checkov:skip=CKV_GCP_84:Images are public demo code with no secrets; Google-managed encryption is enough and a CMEK key would add KMS cost and a key-management burden.
  project       = var.project_id
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "Container images for ${var.service_name}"

  labels = {
    app = var.service_name
  }

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-latest-5"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }

  cleanup_policies {
    id     = "delete-older-than-7d"
    action = "DELETE"
    condition {
      older_than = "604800s"
    }
  }

  depends_on = [google_project_service.enabled]
}
