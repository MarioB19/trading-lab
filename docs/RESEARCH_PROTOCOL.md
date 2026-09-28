# Protocolo de investigación reproducible

Estado: motor preparado. La suite general continúa pendiente de su propio preregistro aprobado.
El ensayo específico `aggressive-v1` sí fue preregistrado e intentado posteriormente; quedó incompleto
por calidad del histórico, antes de calcular rentabilidad. Ver [su evidencia](../reports/aggressive_v1_ejecucion.md).
La estrategia activa y `config.yaml` permanecen fuera de este proceso. El paso a dinero real sigue siendo
una decisión y acción manual de Brandon. Una infraestructura más confiable no demuestra una ventaja estadística.

## Qué se corrigió

- El optimizador walk-forward mantiene pesos y parámetros conocidos en cada cierre. El parámetro
  elegido en el último año ya no modifica retrospectivamente el freno de años anteriores.
- La cartera, capital, máximos y kill switch conservan continuidad entre selecciones. El primer retorno
  de cada año usa la señal del último cierre disponible del año previo.
- El placebo Monte Carlo calcula `(1 + simulaciones >= observado) / (1 + n)`: con 200 simulaciones
  su mínimo es 1/201, nunca cero. La corrección también se aplica a los módulos históricos RT y corto plazo.
- Se puede investigar covarianza Ledoit–Wolf explícitamente. `sample` sigue siendo el valor por defecto.
  La alternativa incorpora tanto `sample` como `ledoit_wolf` al grid para contar los dos intentos.

Los JSON/Markdown históricos de `reports/` **no fueron recalculados**. Sus filas del optimizador y sus
p-valores pertenecen al motor anterior. La candidata fija no dependía del defecto del optimizador;
eso no elimina las limitaciones de datos, selección retrospectiva y ejecución. No atribuir resultados
históricos al motor corregido ni afirmar nuevas rentabilidades.

## Primero describir, después preregistrar

Este comando solo lee configuración y describe el grid; no descarga ni calcula rendimientos:

```bash
python -m lab.research_multi --describe --universe bitso
```

Opciones que deben estar congeladas antes de correr:

- `--universe historical|bitso`: universo histórico top 15 o las monedas Bitso fijadas en código.
- `--cov-estimator sample|ledoit_wolf`: candidata de investigación y grid correspondiente.
- `--multi-market --candidate multi|multi_monthly`: protocolo separado para ese bloque.
- `--refresh`: también forma parte del hash del plan; no se puede añadir después de preregistrar.

La salida incluye `config_sha256`, configuración completa e IDs de todas las variantes **declaradas**.
Declarar una variante no implica haberla ejecutado ni validado. El grid de `SLEEVES` sigue siendo la
fuente de las variantes; `research_plan` produce una copia con las opciones explícitas, sin mutar los defaults.

Crear un preregistro con frontmatter como el siguiente, sustituyendo todos los campos:

```yaml
---
protocol_version: 1
status: approved
experiment_id: nombre-unico
hypothesis: Hipótesis falsable escrita antes de examinar resultados
evaluation_window: Periodo reservado y entrenamiento; declarar qué datos ya fueron inspeccionados
config_sha256: HASH_EXACTO_DE_DESCRIBE
variant_ids: [IDS_EXACTOS_DE_DESCRIBE]
criteria:
  walk_forward: Periodos, benchmark y umbral fijados antes de correr
  placebo: p < 0.05, cola superior con corrección finita
  bootstrap: Métrica, referencia, longitud de bloque y umbral fijados antes de correr
  cost_stress: Costos y criterio de aceptación fijados antes de correr
  drawdown: Máxima caída aceptada y regla de comparación
---
```

El gate verifica estado aprobado, identidad, hash del plan, lista exacta de IDs y presencia de criterios.
La calidad científica y falsabilidad del texto requieren revisión humana; el gate no las deduce de prosa.

El preregistro necesita **su propio commit**. El SHA del preregistro debe ser un ancestro estricto de
HEAD: el código ejecutado corresponde a un commit posterior. El archivo debe seguir idéntico al blob
del commit declarado, y el árbol de trabajo debe estar limpio. Los resultados bajo `reports/experiments/`
se excluyen de esa última comprobación. Cambiar parámetros, universo o reparto después del preregistro
invalida su hash y exige un protocolo nuevo. La base técnica está registrada en el commit local
`c2758dd274e47c36f8c4c0012c7b07ba4a88e504`; no hubo push. El preregistro agresivo no autoriza
otras investigaciones ni la suite general todavía pendiente.

## Ejecución registrada

Cuando los pasos anteriores estén completos, la interfaz es:

```bash
python -m lab.research_multi \
  --experiment-id nombre-unico \
  --preregistration reports/nombre-unico_preregistro.md \
  --preregistration-commit SHA_COMPLETO_DE_40_CARACTERES \
  --universe bitso
```

