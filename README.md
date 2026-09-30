# Trading Lab

Piloto de inversión **simulado**, con dos bloques. Railway es el destino elegido para simplificar la operación; GCP queda como alternativa preparada. El estado de cada despliegue se verifica por separado: tener código o imagen no demuestra que el bot esté ejecutándose.

## Qué se conserva para operar

| Bloque | Regla vigente | Ejecución |
|---|---|---|
| Cripto | Tendencia + momentum, hasta 5 activos, volatilidad objetivo 40%, frenos y kill switch | Diaria; simulación con libro público Bitso |
| ETFs | 60% SPY / 40% IEF; banda de rebalanceo de 5 puntos | Simulador interno sin llaves privadas |

Se mantiene `config.yaml` sin cambiar capital, modo ni estrategia. La observación frecuente comprueba salud y valúa; no aumenta la frecuencia de trading. Alpaca paper externo requiere una migración de propiedad independiente: añadir credenciales no adopta posiciones existentes.

La candidata agresiva **falló los siete criterios**: CAGR cripto neto 17.08% frente a 33.77% del control y caída máxima 45.13% frente a 39.48%, en la comparación retrospectiva 2021–2026. Se retira de la operación y no se programa otro seguimiento. [Resultado completo](reports/aggressive_v2_resultado.md). El control ganó esa comparación; no demuestra rentabilidad futura ni que sea el mejor algoritmo posible.

## Empezar aquí

0. [Despliegue, corte y recuperación en Railway](docs/RAILWAY_RUNBOOK.md).
1. [Lista única de conexión y criterios GO/NO GO](docs/CONNECT_CHECKLIST.md).
2. [Runbook de instalación, corte y recuperación GCP](docs/GCP_RUNBOOK.md).
3. [Conectar una cuenta para consulta GET](docs/REAL_ACCOUNT_RUNBOOK.md).
4. [Estado de preparación y evidencia vigente](docs/CONNECTION_READINESS.md).
5. [Vista en pesos, capital de US$1,000 y ganancias por día](docs/PERFORMANCE_VIEW.md).

GitHub conserva código y validación; su workflow de operación está desactivado desde el corte del 28-sep-2026. Railway aloja una instancia con API protegida y worker simulado supervisado, SQLite persistente y backups verificados. [Panel publicado](https://trading-lab-production-a56b.up.railway.app/), usuario `brandon`: acceso autenticado y ciclo posterior al reinicio comprobados el 29-sep 04:08 UTC. No activar dos escritores. La copia externa automática sigue pendiente. La arquitectura alternativa GCP usa IAP y GCS, descritos en su propia guía.

## Procedimientos que se conservan

- Órdenes con intención durable, conciliación y contabilidad de fills confirmados. Una respuesta desconocida bloquea el reenvío; no se adivina si se ejecutó.
- Propiedad por cuenta, modo y bloque. Rotar claves no reasigna capital; las inversiones externas siguen fuera del bot.
- Bloqueo de escritor, transacciones SQLite, datos frescos y detección de precios ausentes. Los controles no garantizan una pérdida máxima.
- Respaldo consistente y autónomo más SHA256; restore a destino vacío y desactivado, con comparación de saldos e historial.
- Imagen Linux AMD64 por digest y SHA, perfil `operational-paper`, UID 10001, sin secretos ni volúmenes de investigación.
- Instalación con worker detenido, comprobación de imagen y API, cutover explícito, prueba de alertas y recuperación antes de considerar el despliegue operativo.

El diagnóstico de cuenta real sólo consulta; no envía órdenes ni adopta inversiones. No hay una ruta real autorizada en esta entrega. No modificar `mode`, `.env` o secrets para eludirla.

## Investigación conservada como historial

Se conservan preregistros, datasets, resultados y código para explicar lo descartado. La imagen y el despliegue habituales excluyen planes e informes experimentales; `scripts/paper/run.sh` rechaza iniciar la candidata retirada. El panel habitual muestra únicamente la operación; el histórico sólo aparece si se enlaza expresamente.

- [Agresiva v2: retirada y evidencia](docs/AGGRESSIVE_EXPERIMENT.md).
- [Consulta y recuperación del archivo experimental](docs/PAPER_OPERATIONS.md).
- [Protocolo para cualquier hipótesis futura](docs/RESEARCH_PROTOCOL.md).
- Informes anteriores: [principal](reports/multi_informe.md), [multi-mercado](reports/multi_market_informe.md), [tiempo real](reports/tiempo_real_informe.md), [corto plazo](reports/corto_plazo_informe.md).

Los informes antiguos no certifican el motor actual: contienen limitaciones de universo, datos, selección y validación fuera de muestra documentadas en la auditoría. La estimación Ledoit–Wolf y otras variantes permanecen fuera de la operación. No se retocan criterios ni se reinicia un kill switch para mejorar una curva.

## Validación local

Python 3.13 y dependencias fijadas:

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock.txt
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m pytest -q -W ignore
.venv/bin/python -m lab.bot --replay 365 --sleeve crypto
bash scripts/gcp/preflight.sh
bash scripts/gcp/validate.sh
```

No iniciar un bot local sobre el estado activo mientras GitHub sea escritor. Para abrir una copia de lectura ya preparada:

```sh
.venv/bin/python -m lab.service \
  --data-dir runtime-data/pesos-20260928/operational-readonly --port 8847
```

Abrir `http://127.0.0.1:8847/`. La vista usa pesos por defecto, permite USD y separa resultados diarios de movimientos de capital. La copia local procede del estado publicado `2a78cf8`; actualizar la página consulta esa copia, no sincroniza GitHub. Este panel local no es una conexión cloud ni prueba de ejecución continua.

## Alternativa GCP: pendientes de conexión

Faltan verificar proyecto/facturación/créditos, aplicar el plan revisado, publicar/instalar la imagen, cortar GitHub, observar un ciclo remoto, descargar/restaurar un respaldo GCS, comprobar notificaciones y medir costo/consumo. Después se observa la versión operativa en paper durante al menos cuatro semanas. El rechazo de la variante agresiva se conserva y no se revoca por esperar más días.

La VM es única, sin alta disponibilidad. Las alertas presupuestarias no cortan automáticamente el gasto. La simulación no reproduce toda la liquidez, prioridad de cola, comisiones o eventos de una cuenta real; las limitaciones y migraciones pendientes están en la guía de cuentas.
