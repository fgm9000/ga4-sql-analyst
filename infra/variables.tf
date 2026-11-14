variable "project_id" {
  description = "GCP project that hosts the demo."
  type        = string
  default     = "fgm9000-portfolio"
}

variable "region" {
  description = "GCP region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "fgm9000/ga4-sql-analyst"
}

variable "service_name" {
  description = "Cloud Run service name; also the prefix for service accounts and the Artifact Registry repository."
  type        = string
  default     = "ga4-sql-analyst"
}

variable "billing_account_id" {
  description = "Billing account ID used by the budget. No default: set it in terraform.tfvars (git-ignored)."
  type        = string
}

variable "budget_amount" {
  description = "Monthly budget in the billing account currency. 28 BRL ~ USD 5 at 5.56 BRL/USD (close of 2026-11-11, PRD RNF-03)."
  type        = number
  default     = 28
}

variable "budget_currency" {
  description = "Currency of the billing account; Cloud Billing rejects budgets in any other currency."
  type        = string
  default     = "BRL"
}

variable "budget_alert_emails" {
  description = "Extra e-mail addresses for budget alerts. Empty means alerts go to billing admins only."
  type        = list(string)
  default     = []
}
