# Cartera experimental agresiva: resultado y operación

La primera comparación válida está **cerrada; la candidata se rechaza**. Falló los siete criterios preregistrados. En cripto, CAGR neto 17.08% frente a 33.77% del control y caída máxima 45.13% frente a 39.48%. Son resultados retrospectivos modelados, no ganancias reales ni pronósticos. [Informe completo](../reports/aggressive_v2_resultado.md), [JSON y trazabilidad](../reports/aggressive_v2_resultado.json).

`aggressive-v2` corrige solamente disponibilidad AVAX con evidencia oficial y conserva todos los demás parámetros de v1. Preregistro propio `1fe6c8c586b6a9899190b4f987807daf9134846c`; código del ensayo `0541232af0ae9db2d56227c0442f0e4e4aa06401`. El intento v1 fallido se conserva en [su diagnóstico](../reports/aggressive_v1_ejecucion.md). No se promueve ni cambia la estrategia activa.

## Diseño evaluado

| | Control | Experimental |
|---|---|---|
| Capital ficticio inicial | US$1,000 | US$1,000 |
| Cripto / ETF inicial | 500 / 500 | 500 / 500 |
| Máximo de criptos | 5 | 3 |
| Volatilidad objetivo anual cripto | 40% | 60% |
| Peso objetivo máximo por cripto | 40% | 40% |
| ETFs | SPY 60% / IEF 40% | Igual |
| Filtro BTC y freno | Vigentes | Iguales |
| Kill switch cripto / ETF | 45% / 25% | Igual |
| Cadencia / apalancamiento | Diaria / ninguno | Igual |

El objetivo de volatilidad no es una tasa de ganancia. Comparar cuentas con el mismo inicio evita atribuir a la estrategia diferencias de capital, precio de entrada o posiciones previas. No se copian ni se transfieren inversiones del bot actual; son cuatro ledgers internos, dentro de una base exclusiva del ensayo.

Configuración completa en `configs/experiments/aggressive_v2.yaml`; protocolo con hash, IDs, semillas y umbrales en `reports/aggressive_v2_preregistro.md`. La candidata ya existía entre las variantes históricas: esta reevaluación no es un holdout virgen ni una selección de la mejor curva.

## Qué cuenta como mejora

La comparación primaria es el bloque cripto. El total con ETFs idénticos se informa también, sin mover capital entre bloques.

- CAGR neto al menos **3 puntos porcentuales** mayor al control y Sharpe no inferior.
- Caída máxima no más de **5 puntos** peor al control y no peor de **−50%**.
- Al menos tres años completos y ventaja de retorno en al menos la mitad de ellos. Parámetros fijos, sin reiniciar capital, máximos o kill switch cada enero.
- Bootstrap emparejado: 2,000 réplicas, bloques de 30 días; frecuencias de retorno y Sharpe superiores de al menos 80%. No son probabilidades de ganancias futuras.
- Placebo de timing: 200 desplazamientos y p finito menor de 0.05. Este gate no demuestra por sí solo superioridad frente al control.
- Costo cripto base **0.45% por lado**, no inferioridad de CAGR y Sharpe con **0.60%**; **1%** es un estrés informativo. El modelo de ETF usa 0.05% por lado.

Todos los criterios deben quedar visibles aunque fallen. Si una regla falla, su estado es no aprobada; cualquier cambio de hipótesis se registra con otro ID antes de repetir. No se promueve la cartera automáticamente.

## Comparación histórica reproducible

El gate comprueba el commit anterior, texto aprobado, hash de configuración, IDs, ancestro y árbol limpio antes de abrir los datos. V2 usa los paneles originales fijados, no una descarga nueva; su copia derivada pone en cuarentena dos observaciones AVAX de julio de 2020 y recalcula elegibilidad desde el mercado de referencia verificado el 2020-09-22. No interpola ni sustituye precios USD por USDT. [Evidencia y límites](../reports/data_quality/avax_spot_availability.md).

