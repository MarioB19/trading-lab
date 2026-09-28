output "instance_name" { value = google_compute_instance.bot.name }
output "zone" { value = var.zone }
output "backup_bucket" { value = google_storage_bucket.backups.name }
output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${var.name}" }
output "outbound_ip" { value = google_compute_address.egress.address }
output "iap_dashboard_command" {
  value = "gcloud compute ssh ${var.name} --project ${var.project_id} --zone ${var.zone} --tunnel-through-iap -- -N -L 8080:127.0.0.1:8080"
}
output "github_wif_provider" {
  value = try(google_iam_workload_identity_pool_provider.github[0].name, null)
}
output "github_delivery_service_account" {
  value = try(google_service_account.delivery[0].email, null)
}
