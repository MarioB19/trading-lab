---
protocol_version: 1
status: approved
approved_on: 2026-10-04
approved_by: Brandon
approval_scope: protocolo y tres commits locales sin push para ejecutar la comparación histórica registrada
experiment_id: cost-aware-v1
hypothesis: Con las mismas señales y riesgo, histéresis de 15% y/o banda de 4pp reducen
  rotación y mejoran el resultado económico de 500 USD cripto + 500 USD ETF frente
  al control, tolerando como máximo 1pp adicional de caída y sin relajar la evidencia
  exigida. Se permite que ninguna alternativa pase.
evaluation_window: '2021-01-01 a 2026-09-25: histórico YA INSPECCIONADO, auditoría
  retrospectiva; señales con calentamiento congelado previo. Años completos 2021-2025;
  2026 parcial, descriptivo. No hay holdout virgen ni selección de hiperparámetros.
  La evaluación futura requiere un protocolo nuevo y al menos 28 días propios.'
config_sha256: f2e42cd223c0f39c316b2cd709c577dd3ba3d7f49bba7289aa6d2a765c4bc545
variant_ids:
- deep_total:4fa836ccf7e64aa09cb7
- deep_total:3bb5c5b991bd66b7720f
- deep_total:d017d55c421f08525d6c
- deep_total:d87abf1e75c18bbf11d8
- deep_total:6940401895846706dab4
- deep_total:e0794733abc8990d5059
criteria:
  walk_forward: Reglas fijas causales sin optimizador. Una curva continua por regla,
    con capital, picos y kill switch sin reinicio; resultado superior al control en
    >=60% de los años calendario completos. Histórico visto; no se declara OOS independiente.
  placebo: 199 desplazamientos comunes entre 60 y n-60 inclusivos, semilla 23.
    Se desplazan exactamente las decisiones anteriores a cada retorno evaluado;
    no se incorpora la señal final no utilizada. Ambos modelos
    se ejecutan de nuevo con efectivo, mínimos, costos y kill switch; diferencia de
    Sharpe. Valor p finito (1+k)/(1+B), ajustado con Holm sobre 3 candidatas, <0.05.
  bootstrap: 2000 bloques no circulares emparejados de 30 días, semilla 11,
    incluyendo el último inicio posible; frecuencia de superioridad
    en retorno y Sharpe >=0.8, con evidencia no degenerada y Sharpe definido. Max-stat conjunto centrado para 3 candidatas, semilla 17,
    p ajustado <.05 e incluyendo cero en el máximo nulo. Sensibilidades de 14/90 días sólo para reporte. DSR parcial con
    un mínimo de 97 intentos previos; no constituye certificación global.
  cost_stress: Costo base cripto 0.45% por lado y ETF 0.05%; sensibilidad cripto de
    0.60% y 1.00%. Con 0.60%, CAGR y Sharpe económicos no inferiores al control.
    Gastos de 0/5/10/20 USD mensuales; caso principal de 5 USD y referencias manuales
    de 0 USD.
  drawdown: Caída económica no peor que la del control por >1pp; kill switches
    persistentes de 45% para cripto y 25% para ETF, sin apalancamiento.
  economics: CAGR económico >= control + 0.5pp, Sharpe >= control, ganancia económica >0
    y rotación cripto al menos 15% menor. Sharpe >= referencia pasiva BTC + ETF sin
    hosting. No declarar una ganadora ni promoverla con datos vistos o equivalencia
    incompleta.
---

# Investigación profunda cost-aware-v1 — protocolo aprobado

## Pregunta y alternativas congeladas

Base de US$1,000: US$500 cripto y US$500 ETFs, sin transferencias entre bloques.

| Regla | Margen de sustitución | Banda cripto |
|---|---:|---:|
| Control reconstruido | 0% | 2pp |
| Menor sustitución | 15% | 2pp |
| Menos rebalanceos | 0% | 4pp |
| Ambas medidas | 15% | 4pp |

