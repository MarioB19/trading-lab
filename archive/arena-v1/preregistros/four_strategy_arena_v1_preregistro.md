---
protocol_version: 1
status: approved
experiment_id: four-strategy-arena-v1
hypothesis: Las cuatro familias pueden compararse con capital independiente y ejecución financiada; ninguna se presume rentable.
evaluation_window: 28 días futuros completos desde la activación aprobada; los datos previos solo calientan señales, no generan operaciones retrospectivas.
config_sha256: da87a899233efafcddee05403d9780881bf2671854bdd02baba691a84ab2143a
variant_ids: [scalping-v1, swing-v1, mean-reversion-v1, market-making-v1]
criteria:
  walk_forward: Sin optimización; cuatro ventanas consecutivas de siete días futuros. Reportar cada una, sin seleccionar ganadora ni promover con solo 28 días; exigir protocolo histórico operable independiente antes de promoción.
  placebo: Validación futura bloqueada hasta disponer de suficientes entradas causales y libro/trades archivados. Exigir p menor que 0.05 con Holm para cuatro comparaciones; no sustituir por una prueba sobre precios sin ejecución.
  bootstrap: Validación futura bloqueada hasta muestra independiente suficiente; bootstrap emparejado por bloques contra BTC comprado al inicio y efectivo, intervalo 95 por ciento de exceso neto por encima de cero y corrección familiar. Longitud siete días, 10000 réplicas; 28 días no bastan para afirmar ventaja.
  cost_stress: Reportar todos los fills y comisiones; evaluar sensibilidad 1x y 2x sin afirmar que reprecificar fees reproduce otras decisiones. Precios taker contra profundidad visible; maker solo trades posteriores que atraviesan la cotización, participación máxima diez por ciento.
  drawdown: Freno permanente al veinte por ciento desde el máximo y pausa hasta el siguiente día UTC al tres por ciento diario; no garantizan pérdida máxima y se conserva inventario si faltan datos o profundidad.
---

# Preregistro — cuatro estrategias, US$1,000 por cartera

Primera versión solicitada por Brandon el 4-oct-2026: cripto al contado Bitso, simulación aislada. Cuatro carteras empiezan con **US$1,000 de efectivo cada una**, US$4,000 ficticios en total. Sin apalancamiento, cortos, transferencias ni conexión privada. El piloto Railway actual mantiene su capital e historial.

El contrato completo está en `configs/arena/four_strategies_v1.json`; hash `da87a899233efafcddee05403d9780881bf2671854bdd02baba691a84ab2143a`. Reglas fijadas antes de evaluar rendimientos:

| Cartera | Señal y salida | Asignación |
|---|---|---|
| Scalping | Cierre de 5 min supera máximos de veinte velas previas y EMA9 > EMA21. Sale por cruce contrario, −1%, +1.5%, dos horas o cambio de día UTC. Máximo seis entradas diarias. | 25% del patrimonio |
| Swing | Motor existente `lab.portfolio.target_weights`: BTC sobre al menos dos medias 20/50/100/200 y momentum 30/90/180 positivo, ajuste por volatilidad 40%, máximo 90%, banda 2pp. | Hasta 90%, solo al cierre diario |
| Reversión | Cierre horario con z-score de veinte cierres <= −2; sale al regresar a la media, −3% o veinticuatro horas. | 25% del patrimonio |
| Creación de mercado | Compra inicial de inventario de 25%; cotiza dos lados de US$25 con margen por lado >= comisión maker +0.10%, sesgo de inventario, TTL60s y latencia1s. No vende más inventario que posee ni compra si supera50%. | Inventario inicial25%, máximo50% |

Se usan cierres públicos Kraken BTC/USD completos (fuente explícita de señales) y libro/trades públicos Bitso BTC/USD para ejecuciones simuladas. La diferencia de proveedores es una limitación; no se afirma réplica del histórico Bitso. Las velas abiertas nunca generan señales. Maker0.30% y taker0.36% son supuestos conservados del piloto, no tarifas verificadas de una cuenta individual. En mercados USD el saldo corresponde a dólares digitales según Bitso; no implica efectivo bancario USD.

Cada ciclo conserva captura, decisiones, cotizaciones y fills. Los cuatro libros son alternativas independientes; no se presentan como órdenes reales ni como cuatro competidores consumiendo juntos la misma liquidez. Modelo maker conservador con volumen observado posterior y lado maker coincidente, sin certeza de prioridad de cola. Un hueco de captura cancela cotizaciones antes de intentar llenarlas. Persistencia atómica, IDs únicos, transacciones y verificación de saldo; no se reinicia capital al recargar.

Panel: saldos, efectivo, inventario, resultados realizados/no realizados, comisiones, caída, actividad, gráfica y detalle por cartera. Sin resultados inventados. Demostración artificial separada y rotulada. Observación pública sin ejecución permitida mientras se revisa este protocolo.

## Puesta en marcha

El preregistro necesita aprobación y commit propio anterior al código; después un commit de implementación con suite completa aprobada. Solo entonces se habilita el ciclo paper de mercado. Ningún resultado habilita dinero real. Backtests, selección de parámetros, publicación Railway y cambios de la estrategia operativa quedan fuera de esta primera implementación.

Fuentes de ejecución: https://docs.bitso.com/bitso-api/docs/list-order-book y https://docs.bitso.com/bitso-api/docs/list-trades .

Aprobado por Brandon en este chat: «Aprobar protocolo y commits locales». Incluye inicio local de la simulación, sin push ni publicación.
