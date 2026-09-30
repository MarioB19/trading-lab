# Plan de mejora — costos y rotación

Solicitado por Brandon el 29-sep-2026. Objetivo: medir dónde se pierde rendimiento
por ejecución y probar una reducción de rotación antes de cambiar el portafolio.
La candidata mejora el diagnóstico retrospectivo, pero todavía no acredita ganancia futura ni promoción.

## 1. Medición operativa implementada

- Endpoint autenticado de lectura `/api/execution-quality` y sección «Costos y
  rotación» en el panel, sobre los últimos 30 días completos de registros disponibles.
- Costo cripto ponderado por importe; separa libro público, supuestos y datos ausentes.
  El costo ya incluye comisión y diferencia de precio: no sumarlas dos veces.
- Nuevas ejecuciones del simulador registran importes maker/taker, tiempo total,
  spread, profundidad visible dentro de 0.5% del precio medio y fracción cubierta.
  Usa los libros ya consultados; no añade consultas ni cambia órdenes, precios,
  comisiones, espera o límites. No acredita fills de una cuenta real.
- Recompras dentro de 48 horas y avisos diagnósticos de liquidez: spread >50 bps
  o profundidad visible insuficiente. Son observaciones; no bloquean operaciones.
- Los registros antiguos sin detalle maker siguen como «Sin dato». La medición
  nueva comienza con la próxima operación diaria que la regla actual indique.

Base observada el 30-sep 00:15:59 UTC (29-sep CDMX): 20 fills cripto, US$1,099.47
operados, US$2.9023 de comisiones; 13 operaciones con costo medido contra libro,
35.994 bps ponderados sobre US$760.25 y cuatro reentradas en 48 horas. Esta base
es un corte histórico, no un pronóstico ni prueba de que mantener habría ganado más.

## 2. Candidata implementada y desactivada

`rotation_buffer=0.15`: conserva una moneda elegible hasta que otra tenga una
puntuación de momentum/volatilidad más de 15% superior. Salidas por inelegibilidad
o régimen siguen siendo inmediatas. El control usa `0.0`, conserva exactamente
el ranking y la identidad de parámetros anterior. La función es compartida por
bot e investigación y tiene pruebas causales de prefijo y alteración del futuro.

No cambia `config.yaml`. El runtime alojado rechaza activar un margen distinto de
cero. Top 5, volatilidad objetivo 40%, límites, capital y ETFs SPY/IEF 60/40 siguen
vigentes. No se modifica modo, `.env`, secretos ni estado a mano.

El preregistro aprobado `reports/rotation_v1_preregistro.md` fija la hipótesis, ventana,
90 variantes declaradas y criterios antes de medir nuevos resultados de mercado.
La investigación requiere preregistro en commit propio anterior al código de la
corrida y checkout limpio. El intento v1 falló al inicializar antes de evaluar; v2 corrigió sólo disponibilidad AVAX y la serialización del timestamp, conservando parámetros, muestra y criterios. Sus 90 variantes se completaron.

## 3. Secuencia de validación

1. Brandon autoriza los tres commits locales el 29-sep-2026: base preservada
   `5d6f5ff41b4afaa0e6aa2b5229311f01ff38418b`, preregistro propio
   `af34687109efbff2b7978ee802b7bb0387955bd3` y código posterior. Sin push.
2. Completar equivalencia de universo, fuentes y ejecución del protocolo operable.
   El histórico Bitso retrospectivo de CoinMetrics/Yahoo no sustituye listados
   históricos ni reproduce el libro, cola, mínimos o latencia de operación.
3. Correr una comparación registrada conservando dataset, intentos, código y hashes.
   Exigir todos los criterios: CAGR neto +0.5 puntos porcentuales, Sharpe no inferior,
   caída máxima no peor por más de 1 punto, rotación al menos 15% menor, superioridad
   en 60% de años completos, placebo p<0.05, bootstrap >=80% en retorno y Sharpe,
   y resistencia a costo de 0.60% por lado. El histórico inspeccionado se identifica.
4. Sólo si pasa la evidencia anterior, preparar paper aislado contra el control
   y observar 28 días completos futuros. No arrancarlo en el volumen operativo.
5. Considerar promoción en una decisión nueva con evidencia; mantener la variante
   desactivada si falla. Dinero real lo activa Brandon manualmente.

## Verificación y entrega

- Rama aislada `codex/mejora-costos-rotacion`, worktree `trading-lab-mejoras`.
  Los cambios ajenos del checkout original se conservaron como base sin editarlo.
- Suite completa: **454 pruebas pasan**, 129.27 segundos. Los dos timeouts de
  procesos observados durante la primera corrida concurrente no se reprodujeron
  aislados ni en la suite final. Se corrigió la identidad del parámetro apagado.
- Replay de 365 días del control: **0.458%**, límite <2%, `state/` intacto.
  JS válido, diff sin errores y panel local sin errores de consola.
- Backup remoto consistente descargado; restore local desactivado con cartera
  idéntica, 24 trades, 10 cierres, 500 observaciones y cero órdenes.
- Paquete congelado `railway-1ae90503c3b9007d`, HEAD `c1b226a` con cambios sin commit,
  41 archivos. Configuración idéntica a la versión vigente antes del despliegue.
