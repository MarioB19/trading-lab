# Entrega de imagen únicamente; no permiso para ejecutar órdenes ni cambiar la VM.
resource "google_service_account" "delivery" {
  count        = var.enable_github_delivery ? 1 : 0
  account_id   = "${var.name}-delivery"
  display_name = "GitHub delivery: Artifact Registry writer only"
  depends_on   = [google_project_service.required]
}
resource "google_iam_workload_identity_pool" "github" {
  count                     = var.enable_github_delivery ? 1 : 0
  workload_identity_pool_id = "${var.name}-github"
  display_name              = "Trading Lab GitHub"
  depends_on                = [google_project_service.required]
}
resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.enable_github_delivery ? 1 : 0
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
  }
  attribute_condition = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.ref == 'refs/heads/main' && assertion.sub == 'repo:${var.github_repository}:environment:gcp-delivery'"
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
  lifecycle {
    precondition {
      condition     = can(regex("^[0-9]+$", var.github_repository_id)) && can(regex("^[0-9]+$", var.github_owner_id)) && can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
      error_message = "WIF requiere repository/owner IDs numéricos y repo validado."
    }
  }
}
resource "google_service_account_iam_member" "github" {
  count              = var.enable_github_delivery ? 1 : 0
  service_account_id = google_service_account.delivery[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository_id/${var.github_repository_id}"
}
resource "google_artifact_registry_repository_iam_member" "delivery" {
  count      = var.enable_github_delivery ? 1 : 0
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.delivery[0].email}"
}