Las cuatro mantienen tendencia, momentum, máximo cinco activos, volatilidad objetivo
de 40%, peso objetivo máximo de 40%, frenos y ETF 60/40. Las salidas a peso 0 y por
kill switch no dependen de la banda. No se prueba mayor riesgo ni frecuencia.
Se registran también dos referencias: BTC pasivo + ETF 60/40 y efectivo USD sin
interés. Son seis identidades en total y tres candidatas frente al control; no hay
una búsqueda indefinida de parámetros.

## Ejecución y contabilidad

Motor nuevo opt-in con 500 USD contables por bloque, cantidades, efectivo, ventas
antes de compras y compras financiadas, incluidos sus costos. Mínimos de 5 USD para
cripto y 1 USD para ETF. La señal usa el cierre previo; el precio de ese cierre es
un proxy de ejecución posterior, no un llenado verificable. El costo por lado
incluye comisión y fricción; no se descuenta dos veces. Ante precios faltantes, no
operar; valorar con el último precio durante un máximo de 5 filas. Una posición
sin valoración válida detiene el estudio. Los precios ajustados de ETF son un
proxy, no un registro contable de dividendos y splits.

Los bloques comienzan sin posiciones; el calentamiento de la señal no aporta
patrimonio pasado. Se conservan el primer retorno y su costo. El hosting se devenga
por día calendario (costo mensual / días del mes), pagado externamente; se resta
del resultado económico sin vender posiciones ni mover dinero. Si los gastos acumulados superan el patrimonio,
se conserva la pérdida completa en USD; CAGR, Sharpe y peor mes compuestos quedan
indefinidos. Un Sharpe indefinido no aprueba comparaciones y asigna p=1 al placebo.
Si una curva principal no admite retornos compuestos, se conserva la familia
completa y su evidencia conjunta queda indisponible con p=1; no se elimina
la alternativa perdedora para reducir el número de comparaciones.
No incluye impuestos.

## Integridad y límites

Entradas idénticas a la corrida conservada
`rotation-v2/20260930T020623Z-3142e39c`, verificadas por SHA256; sin actualización
de datos ni cambios a posteriori. El plan JSON adjunto contiene hashes, fechas,
activos, criterios, semillas y costos exactos. Un cambio de plan necesita otro
preregistro.

No hay históricos completos de listados de Bitso, precios de ejecución y cola ni
registro de eventos corporativos de ETF. El universo es retrospectivo. Se auditan
24 fechas equiespaciadas usando 720 filas y recalculando las 250 observaciones
mínimas dentro de cada ventana como el bot, tolerancia de 0.0001 en peso y la misma
membresía; pasar esas fechas no acredita equivalencia completa. El ensayo
`rotation-paper-v1` se conserva intacto.

Superar los controles puede justificar la revisión de una candidata; nunca
establece una ventaja en datos nuevos fuera de muestra, autoriza dinero real ni
promueve una estrategia. Una validación futura propia requiere identificación y
al menos 28 días; ese tiempo demuestra continuidad operativa, no significancia
estadística. Si ninguna pasa, es un resultado válido: ninguna alternativa justifica
una mejora. No se relajan umbrales.

## Procedimiento después de aprobación

1. Registrar la base técnica publicada anterior en un commit local separado.
2. Guardar este preregistro aprobado y su plan JSON en su propio commit.
3. Registrar la implementación y pruebas en un commit posterior; árbol limpio.
4. Ejecutar exclusivamente por `research_multi` con `--deep-profile cost-aware-v1`, SHA previo completo y entradas congeladas. El gate existente verifica ancestro estricto, hash y variantes.
5. Conservar manifiesto, entradas, curvas, métricas, placebos y ledger encadenado; publicar un informe con fallos además de aciertos. No hacer push ni desplegar el estudio.

Fuentes y crítica: [investigación documental](../docs/DEEP_RESEARCH_SOURCES_20261003.md), [auditoría del motor](../docs/DEEP_RESEARCH_ENGINE_AUDIT_20261003.md).
