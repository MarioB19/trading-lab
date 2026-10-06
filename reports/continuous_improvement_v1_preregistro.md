---
protocol_version: 1
status: approved
experiment_id: continuous-improvement-v1
hypothesis: Un ciclo diario de atribución, calidad e integridad permite priorizar problemas medidos y conservar evidencia sin cambiar estrategias por pérdidas recientes. No prueba una hipótesis de rentabilidad.
evaluation_window: Desde la implementación; cortes diarios CDMX. Histórico visto solo como diagnóstico. Cada futura candidata requiere un protocolo y periodo reservado propios.
config_sha256: 0902bfeaaf1e2b0590e62feb6058922b5b95bdf1958007590c1bc9249d81359f
variant_ids: [daily-diagnostics-v1]
criteria:
  walk_forward: El controlador no simula nuevas reglas; cada candidata debe superar su evaluación temporal independiente y prerregistrada.
  placebo: Cada candidata necesita p inferior a 0.05 con corrección por intentos; el diagnóstico no satisface ese criterio.
  bootstrap: Cada candidata necesita evidencia emparejada contra su control y umbrales fijados antes de la corrida.
  cost_stress: Reportar neto sin descontar fees dos veces; cambios económicos necesitan costos de ejecución y estrés verificados.
  drawdown: No alterar exposición, máximos ni frenos del runtime. Candidatas sin validación no se promueven.
---

# Mejora continua diaria v1

Autorización: Brandon solicita implementar un plan y algoritmo de mejora continua diario el 5-oct-2026. Se implementa seguimiento, memoria de incidencias, prioridades, registro y evaluación de candidatas separadas. Sigue todo paper. No se autoriza dinero real, cambios de secretos ni promoción por resultados recientes.

Esta declaración congela las reglas del controlador antes de su código. Es una herramienta de diagnóstico y gobernanza, no una nueva estrategia de inversión ni una prueba que demuestre mayores ganancias.

- Fuentes: APIs autenticadas y registros Railway del piloto y la arena, exclusivamente GET y SQLite mode=ro. Nunca escribir en los datos operativos.
- Preservar cortes, hashes y reintentos. Solo un diagnóstico final por fecha y fuente; revisiones intradía se conservan sin contarlas como nuevos días.
- Prioridades: integridad y frescura, ejecución/calidad, costos medidos y cobertura. Perder un día no justifica mutar reglas; los días ganadores también se revisan.
- Candidatas: máximo dos activas y un nuevo ensayo cada siete días; preregistro propio anterior al código, grid contado, control, datos reservados y evaluación final fijada. No reutilizar holdouts para ajustar ni revisar significancia diariamente.
- Incorporación: walk-forward, placebo, bootstrap, costos, caída, causalidad, comparación múltiple, equivalencia y holdout; al menos 28 días completos y sin huecos/incidencias. Salida máxima: apta para revisión humana. Ningún comando de este controlador despliega o modifica estrategias.
- La mejora cotidiana puede ser evidencia nueva, un fallo técnico corregido o una hipótesis documentada. Un día sin cambio justificable se registra como tal; no se promete una mejora de rendimiento diaria.
