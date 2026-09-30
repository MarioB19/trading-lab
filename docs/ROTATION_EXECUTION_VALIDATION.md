# Validación técnica de ejecución — menor rotación

Corte del 30-sep-2026, 03:18 UTC (29-sep CDMX). La candidata de margen 15%
continúa en observación aislada. Estas comprobaciones validan componentes del
ejecutor compartido; no eligen una estrategia por resultados recientes ni
acreditan equivalencia completa con una cuenta real. No agregan fechas al paper.

## Bot y backtest

Replay de 365 días sobre la misma captura pública cerrada que inició el paper,
con los parámetros registrados de control y candidata. La diferencia máxima
relativa entre sus respectivas curvas bot/backtest es **0.448% en ambos casos**,
inferior al límite de 2%. Cada comparación conserva 365 filas y pasa su criterio.
Se verifica coherencia mecánica; no se utiliza este replay para elegir retornos.

Entrada cripto SHA256:
`442112ecf183daed15f79677f85c54d99ef50a3d6944b204100363f1a29815bc`.
Resultados y curvas:
`runtime-data/improvements-20260929/replay-equivalence-20260930T031728Z/`.

## Libro público y ejecución taker virtual

Se capturaron los 16 mercados USD activos y sus libros públicos Bitso. Dos
carteras efímeras de US$500 se ejecutaron contra exactamente la misma captura,
con el ejecutor del bot y las reglas registradas. Sus objetivos iniciales
coinciden: ETH, SOL, LINK, NEAR y UNI. Ambas completan sus cinco compras,
respetan redondeos y mínimos, conservan efectivo positivo y tienen profundidad
visible suficiente para el 100% de las cantidades solicitadas.

El costo ponderado de esta muestra taker es **41.36 bps (0.4136%)** en cada cartera,
derivado de los costos redondeados que registró cada fill. No sustituye el costo
constante preregistrado del ensayo ni demuestra costos futuros. Esta captura
valida la rama taker; no reproduce espera maker, prioridad de cola ni latencia.

Evidencia:
`runtime-data/improvements-20260929/execution-readiness-20260930T025713Z/`.
SHA256 de `result.json`:
`1af3bff223f7445e519dbe5a93d83288edc84cbccbc318691553f293d25fe389`.

## Espera maker con consultas públicas

Una compra virtual ETH de US$107.57 completó el 100% como maker en **37.748 segundos**,
dentro del perfil vigente de espera máxima 120 segundos y consulta cada 15.
Comisión simulada US$0.322720013475, exactamente 0.30% del importe. Cantidad
redondeada, efectivo y posición concilian; no hay remanente taker ni identificadores
de órdenes externas.

Se conservaron tres libros y dos consultas de operaciones públicas. Estas dos
consultas devolvieron cero operaciones; el llenado se produjo por cruce de la
cotización pública. No prueba prioridad real de cola ni que una orden enviada
hubiera obtenido ese fill. La salida a mercado al vencer el plazo no ocurrió
en esta muestra: la rama taker se verificó por separado contra la captura anterior.

Evidencia:
`runtime-data/improvements-20260929/maker-readiness-20260930T030552Z/`.
SHA256 de `result.json`:
`2d9a9fc27b93a7967fffe2d8e5d82acd68c9ba7d4486371e2faf55800a09847c`.
`verification.json` comprueba hashes, comisión, efectivo, cantidad, redondeo,
cruce público, tiempo y ausencia de identificadores externos.

## Estado de la decisión

El seguimiento `com.tradinglab.rotation-paper-v1` sigue registrado cada 900
segundos; cuatro ejecuciones, última salida 0, una sola fecha observada y cero
incidencias. El código prospectivo conserva `26ec45e` y su preregistro `c55b5ac`.
Los 225 archivos registrados del checkout original mantienen su hash.

Faltan 28 días completos futuros continuos y evidencia de ejecución durante el
periodo, además de cerrar las limitaciones de datos/universo. Las comprobaciones
puntuales anteriores no cumplen esas condiciones. La evaluación futura también
exige retorno neto no inferior, caída no peor por más de un punto porcentual y
volumen operado <=85% del control. Sin cumplimiento y revisión, no hay promoción.
El bot operativo conserva margen cero; no se envió ninguna orden real.

Verificación conjunta:
`runtime-data/improvements-20260929/execution-validation-delivery.json`.
Procedimiento y límites del seguimiento: [ROTATION_PAPER_RUNBOOK.md](ROTATION_PAPER_RUNBOOK.md).

## Pruebas de entrega

Suite completa final: **461 pruebas pasan en 32.78 segundos**. El primer intento
tuvo un fallo al exceder cuatro segundos de arranque de un proceso sintético de
supervisión; esa prueba aislada pasó en 1.15 segundos y la suite posterior pasó
sin modificar código ni plazos. Se detuvo únicamente el proceso auxiliar huérfano
identificado de ese intento. Los tres logs y el registro de limpieza se conservan
en `runtime-data/improvements-20260929/execution-documentation-*`.
