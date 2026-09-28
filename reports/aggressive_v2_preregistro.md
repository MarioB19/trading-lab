---
protocol_version: 1
status: approved
approved_by: Brandon
approved_at_utc: '2026-09-28T02:25:26.828931+00:00'
approval_scope: Corrección de disponibilidad documentada, commits locales, comparación
  simulada y preparación funcional autorizados por Brandon; dinero real no activado.
experiment_id: aggressive-v2
hypothesis: Una concentración de hasta tres criptos y volatilidad objetivo de 60%
  mejora el rendimiento neto frente al control top5/40%, con deterioro de drawdown
  acotado, manteniendo todos los demás controles.
evaluation_window: Reevaluación retrospectiva 2021-01-01 a 2026-09-26; historia de
  señales desde 2019; datos previamente inspeccionados, no holdout virgen. Paper prospectivo
  comienza después del preregistro y debe acumular 28 días completos verificados.
config_sha256: 4fe0885b787d4ba341e4a8e606d4bd25aa0f2078427d1db99bba4194174381e1
variant_ids:
- crypto:2b12bfad2351b6e2494a
- crypto:95174601ed2699fa924a
criteria:
  walk_forward: Parámetros fijos; sin búsqueda ni reentrenamiento. Continuidad de
    cartera/kill entre años. Al menos 3 años completos y superioridad de retorno neto
    en al menos la mitad. CAGR cripto >= control + 0.03 y Sharpe >= control. Total
    agregado es comparación secundaria.
  placebo: 'Timing de la candidata: 200 desplazamientos, seed 5, p finito=(1+extremos)/(201),
    p<0.05. No demuestra por sí solo ventaja incremental frente al control.'
  bootstrap: 2000 remuestreos emparejados, bloques de 30 días, seed 11; frecuencia
    de retorno mayor >=0.80 y Sharpe mayor >=0.80. Frecuencias bootstrap, no probabilidades
    de ganancias futuras.
  cost_stress: Costo base cripto 0.0045 por lado, ETFs 0.0005. A 0.006 cripto exigir
    CAGR y Sharpe no inferiores al control. A 0.01 resultado informativo incluso si
    falla; no cambiar criterio tras verlo.
  drawdown: Caída cripto no peor que control en más de 0.05 y no inferior a -0.50.
    Kill switch 0.45 sin rearme en ambas; el límite de ejecución no garantiza una
    pérdida máxima.
---

# Cartera experimental agresiva v2 — corrección de disponibilidad preregistrada

**Aprobado antes de calcular rendimientos de v2.** Brandon solicita cerrar correctamente la primera comparación, entregar el sistema funcional y documentar la conexión de cuentas; autoriza el trabajo necesario. Esta versión conserva íntegros los parámetros, costos, capitales, variantes, periodo y criterios de `aggressive-v1`. No introduce otra estrategia ni modifica la cartera activa.

## Única corrección

El intento v1 `20260928T013517Z-4fe72d3e` terminó antes de evaluar variantes: AVAX tenía dos precios el 13 y 14 de julio de 2020 y después 69 cierres ausentes. Los originales se conservan. La nueva corrida usa exactamente esos paneles y su manifiesto, identificados por SHA256 en `configs/experiments/aggressive_v2.yaml`; no refresca ni sustituye la muestra.

Una copia derivada representa AVAX como no disponible antes de 2020-09-22. Pone en cuarentena las dos observaciones de julio con sus valores originales, sin imputar cierres, convertir monedas ni cambiar precios posteriores. La elegibilidad se recalcula con los mismos 250 cierres requeridos. La regla se basa en evidencia de disponibilidad, no en resultados de inversión.

El anuncio oficial de Binance y sus archivos spot AVAXUSDT confirman negociación desde 2020-09-22 06:30 UTC. El archivo diario empieza su bucket a 00:00 UTC; no indica negociación antes de 06:30. Es un mercado de referencia verificable, no prueba del primer mercado mundial ni de un listado histórico de Bitso. USDT sirve para verificar disponibilidad; los precios USD originales posteriores se conservan. Las cotizaciones de julio tienen procedencia spot/IOU sin acreditar, no se afirma que sean falsas.

La evidencia exacta está en `reports/data_quality/avax_spot_availability.json` y su explicación en el Markdown contiguo. Su hash se congela dentro del plan. El CSV oficial se conserva para auditoría. Los archivos publicados después pueden ser revisables; quedan fijados los bytes consultados.

## Diseño y decisión congelados

Se aplica el diseño completo de `reports/aggressive_v1_preregistro.md` (commit `49c7dc42ec552c45e6dbd8e6bd8d03683e46d27a`): dos carteras de US$1,000; 500 cripto y 500 ETF; control top5/40% frente a top3/60%, mismos límites y protecciones. Los IDs y criterios están en el frontmatter de este documento. El validador exige que al retirar los dos campos de procedencia y volver a ID v1, el hash sea exactamente `4d7d97add8f79e86d5dd942691cf99ad4d0bac030508c3cff427fb66ac86886e`.

Informar todos los resultados, incluidos fallos. El histórico ya inspeccionado no es un holdout virgen, las ventanas anuales de parámetros fijos no certifican por sí solas walk-forward fuera de muestra y no se reconstruye DSR global. Esta corrección no mejora esas limitaciones. La comparación nunca promueve automáticamente una estrategia. Se requieren 28 días prospectivos realmente observados y revisión humana; cuatro semanas prueban operación, no rentabilidad estadística.

## Secuencia reproducible

1. Guardar este preregistro aprobado en commit propio, después de pruebas sintéticas.
2. Guardar código, plan y evidencia, ejecutar las pruebas y dejar el árbol limpio.
3. Verificar el commit anterior y los hashes antes de abrir los paneles.
4. Copiar entradas originales y evidencia al expediente de v2; aplicar la corrección en copia y congelar paneles derivados.
5. Calcular la comparación completa una vez, conservando su ledger, manifiesto, curvas y veredicto. No retocar criterios según los resultados.
6. Ejecutar paper futuro separado con SimBroker y datos públicos; nunca conectar órdenes reales desde este ensayo.