La corrida `20260928T023514Z-2b88ffec` terminó con 27 artefactos íntegros: fuentes originales, paneles derivados, auditoría, curvas, costos y resultado. El ledger conserva ambos ensayos. Comando ejecutado:

```sh
.venv/bin/python -m lab.aggressive_research --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c
```

No repetir con criterios distintos bajo el mismo ID. Para describir sin datos ni cálculos, añadir `--describe` y omitir el SHA.

## Paper prospectivo separado

El runner usa cuatro ledgers internos: control/agresiva × cripto/ETF, dentro de una SQLite dedicada. Cada mercado aporta una única captura compartida; una transacción confirma ambas carteras. Sólo SimBroker, datos públicos y dinero ficticio. No carga `.env` ni conecta brokers privados.

En checkout limpio y versión fijada:

```sh
.venv/bin/python -m lab.paper_comparison --once \
  --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --data-dir /ruta/persistente/experimental/aggressive-v2 --fetch

.venv/bin/python -m lab.paper_comparison --status \
  --data-dir /ruta/persistente/experimental/aggressive-v2
```

Se pueden sustituir `--fetch` por `--crypto-prices /ruta/crypto.csv --stocks-prices /ruta/etf.csv`: fecha ISO en primera columna y precios USD. El programa exige historia suficiente, cierres completos y datos compatibles. No usar `state/`, `data/`, el volumen operativo principal ni carpetas con su base/flag de activación.

La base queda fijada al plan, preregistro y commit de código exactos. Una actualización de código requiere conservar el expediente y decidir una migración explícita o nuevo seguimiento; no se borra el manifiesto para eludir esta comprobación. Reintentar el mismo cierre no duplica operaciones ni cuenta otro día. Datos revisados para una vela ya procesada se rechazan.

La imagen sin Git verifica una atestación generada desde el checkout limpio y vinculada al commit de la imagen: objetos commit/tree, relación con el preregistro y archivos de código/configuración. Usar `--attestation /app/reports/attestations/aggressive-v2.json` además de plan, SHA y directorio. El [runbook GCP](GCP_RUNBOOK.md) documenta generación, empaquetado y comprobación. Un JSON con un hash arbitrario no salta el gate.

## Interpretación del seguimiento

Como la candidata ya fue rechazada, el seguimiento sirve para comprobar el funcionamiento del software y comparar decisiones simuladas. **28 días no anulan los siete fallos ni rescatan automáticamente la estrategia.** No hay promoción automática, botón de trading ni permiso real.

Sólo cuentan observaciones futuras tras el primer ciclo verificado; importar un mes de precios no equivale a un mes observado. Deben transcurrir al menos 28 días completos, con continuidad e incidentes resueltos. Los días omitidos quedan registrados y no se rellenan retrospectivamente. Cuatro semanas prueban operación, no rentabilidad estadística.

## Alcance técnico y conexión posterior

La simulación al cierre no reproduce liquidez, cola, fills parciales o precios exactos del broker. El histórico no modela mínimos/tope por orden ni `max_price_jump`, aunque el runner paper conserva esas restricciones. Las ventanas históricas ya inspeccionadas no son un holdout virgen. No hay reconstrucción completa de listados Bitso ni DSR global.

El panel `lab.service` acepta `--research-dir` para mostrar la corrida verificada y `--comparison-dir` para leer la SQLite experimental; no modifica ninguna. La preparación de cuenta real está en [REAL_ACCOUNT_RUNBOOK.md](REAL_ACCOUNT_RUNBOOK.md), con diagnóstico GET y propiedad externa explícita. La cuenta no se adopta ni opera por conectarla.

La evidencia final de pruebas, imagen, primer ciclo y recuperación se registra en [DELIVERY_ACCEPTANCE.md](DELIVERY_ACCEPTANCE.md). Distinguir implementación local, imagen ejecutada, conexión/despliegue GCP, broker externo y semanas observadas. No se ha conectado GCP ni activado dinero real.
