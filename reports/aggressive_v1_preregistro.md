---
protocol_version: 1
status: approved
approved_by: Brandon
approved_at_utc: '2026-09-28T01:30:39Z'
approval_scope: Commits locales y primera comparación simulada; sin push ni despliegue.
experiment_id: aggressive-v1
hypothesis: Una concentración de hasta tres criptos y volatilidad objetivo de 60%
  mejora el rendimiento neto frente al control top5/40%, con deterioro de drawdown
  acotado, manteniendo todos los demás controles.
evaluation_window: Reevaluación retrospectiva 2021-01-01 a 2026-09-26; historia de
  señales desde 2019; datos previamente inspeccionados, no holdout virgen. Paper prospectivo
  comienza después del preregistro y debe acumular 28 días completos verificados.
config_sha256: 4d7d97add8f79e86d5dd942691cf99ad4d0bac030508c3cff427fb66ac86886e
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

# Cartera experimental agresiva v1 — preregistro aprobado

**Estado al preregistrar: aprobado para ejecutar; todavía sin resultados.** Brandon confirmó expresamente el protocolo, los commits locales del preregistro/código y la primera comparación simulada. La autorización incluye guardar la base técnica GCP pendiente; no incluye push, despliegue, cambio de estrategia activa ni dinero real. Los parámetros y criterios siguientes quedan congelados antes de la primera corrida.

## Diseño congelado

Dos carteras virtuales de US$1,000 nuevas, con US$500 en cripto y US$500 en SPY/IEF 60/40. Ningún saldo del bot activo se copia ni se mueve. La referencia es la **regla actual** iniciada con el mismo efectivo y precios que la candidata, no una comparación engañosa contra su cuenta ya invertida.

| Regla | Control | Experimental |
|---|---|---|
| Máximo de criptos | 5 | 3 |
| Volatilidad objetivo anual | 40% | 60% |
| Peso objetivo máximo por cripto | 40% | 40% |
| Filtro BTC, tendencia y momentum | Sí | Igual |
| Freno por caída | Sí | Igual |
| Kill switch cripto / ETF | 45% / 25% | Igual |
| Cadencia | Diaria | Diaria |
| Apalancamiento, cortos, retiros | No | No |
| Bloque ETF | SPY 60%, IEF 40% | Igual |

60% es un presupuesto de volatilidad, **no una promesa ni objetivo de rentabilidad**. Los pesos pueden desviarse por mercado entre rebalanceos. Las órdenes de venta que reducen riesgo siguen permitidas.

Los parámetros completos, capital, universo, costos, ventanas, semillas y criterios numéricos viven en `configs/experiments/aggressive_v1.yaml`. Su SHA256 está en el frontmatter. Ambas variantes ya pertenecen al grid declarado `SLEEVES.crypto`; no se elige la más rentable del histórico ni se abre una búsqueda adicional. Este es un nuevo ensayo registrado de dos reglas previamente consideradas, no evidencia inédita.

## Ejecución comparable

- Un único panel de precios congelado por mercado, compartido por ambas carteras. Mismas fechas de evaluación, disponibilidad de activos y costos.
- Inicio con efectivo, sin transferencia/rebalanceo entre cripto y ETF. Estados separados por cartera dentro de una SQLite exclusiva con commit del par completo.
- Históricos: funciones compartidas `lab.portfolio`, pesos de t aplicados en t+1, costos por compraventa, freno y kill persistentes; sin reiniciar riesgos en cada año.
- El motor histórico trabaja con pesos continuos: no reproduce mínimos/tope por orden ni el filtro operativo de saltos `max_price_jump`. Esas restricciones permanecen iguales en el paper de ambas carteras. El histórico debe rechazar huecos internos de precio desde la primera observación de un activo: rellenarlos y vender en un cierre inexistente podría ocultar pérdidas. Las ausencias anteriores al primer precio solo sirven para modelar elegibilidad, no demuestran fecha real de listado.
- Paper: funciones compartidas del bot, únicamente `SimBroker`, llenado idealizado al cierre con fee y slippage modelados. No consulta brokers privados, credenciales ni env, ni atribuye ventaja maker. Esta comparación estudia señales y riesgo; la ejecución real se valida por separado.
- Inputs históricos y resultados en `reports/experiments/aggressive-v1/`; paper en un directorio dedicado, fuera de `state/`/`data/` activos. Cualquier resultado fallido se conserva.

## Interpretación y decisiones

Los umbrales son tolerancias de diseño fijadas antes de esta corrida; no se ajustaron observando sus resultados. Informar todos los criterios, también los que fallen. Un fallo significa **no promover**; no se retoca y reejecuta bajo el mismo ID.

El periodo histórico ya se inspeccionó, la disponibilidad histórica exacta de pares Bitso no está reconstruida y el modelo no reproduce profundidad, prioridad maker, latencia, suspensión de activos ni deslistes reales. La muestra no es una garantía. La primera comparación es retrospectiva; la confirmación posterior requiere datos nuevos.

El ledger contará los dos intentos en este experimento, pero no reconstruye por sí solo el DSR global de todas las exploraciones históricas. No declarar una certificación global de significancia ajustada.

No basta con ganar más dólares: debe pasar CAGR, Sharpe, costos, caída, bootstrap y placebo. Luego completar al menos 28 días paper observados desde el primer ciclo verificado, con continuidad e incidentes resueltos. **Cuatro semanas prueban operación, no rentabilidad estadística.** No hay promoción automática ni dinero real.

## Orden antes de ejecutar

1. Revisar este protocolo y los archivos concretos.
2. Autorizar commits locales: preregistro en commit propio y después código reproducible, incluyendo la base técnica GCP aún pendiente. No implica push.
3. Verificar hash y ancestro, árbol limpio y ausencia de cambios en configuración activa.
4. Ejecutar primero la comparación registrada; reportar veredicto completo.
5. Iniciar el paper prospectivo con datasets del cierre compartidos y acumulación real de evidencia, sin backfill presentado como observación.
