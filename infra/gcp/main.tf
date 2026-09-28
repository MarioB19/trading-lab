locals {
  services = toset(concat(["compute.googleapis.com", "artifactregistry.googleapis.com", "storage.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "iap.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "secretmanager.googleapis.com"], var.enable_budget ? ["billingbudgets.googleapis.com"] : []))
  host_files = merge(
    { for name in ["run-container.sh", "backup.sh", "healthcheck.sh", "install-release.sh"] :
      "/usr/local/lib/trading-lab/${name}" => { content = file("${path.module}/../../scripts/gcp/host/${name}"), mode = "0755" }
    },
    { for name in ["trading-lab-worker.service", "trading-lab-api.service", "trading-lab-backup.service", "trading-lab-backup.timer", "trading-lab-health.service", "trading-lab-health.timer"] :
      "/etc/systemd/system/${name}" => { content = file("${path.module}/systemd/${name}"), mode = "0644" }
    }
  )
}

resource "google_project_service" "required" {
  for_each           = local.services
  service            = each.value
  disable_on_destroy = false
}
resource "google_compute_network" "bot" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}
resource "google_compute_subnetwork" "bot" {
  name                     = var.name
  ip_cidr_range            = "10.48.0.0/24"
  network                  = google_compute_network.bot.id
  private_ip_google_access = true
}
resource "google_service_account" "runtime" {
  account_id   = "${var.name}-runtime"
  display_name = "Trading Lab paper runtime"
  depends_on   = [google_project_service.required]
}
resource "google_project_iam_member" "telemetry" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_artifact_registry_repository" "images" {
  repository_id = var.name
  location      = var.region
  format        = "DOCKER"
  description   = "Trading Lab imágenes inmutables revisadas"
  depends_on    = [google_project_service.required]
}
resource "google_artifact_registry_repository_iam_member" "reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_storage_bucket" "backups" {
  name                        = "${var.project_id}-${var.name}-backups"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = 35 }
    action { type = "Delete" }
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}
resource "google_storage_bucket_iam_member" "backup_writer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_secret_manager_secret_iam_member" "paper" {
  for_each   = toset([for ref in values(var.paper_secret_versions) : split("/", ref)[0]])
  project    = var.project_id
  secret_id  = each.value
  role       = "roles/secretmanager.secretAccessor"
  member     = "serviceAccount:${google_service_account.runtime.email}"
  depends_on = [google_project_service.required]
}
resource "google_compute_firewall" "iap_ssh" {
  name                    = "${var.name}-iap-ssh"
  network                 = google_compute_network.bot.name
  source_ranges           = ["35.235.240.0/20"]
  target_service_accounts = [google_service_account.runtime.email]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
resource "google_compute_address" "egress" {
  name       = "${var.name}-egress"
  depends_on = [google_project_service.required]
}
resource "google_compute_disk" "state" {
  name = "${var.name}-state"
  type = "pd-balanced"
  zone = var.zone
  size = 30
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}
resource "google_compute_disk" "experiments" {
  name = "${var.name}-experiments"
  type = "pd-standard"
  zone = var.zone
  size = 10
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}
resource "google_compute_instance" "bot" {
  name                      = var.name
  machine_type              = var.machine_type
  zone                      = var.zone
  deletion_protection       = true
  allow_stopping_for_update = true
  boot_disk {
    auto_delete = true
    initialize_params {
      image = "debian-cloud/debian-12"
      type  = "pd-balanced"
      size  = 10
    }
  }
  attached_disk {
    source      = google_compute_disk.state.id
    device_name = "trading-state"
  }
  attached_disk {
    source      = google_compute_disk.experiments.id
    device_name = "trading-experiments"
  }
  network_interface {
    subnetwork = google_compute_subnetwork.bot.id
    access_config { nat_ip = google_compute_address.egress.address }
  }
  service_account {
    email  = google_service_account.runtime.email
    scopes = ["cloud-platform"]
  }
  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    disable-legacy-endpoints = "TRUE"
    startup-script = templatefile("${path.module}/templates/startup.sh.tftpl", {
      files          = local.host_files
      project_id     = var.project_id
      region         = var.region
      bucket         = google_storage_bucket.backups.name
      image_uri      = var.image_uri
      source_sha     = var.source_sha
      paper_refs_b64 = base64encode(jsonencode(var.paper_secret_versions))
    })
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  labels     = { app = var.name, environment = "paper" }
  depends_on = [google_artifact_registry_repository_iam_member.reader, google_project_iam_member.telemetry]
  lifecycle {
    precondition {
      condition     = var.image_uri == "" || var.source_sha != ""
      error_message = "Una imagen inicial requiere source_sha."
    }
  }
}
resource "google_project_iam_member" "operator" {
  for_each = var.operator_email == "" ? toset([]) : toset(["roles/compute.osAdminLogin", "roles/iap.tunnelResourceAccessor", "roles/compute.viewer"])
  project  = var.project_id
  role     = each.value
  member   = "user:${var.operator_email}"
}
resource "google_service_account_iam_member" "operator_runtime" {
  count              = var.operator_email == "" ? 0 : 1
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "user:${var.operator_email}"
}
