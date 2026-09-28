# Primera comparación agresiva: incompleta por calidad del histórico

Fecha: 27-sep-2026 CDMX / 28-sep-2026 UTC.

**Se registró e intentó una corrida; no se calculó rendimiento de ninguna cartera.** El control de datos la detuvo antes de simular. Por tanto, no hay evidencia a favor ni en contra de la candidata agresiva y no corresponde aprobarla o descartarla por rentabilidad.

## Qué se encontró

AVAX tiene dos observaciones el 13 y 14 de julio de 2020, seguidas de **69 cierres ausentes del 15-jul al 21-sep**, y vuelve a tener datos el 22-sep. El protocolo rechaza cualquier hueco interno desde el primer precio observado para evitar operaciones simuladas a precios imputados.

Todo el hueco está en el calentamiento. No hay huecos internos en el periodo evaluable de 2021-01-01 a 2026-09-26; eso no permite ignorar el calentamiento, porque forma las señales y la elegibilidad de activos.

| Panel congelado | Cobertura | Filas en evaluación | Huecos internos |
|---|---|---:|---|
| 16 criptos | 2,826 fechas diarias desde 2019-01-01 | 2,095 | AVAX: 69 en calentamiento; 0 en evaluación |
| SPY / IEF | 1,944 sesiones desde 2019-01-02 | 1,439 | 0 |

Las ausencias previas al primer precio de SOL, HBAR, NEAR, UNI, ATOM y AVAX se identifican por separado; el protocolo permite ese tramo inicial. El único hueco interno encontrado es el de AVAX.

## Comprobación del origen

Una consulta actual al [endpoint de Yahoo para AVAX](https://query1.finance.yahoo.com/v8/finance/chart/AVAX-USD?period1=1388534400&period2=1601856000&interval=1d&includeAdjustedClose=true) respondió HTTP 200 y reprodujo exactamente las dos primeras observaciones y los 69 días nulos. Refrescar la misma fuente no resuelve el problema.

El [CSV actual de CoinMetrics](https://raw.githubusercontent.com/coinmetrics/data/master/csv/avax.csv) no contiene `PriceUSD`; la primera capitalización disponible es del 23-sep-2020. Los puntos de julio no pueden derivarse del proxy de capitalización de la ruta actual. El cache original no conserva procedencia por observación: la coincidencia con Yahoo no reconstruye por sí sola toda su trazabilidad.

Las observaciones de julio preceden al [lanzamiento anunciado de Avalanche para el 21-sep-2020](https://medium.com/avalancheavax/ready-for-liftoff-avalanche-mainnet-set-to-launch-on-september-21-66a1def8d3b3). Esto requiere investigación de procedencia; no demuestra por sí solo que sean cotizaciones spot válidas, IOUs o datos que deban borrarse.

## Evidencia de la ejecución

- Preregistro aprobado y guardado solo en el commit `49c7dc42ec552c45e6dbd8e6bd8d03683e46d27a`.
- Código y base GCP registrados en `c2758dd274e47c36f8c4c0012c7b07ba4a88e504`.
- Corrida `20260928T013517Z-4fe72d3e`, protocolo `aggressive-v1`, configuración SHA256 `4d7d97add8f79e86d5dd942691cf99ad4d0bac030508c3cff427fb66ac86886e`.
- Manifiesto: `failed`. Ambas variantes: `declared`; **cero variantes evaluadas**.
- Ledger: `run_started → dataset_frozen crypto → dataset_frozen stocks → run_failed`. No hay `variant_started`, curvas ni `comparison.json`.
- Verificados cinco hashes de artefactos, la cadena del ledger, el preregistro aprobado como ancestro estricto y el commit exclusivo del protocolo.
- **203 pruebas pasan** antes de ambos commits. La configuración activa y los siete archivos operativos de estado conservan sus hashes anteriores.

Evidencia estructurada: [aggressive_v1_ejecucion.json](aggressive_v1_ejecucion.json). Captura original local: [manifiesto](experiments/aggressive-v1/20260928T013517Z-4fe72d3e/manifest.json), [fallo](experiments/aggressive-v1/20260928T013517Z-4fe72d3e/failure.json) y [ledger](experiments/ledger.jsonl). Los inputs congelados permanecen dentro de esa carpeta, excluidos de Git y de la imagen Docker; requieren respaldo separado cuando se conecte GCP.

## Consecuencia y siguiente paso

CAGR, Sharpe, caída, ventanas anuales, bootstrap, placebo y estrés de costos quedan **sin evaluar**, no en cero ni reprobados por desempeño. No se inició paper prospectivo, no se modificó el bot activo y no hubo push ni despliegue.

El siguiente trabajo necesario es una corrección trazable de calidad y disponibilidad histórica: acreditar la fuente y naturaleza de las observaciones tempranas, fijar esa política antes de construir otro dataset y conservar este intento. No interpolar los 69 cierres ni borrar observaciones para conseguir que la prueba avance. Si cambia el protocolo, requiere otro preregistro antes de una nueva corrida. El preregistro original y sus criterios permanecen intactos.
