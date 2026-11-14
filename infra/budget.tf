data "google_project" "this" {
  project_id = var.project_id

  # CRM API may still be disabled on the first run; defer the read to apply.
  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "budget_email" {
  for_each = toset(var.budget_alert_emails)

  project      = var.project_id
  display_name = "Budget alert ${each.value}"
  type         = "email"

  labels = {
    email_address = each.value
  }
}

resource "google_billing_budget" "service" {
  billing_account = var.billing_account_id
  display_name    = "${var.service_name} — ${var.project_id}"

  # The filter is the whole project (it includes other demos), which makes
  # the alert conservative.
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      # Must match the billing account currency (BRL).
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 0.9
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  dynamic "all_updates_rule" {
    for_each = length(var.budget_alert_emails) > 0 ? [1] : []
    content {
      # Billing admins are still notified by default.
      disable_default_iam_recipients   = false
      monitoring_notification_channels = [for c in google_monitoring_notification_channel.budget_email : c.id]
    }
  }

  depends_on = [google_project_service.enabled]
}
