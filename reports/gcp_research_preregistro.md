---
protocol_version: 1
status: draft
experiment_id: gcp-research-integrity
hypothesis: Pendiente de declarar y aprobar antes de ejecutar
evaluation_window: Pendiente; los históricos 2021-2026 ya fueron inspeccionados
config_sha256: null
variant_ids: []
criteria:
  walk_forward: null
  placebo: null
  bootstrap: null
  cost_stress: null
  drawdown: null
---

# BORRADOR — validación de investigación y universo operable

**No ejecutado. No aprobado. No autoriza una nueva estrategia ni dinero real.**

Este documento reserva el lugar de un protocolo futuro. No es un preregistro válido: faltan hipótesis
falsable, periodo reservado, hash exacto, lista de variantes, criterios numéricos y commit propio anterior
al código que se ejecutará. El gate lo rechaza expresamente.

Orden propuesto:

1. Congelar la estrategia vigente y reconstruir un universo con disponibilidad histórica por par.
2. Contrastar el pipeline completo sobre el universo Bitso y declarar explícitamente lo que no pueda
   reconstruirse. No interpretar el snapshot retrospectivo como datos completos punto en tiempo.
3. Solo después, considerar un protocolo separado para covarianza Ledoit–Wolf y, posteriormente,
   rebalanceo consciente de costos o diversificación de señales.

Cada hipótesis tendrá un identificador propio, plan exacto generado por `--describe`, registro integral
de intentos, evaluación temporal, placebo finito, bootstrap contra referencias, estrés de costos y
cuatro semanas completas en simulado. El documento no promete retornos ni contiene resultados inventados.

La infraestructura GCP y el cambio de scheduler no constituyen evidencia a favor de ninguna hipótesis.
Ver `docs/RESEARCH_PROTOCOL.md` para interfaces, limitaciones y verificación del preregistro.
