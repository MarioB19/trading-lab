# Entirely offline plans: mock provider never calls a Google Cloud API.
mock_provider "google" {}

variables { project_id = "trading-lab-offline-test" }

run "safe_defaults" {
  command = plan
  assert {
    condition     = google_compute_instance.bot.machine_type == "e2-medium" && google_compute_disk.state.size == 30
    error_message = "Default VM/storage must remain within the reviewed cost envelope."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.paper) == 0 && length(google_iam_workload_identity_pool.github) == 0
    error_message = "Secrets and GitHub federation must be opt-in."
  }
  assert {
    condition     = !google_monitoring_alert_policy.heartbeat.enabled && !google_monitoring_alert_policy.backup_absence.enabled && length(google_billing_budget.monthly) == 0
    error_message = "No premature monitoring notifications or billing configuration."
  }
  assert {
    condition     = google_compute_firewall.iap_ssh.source_ranges == toset(["35.235.240.0/20"])
    error_message = "Inbound SSH must be IAP-only."
  }
}

run "reject_mutable_image" {
  command = plan
  variables { image_uri = "us-central1-docker.pkg.dev/project/repo/runtime:latest" }
  expect_failures = [var.image_uri]
}

run "reject_unreviewed_alerts" {
  command = plan
  variables { enable_operational_alerts = true }
  expect_failures = [google_monitoring_alert_policy.heartbeat, google_monitoring_alert_policy.backup_absence]
}
