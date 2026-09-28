variable "project_id" {
  type        = string
  description = "Proyecto existente. Terraform no crea proyectos ni vincula billing."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Indica un project ID válido."
  }
}
variable "region" { default = "us-central1" }
variable "zone" { default = "us-central1-a" }
variable "name" {
  default = "trading-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,19}$", var.name))
    error_message = "Nombre en minúsculas, números y guiones, 2–20 caracteres."
  }
}
variable "machine_type" {
  default = "e2-medium"
  validation {
    condition     = var.machine_type == "e2-medium"
    error_message = "El piloto requiere e2-medium: los límites de los contenedores necesitan 4 GiB."
  }
}
variable "image_uri" {
  type        = string
  default     = ""
  description = "Imagen inmutable de Artifact Registry @sha256. Vacío provisiona sin iniciar aplicación."
  validation {
    condition     = var.image_uri == "" || can(regex("^[a-z0-9-]+-docker\\.pkg\\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Usa URI Artifact Registry con digest SHA256; no latest ni tags mutables."
  }
}
variable "source_sha" {
  type    = string
  default = ""
  validation {
    condition     = var.source_sha == "" || can(regex("^[a-f0-9]{40}$", var.source_sha))
    error_message = "SHA completo de 40 caracteres."
  }
}
variable "operator_email" {
  type        = string
  default     = ""
  description = "Operador futuro; vacío no otorga acceso humano. La cuenta prevista es brandonmuro.work@gmail.com."
}
variable "notification_channels" {
  type        = list(string)
  default     = []
  description = "IDs de canales Monitoring existentes y verificados. No se crean ni envían mensajes en local."
}
variable "enable_operational_alerts" {
  default     = false
  description = "Habilitar después de importación, cutover y primer heartbeat válido."
}
variable "billing_account_id" {
  type    = string
  default = ""
}
variable "enable_budget" {
  default     = false
  description = "Presupuesto de alertas opcional, NO límite automático de gasto."
}
variable "paper_secret_versions" {
  type        = map(string)
  default     = {}
  description = "Solo referencias existentes NAME/VERSION del mismo proyecto; nunca valores. Opt-in posterior."
  validation {
    condition = alltrue([for key, ref in var.paper_secret_versions :
      contains(["ALPACA_KEY_ID", "ALPACA_SECRET_KEY"], key) && can(regex("^[A-Za-z0-9_-]+/[0-9]+$", ref))
    ]) && (length(var.paper_secret_versions) == 0 || length(var.paper_secret_versions) == 2)
    error_message = "Proporciona ambas referencias ALPACA paper o ninguna, con versiones numéricas."
  }
}
variable "enable_github_delivery" { default = false }
variable "github_repository" {
  type    = string
  default = "MarioB19/trading-lab"
}
variable "github_repository_id" {
  type        = string
  default     = ""
  description = "ID numérico inmutable GitHub, requerido al habilitar WIF."
}
variable "github_owner_id" {
  type        = string
  default     = ""
  description = "ID numérico owner GitHub para prevenir toma del nombre."
}