El comando antiguo sin preregistro falla antes de descargar datos o simular. Los métodos públicos
`run`, `run_multi_market` y `run_sleeve` también exigen una `ExperimentRun` verificada. Los helpers
matemáticos permanecen disponibles para tests sintéticos. Los ejecutables antiguos `research_rt`,
`research_short` y `research` todavía no integran este gate; son herramientas heredadas, no rutas
autorizadas para explorar nuevas variantes. La automatización nueva debe invocar `research_multi`.

Cada ejecución guarda:

```text
reports/experiments/<experiment-id>/<run-id>/
  manifest.json
  inputs/<sleeve>_prices.csv
  inputs/<sleeve>_eligible.csv
  multi_results.json + multi_informe.md + multi_curves.csv
  # o multi_market[_monthly]_results.json
reports/experiments/ledger.jsonl
```

El manifiesto identifica SHA de código, SHA/blob del preregistro, plan y hash, datasets congelados y sus
hashes SHA256, periodo, activos, faltantes, procedencia y limitaciones. Los resultados incluyen el dataset
usado. El ledger distingue `run_started`, `dataset_frozen`, `variant_started`, `variant_completed`,
`variant_failed`, `run_completed` y `run_failed`. Registra el intento antes del cálculo; una caída no borra
un intento empezado. Sus registros tienen bloqueo entre procesos, fsync y una cadena de hashes que
detecta alteraciones; no es una firma ni reemplaza respaldos. Una caída abrupta puede dejar un run abierto:
eso debe investigarse, nunca presentarse como completado.

Para almacenamiento externo/local persistente o futuro job GCP:

```bash
# Añadir al comando registrado; rutas de archivos, no URLs gs://.
--output-root /ruta/persistente/experiments --ledger /ruta/persistente/ledger.jsonl
```

El workflow de GitHub conserva un artefacto por ejecución durante 90 días; su ledger temporal no consolida todos los runs anteriores. Para investigación sostenida se debe preservar y consolidar un ledger duradero antes de evaluar el conjunto global de intentos. El proceso de infraestructura debe preservar esos archivos antes de eliminar un contenedor efímero.
No se implementa aquí subida automática a GCS, IAM, llaves, ni autorización de trading.

## Universo operable y limitaciones explícitas

`--universe bitso` ejecuta el **mismo pipeline completo** (grid, walk-forward, placebo, bootstrap,
costos, kill switch y comparaciones) sobre el subconjunto Bitso. Se etiqueta como `bitso` y se guarda
separado del headline histórico. Esa ruta existe pero **no fue ejecutada** durante esta implementación.

No constituye todavía una réplica exacta de ejecución:

- La lista contiene monedas operables según el snapshot de septiembre de 2026; faltan sus fechas de
  listado/deslistado de pares. `point_in_time_complete` y `bitso_listing_history_available` son falsos.
- Los precios siguen siendo CoinMetrics/Yahoo; el bot consulta Kraken/Bitso. Los proxies antiguos por
  capitalización y las extrapolaciones de capitalización no se vuelven datos exactos por tener hash.
- Se congela el panel y la elegibilidad efectivamente usados; no se inventa procedencia por observación
  que las fuentes actuales no entregan.
- Faltantes, suspensiones, apertura siguiente de Alpaca, cola maker, latencia y deslistes no tienen aún
  reproducción completa en el backtest. Los costos continúan siendo supuestos.
- Los periodos históricos ya inspeccionados no pasan a ser holdout virgen. Hace falta un periodo reservado
  y datos nuevos para conclusiones posteriores.

## Contabilidad de intentos y promoción

El registro nuevo conserva los intentos entre ejecuciones. Las pruebas horarias/corto plazo históricas
siguen identificadas como externas/legadas: no se registran falsamente como corridas del run actual.
El DSR actual incluye su número, pero usa la dispersión del grid diario; no reconstruye automáticamente
todos los Sharpes y decisiones exploratorias de antes del ledger. Debe leerse como corrección parcial,
no como certificación global de ausencia de sobreajuste.

`experiments.promotion_gate` recibe evidencia de validación y evidencia paper previamente verificadas.
Exige todos los checks cuantitativos, causalidad, coincidencia de configuración/código/run, intervalo de
28 días completos, al menos 28 días observados, continuidad completa e incidencias resueltas. La función
evalúa evidencias suministradas; no audita por sí sola un broker ni certifica que quien las entrega dice
la verdad. Su salida máxima es `ready_for_human_review`; `live_authorized` siempre es falso. No está
conectada a cambios de modo ni a llaves reales. Cuatro semanas prueban operación, no rentabilidad futura.

## Próximas hipótesis

Prioridad: equivalencia de datos/universo/ejecución de la estrategia congelada. Después pueden declararse
bandas de rebalanceo conscientes de costos, Ledoit–Wolf y diversificación de señales de baja frecuencia.
Solo Ledoit–Wolf tiene interfaz matemática opt-in en este cambio. Histéresis y nuevas familias quedan
como hipótesis; no se implementaron reglas de rendimiento ni se activaron estrategias.
