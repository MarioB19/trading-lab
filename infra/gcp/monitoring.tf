resource "google_logging_metric" "heartbeat" {
  name   = "${var.name}/heartbeat"
  filter = "resource.type=\"gce_instance\" AND resource.labels.instance_id=\"${google_compute_instance.bot.instance_id}\" AND jsonPayload.event=\"heartbeat\" AND jsonPayload.status=\"ok\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}
resource "google_monitoring_alert_policy" "heartbeat" {
  display_name          = "${var.name}: sin heartbeat válido en 15 minutos"
  combiner              = "OR"
  enabled               = var.enable_operational_alerts
  notification_channels = var.notification_channels
  conditions {
    display_name = "API no lista o worker sin progreso"
    condition_absent {
      filter   = "resource.type=\"gce_instance\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.heartbeat.name}\""
      duration = "900s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  alert_strategy { auto_close = "1800s" }
  documentation {
    content = "Consultar readyz y systemctl status trading-lab-worker. No reiniciar órdenes sin reconciliar. La ausencia solo se habilita tras cutover y primer heartbeat."
  }
  lifecycle {
    precondition {
      condition     = !var.enable_operational_alerts || length(var.notification_channels) > 0
      error_message = "Habilitar alertas requiere al menos un canal existente verificado."
    }
  }
}
resource "google_logging_metric" "backup_success" {
  name   = "${var.name}/backup_success"
  filter = "resource.type=\"gce_instance\" AND resource.labels.instance_id=\"${google_compute_instance.bot.instance_id}\" AND jsonPayload.event=\"backup\" AND jsonPayload.status=\"ok\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}
resource "google_monitoring_alert_policy" "backup_absence" {
  display_name          = "${var.name}: sin backup completo en 2 horas"
  combiner              = "OR"
  enabled               = var.enable_operational_alerts
  notification_channels = var.notification_channels
  conditions {
    display_name = "Backup horario sin confirmación de verificación y subida"
    condition_absent {
      filter   = "resource.type=\"gce_instance\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.backup_success.name}\""
      duration = "7200s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  alert_strategy { auto_close = "86400s" }
  documentation {
    content = "Consultar systemctl status trading-lab-backup.timer/trading-lab-backup.service y logs event=backup status=failed. Revisar espacio, permisos GCS y último backup con su manifiesto. Confirmar una restauración en destino vacío. Habilitar tras primer backup completo y canal verificado; el heartbeat del worker es independiente."
  }
  lifecycle {
    precondition {
      condition     = !var.enable_operational_alerts || length(var.notification_channels) > 0
      error_message = "Habilitar alerta de backup requiere al menos un canal existente verificado."
    }
  }
}
resource "google_monitoring_alert_policy" "cpu" {
  display_name          = "${var.name}: CPU > 85% por 10 minutos"
  combiner              = "OR"
  enabled               = var.enable_operational_alerts
  notification_channels = var.notification_channels
  conditions {
    display_name = "CPU sostenida"
    condition_threshold {
      filter          = "resource.type=\"gce_instance\" AND resource.labels.instance_id=\"${google_compute_instance.bot.instance_id}\" AND metric.type=\"compute.googleapis.com/instance/cpu/utilization\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.85
      duration        = "600s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}
resource "google_monitoring_alert_policy" "disk" {
  display_name          = "${var.name}: disco > 80% por 5 minutos"
  combiner              = "OR"
  enabled               = var.enable_operational_alerts
  notification_channels = var.notification_channels
  conditions {
    display_name = "Disco persistente o raíz lleno"
    condition_threshold {
      filter          = "resource.type=\"gce_instance\" AND resource.labels.instance_id=\"${google_compute_instance.bot.instance_id}\" AND metric.type=\"agent.googleapis.com/disk/percent_used\" AND metric.labels.state=\"used\""
      comparison      = "COMPARISON_GT"
      threshold_value = 80
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}
data "google_project" "budget" {
  count      = var.enable_budget ? 1 : 0
  project_id = var.project_id
}
resource "google_billing_budget" "monthly" {
  count           = var.enable_budget ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "Trading Lab US$60 mensual (alertas, no tope)"
  depends_on      = [google_project_service.required]
  budget_filter {
    projects               = ["projects/${data.google_project.budget[0].number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = "60"
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.8 }
  threshold_rules { threshold_percent = 1.0 }
  lifecycle {
    precondition {
      condition     = var.billing_account_id != ""
      error_message = "Habilitar presupuesto requiere billing_account_id y permisos Billing."
    }
  }
}