- Publicación verificada en Railway, deployment `035ebf32-cf75-4eaa-8143-9b1730db4798`
  `SUCCESS`. Los 40 archivos instalados coinciden con el manifiesto (Dockerfile
  sólo participa en el build). Ciclo posterior del 30-sep 01:00:41 UTC sano:
  paper, ready=true, cero errores y órdenes pendientes/desconocidas, 24 trades
  conservados y un único worker. Autenticación y assets HTTPS comprobados.
- Backup posterior también descargado/restaurado en copia desactivada. Los 225
  archivos registrados del checkout original mantienen su SHA256.

## Registro local autorizado

El preregistro queda aprobado por Brandon y congelado en el commit anterior al
código. Su hipótesis, criterios y hash no se retocan. La base exacta del primer
commit pasa 432 pruebas; la integridad científica del segundo pasa 10. El tercer
commit contiene el código ya publicado y su documentación, con la suite completa.
El SHA del código y la comprobación de ancestro/árbol limpio se guardan en
`runtime-data/improvements-20260929/commit-verification.json` tras crear el commit.

La comparación registrada se completó; véase el resultado y la etapa prospectiva abajo. La equivalencia completa de datos/universo/ejecución todavía no está resuelta. Railway conserva el paquete comprobado, sin otro redeploy por la investigación.

Evidencia local: `runtime-data/improvements-20260929/`. El paquete excluye secretos,
estado, datasets e informes. La copia externa automática recurrente de Railway
sigue pendiente; esta entrega conserva una copia descargada comprobada.

## Comparación y elección del 29-sep

Corrida rotation-v2 `20260930T020623Z-3142e39c`, preregistro `45c1290`, código
`708b214`, 90 variantes y 16 artefactos íntegros. Cripto 2021-01-01 a 2026-09-26:
CAGR neto control 34.06% / candidata 39.37%, caída máxima 39.48% / 37.82%,
rotación 19.11% menor. Supera 4/5 años completos y los 8 criterios declarados;
bootstrap retorno 83.95%/Sharpe 85.90%, placebo p=0.004975. No son pronósticos.
Resultado: `reports/experiments/rotation-v2/rotation_v2_resultado.md`.

Se elige 15% para la siguiente etapa; el control operacional sigue intacto.
Plan prospectivo propio `configs/experiments/rotation_paper_v1.yaml`, preregistro
`c55b5ac`, código congelado `26ec45e`. Mismos parámetros, dos carteras virtuales
independientes, USD 1,000 cada una, sin cuentas o fábricas de broker. Primera
observación 30-sep 02:28:24 UTC, sólo 1 fecha observada, 14 fills virtuales y cero
órdenes externas/incidencias. Reintentos no duplican fills ni cuentan días.

LaunchAgent `com.tradinglab.rotation-paper-v1` cada 900 segundos comprobado,
última salida 0, errores vacíos. La ruta inicial externa falló con EX_CONFIG 78;
se conserva ese log y se retiró ese registro antes de migrar mediante backup/
restore a `~/Library/Application Support/Trading Lab/rotation-paper-v1-26ec45ef8778/`.
Paquete, Python/dependencias idénticas, datos y backups ahora son locales;
no dependen de Kingston. Se verificaron 43 archivos, siete documentos, tablas de
trades/equity y restore desactivado. Necesita Mac y sesión disponibles;
una interrupción puede causar huecos que no se reconstruyen.

Faltan 28 días completos y la validación de ejecución operable. Ninguna
promoción es automática. El plazo no puede cumplirse antes del 27-oct 20:28 CDMX;
la revisión depende de nuevas observaciones continuas. `lab.rotation_observer`
compara retorno neto, caída y volumen normalizado por capital inicial; su salida
sigue `candidate_promoted=false`, `live_authorized=false`.

Suite final 461 pruebas; replay control 0.458%. Configuración Railway verificada
igual el 30-sep 02:32:38 UTC, paper/ready, cero errores/órdenes pendientes, 40 archivos
instalados coincidentes. Original 225 hashes intactos. Sin push ni dinero real.
Evidencia: `runtime-data/improvements-20260929/rotation-v2-verification.json`,
`rotation-paper-verification.json`, `rotation-paper-local-runtime.json`.

## Validación técnica posterior del 29-sep

Replay de 365 días de ambas variantes registradas: diferencia máxima bot/backtest
0.448% en cada una, menor que 2%. Captura pública Bitso de 16 mercados y prueba
taker con el ejecutor compartido: cinco compras completas por cartera, mínimos,
redondeos y profundidad comprobados; costo puntual ponderado 41.36 bps. Una compra
virtual ETH maker completó en 37.748 segundos por cruce del libro público, con
comisión simulada 0.30% y efectivo conciliado. No certifica prioridad real de cola
ni salida por timeout; no suma fechas al paper ni modifica sus costos constantes.

Seguimiento local: cuatro ejecuciones, última salida 0, sigue una fecha observada
y cero incidencias. Original 225 hashes intactos. La equivalencia operable completa
y los 28 días futuros siguen pendientes; no se activa la candidata. Métodos,
artefactos y límites en [ROTATION_EXECUTION_VALIDATION.md](ROTATION_EXECUTION_VALIDATION.md).
