# Datos prospectivos y reproducción paper

Esta entrega instrumenta el control vigente. No cambia parámetros, capital,
cuentas, frecuencia de órdenes ni la observación congelada `rotation-paper-v1`.
La comparación `cost-aware-v1` continúa cerrada sin candidatas aprobadas.

## Flujo instalado

El mismo worker `lab.runtime` ejecuta bot y observación como antes. Después llama
a `lab.evidence --once`: consulta datos públicos una vez por día UTC. Una captura
parcial también consume esa fecha para evitar copias masivas cada cinco minutos;
los errores reintentan después de una hora. Tiene un límite de 240 segundos y su
salud se informa por separado de la operación. Nunca construye brokers ni órdenes.

Cada captura conserva el panel exacto, cobertura y proveedor por activo, respuesta
actual de mercados Bitso, ambas columnas Yahoo (Close ajustado por splits y
Adj Close ajustado también por distribuciones), eventos y metadatos seleccionados.
Se guarda la fecha de observación; no se inventan fechas históricas de listado.
Yahoo no es un feed contratado. Su evento no prueba pago ni fecha de anuncio.
El hash identifica el contenido conservado, no certifica la precisión del proveedor.

Las señales se calculan sobre el panel original y su copia serializada y restaurada,
usando `compute_targets`. Esto comprueba reproducción, no una implementación
independiente ni rentabilidad. El registro no modifica la base de precios existente.

Cuando el bot procesa un cierre elegible, archiva configuración, precios completos,
procedencia, historia de equity y estado previo sin redondeo. Para BookSim conserva
respuestas públicas, precisión, libros, trades, reloj y esperas. Repite `run_sleeve`
sobre copias aisladas con esa secuencia estricta, sin red ni espera real, y compara
solicitudes, fills, costos, efectivo, cantidades, presupuesto maker y resultado.
También comprueba que se consuma toda la secuencia. El broker original mantiene
su clase y comportamiento; las capturas no introducen una estrategia alternativa.

Un fallo del registro conserva el resultado operativo y aparece como `unavailable`.
`verified_no_orders` sólo certifica una decisión sin órdenes; `verified` certifica
la simulación registrada. Ninguno prueba cola real, fills externos o equivalencia
completa de la investigación. Alpaca externo no se reproduce por esta ruta.
No se borran `last_candle` ni se fuerzan operaciones para obtener evidencia.

## Persistencia y consulta

Se conservan documentos inmutables `evidence.capture.<tipo>.<sha256>` y un índice
compacto en el SQLite existente, esquema 1. Las decisiones se confirman en la misma
transacción que estado/fills. Las capturas idénticas no duplican el registro. El
digest interno cubre todo el payload salvo su propio campo; el hash de almacenamiento
cubre el JSON canónico completo. No hay sidecars fuera del backup.

`/api/evidence` es de sólo lectura y usa la misma autenticación del panel. Verifica
los hashes de las últimas capturas y muestra cobertura, señales, fechas y resultados
por bloque. No entrega todos los precios ni el libro público completo. Un hash
incorrecto tiene precedencia sobre un estado parcial. Una captura de mercado de
más de 36 horas queda vencida. La sección «Datos y decisiones verificables» separa
captura de datos, decisión sin órdenes y reproducción con fills.

Los backups normales de `lab.ops` incluyen estos documentos. Recuperar en directorio
vacío y desactivado y comparar saldos, filas y hashes de evidencia. Restaurar jamás
autoriza a activar un segundo escritor. Siete backups automáticos locales; la copia
externa automática sigue pendiente. Las capturas crecen con el tiempo: medir uso
del volumen de 5 GB antes de adoptar retención o almacenamiento externo.

## Qué permanece pendiente

- Disponibilidad histórica de cada par Bitso y series suficientemente largas.
- Contabilidad nominal y eventos corporativos ETF con derechos/fechas de pago.
- Equivalencia completa entre investigación, selector y ejecución operable.
- Evidencia independiente fuera de muestra y observación prospectiva suficiente.
- Una candidata que supere todos los criterios; esperar no revierte un rechazo.

El estado desplegado, pruebas, SHA y primer ciclo están en
`reports/operations/evidence-20261004.json` y `docs/RAILWAY_RUNBOOK.md`.

## Fuentes de interpretación

- [Bitso: mercados disponibles](https://docs.bitso.com/bitso-api/docs/list-available-books).
- [Yahoo: Close y Adj Close](https://finance.yahoo.com/quote/SPY/history/).
- [Yahoo: cálculo del cierre ajustado](https://in.help.yahoo.com/kb/finance/adjusted-close-sln28256.html).
