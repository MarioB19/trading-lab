# AGENTS.md — Trading Lab (para Codex y otros agentes)

Laboratorio y bot de inversión de Brandon, con dinero potencialmente real. El objetivo es no engañarse, no maximizar el backtest. Las mismas reglas están en `CLAUDE.md`; si cambias una, cambia las dos.

## Qué es

- Bot diario simulado en Railway, con dos bloques de $500 USD cada uno. GitHub Actions (`.github/workflows/daily.yml`) quedó desactivado en el corte del 28-sep-2026:
  - **Cripto:** portafolio táctico (tendencia + momentum + paridad de riesgo + volatilidad objetivo 40%) en los mercados contra USD de Bitso. Simulado contra el libro real de Bitso, con órdenes límite primero.
  - **Acciones:** 60/40 SPY/IEF pasivo en Alpaca (simulado interno mientras no haya llaves de Alpaca paper).
- Revisa cada cinco minutos (`lab.realtime`, solo observa) y opera una vez al día tras el cierre de las 00:00 UTC (`lab.bot --if-due`).
- Todo está en **modo simulado**. Nada mueve dinero real.
- Corte histórico del 30-sep — Railway: `docs/RAILWAY_RUNBOOK.md`; una instancia `lab.hosted`, SQLite en `/data/runtime`, backup interno diario. Un solo escritor. Build vigente `railway-1ae90503c3b9007d` con balance diario, diagnóstico de costos/rotación y 454 pruebas; ciclo remoto sano el 30-sep 01:00:41 UTC (29-sep CDMX). Autenticación HTTPS, historial y backups/restores comprobados. Copia externa automática pendiente (Hobby no incluye backups nativos). Candidata `rotation_buffer=0.15` bloqueada en el runtime operativo. Comparación `rotation-v2` completa: supera 8/8 criterios; elegida para observación futura aislada `rotation-paper-v1`. Código congelado `26ec45e`, preregistro previo `c55b5ac`, 461 pruebas; primera observación 30-sep 02:28:24 UTC, 14 fills virtuales, cero órdenes externas e incidencias. LaunchAgent local cada 15min arrancó y reintentó sin duplicados; backup/restore comprobados. Sólo 1 día observado, 28 días completos y equivalencia de ejecución todavía pendientes. Ver `docs/IMPROVEMENT_PLAN.md` y `docs/ROTATION_PAPER_RUNBOOK.md`.
- Plataforma GCP implementada localmente, pendiente de conexión y despliegue. Cuenta prevista `brandonmuro.work@gmail.com`; US$60/mes máximo. Empezar por `docs/CONNECT_CHECKLIST.md` y `docs/CONNECTION_READINESS.md`; detalles en `GCP_RUNBOOK.md`. Tras el corte, SQLite será la fuente primaria; `state/` será histórico/exportación. No ejecutar dos escritores.
- Panel actual: https://trading-lab-production-a56b.up.railway.app/ (autenticado). El tablero anterior de Claude y `state/` en GitHub conservan el corte histórico y ya no reciben actualizaciones del bot.

- Estado verificado 3-oct 19:03 CDMX: vigente `railway-fe50d0ea8a3e5a3d`, 508 pruebas y primer ciclo sano; base US$1,000 (500/500), FIFO SQLite actualizado/conciliado, flujos conservados en reintentos, escenarios de gastos. Recuperación de efectivo ETF −US$0.10 implementada pero espera el próximo cierre fresco. Datos y configuración preservados, backup/restore comprobados; cambios sin commit/push en `codex/rentabilidad-20261003`. La auditoría científica identifica bootstrap corregido y gates walk-forward/equivalencia pendientes: los 8/8 históricos no bastan para promover, tampoco cumplir 28 días. Ver `docs/PROFITABILITY_RESEARCH_20261003.md`, `reports/operations/profitability-20261003.json` y `docs/RAILWAY_RUNBOOK.md`.

- Investigación `cost-aware-v1` aprobada por Brandon el 4-oct: preregistro `55a8fc8fa4fd30c022da5bc9149cd132cf58c10b`, capital 500/500, control y tres variantes de margen/banda, dos referencias. Motor financiado opt-in, bootstrap emparejado y corrección familiar; 589 pruebas. Ver `docs/DEEP_RESEARCH_RUNBOOK.md` y el estado real de corridas en `reports/experiments/cost-aware-v1/`. Histórico inspeccionado y datos/ejecución incompletos: ningún resultado promueve una estrategia. Base técnica publicada registrada en `f937086`; sin push ni nuevo despliegue.

- Estado verificado 4-oct 18:19 CDMX: `railway-c5b4442986a16922`, commit limpio `bd53c1c`, 650 pruebas, primer ciclo sano y captura pública automática con señales reproducidas. API/panel «Datos y decisiones verificables», captura exacta de decisiones paper y replay sin red; datos/estado/capital 500/500 preservados y backup/restore incluyen evidencia. Primera decisión con tape pendiente del próximo cierre elegible. `cost-aware-v1` cerrada sin candidatas aprobadas; no confundir reproducción con rentabilidad. Rama `codex/datos-ejecucion-20261004`, sin push. Ver `docs/EVIDENCE_RUNBOOK.md` y `reports/operations/evidence-20261004.json`.

## Antes de trabajar

1. Revisar cambios locales y usar `git pull --ff-only origin main`: el antiguo bot hacía commit de `state/`; tras el corte Railway, ese estado es histórico y no debe reactivarse para sincronizarlo. Si hay divergencia, inspeccionar e integrar sin reescribir commits utilizados por preregistros, corridas o imágenes. No hacer rebase de evidencia publicada o registrada; conservar cambios ajenos y SHAs científicos.
2. Entorno Python 3.13: crear `.venv`, instalar `requirements-dev.lock.txt` y luego `pip install --no-deps -e .`.
3. Lee `README.md` (qué hace, qué dice la evidencia, candados) y el informe que toque en `reports/`.

## Comandos

- Pruebas: `python -m pytest -q -W ignore` (todas deben pasar antes de terminar cualquier cambio)
- Consistencia bot/backtest: `python -m lab.bot --replay 365 --sleeve crypto` (diferencia < 2%)
- Estado: `python -m lab.bot --status`; capital diario en `state/equity.csv`, operaciones en `state/trades.csv`, análisis FIFO en `state/analysis.json`
- Tiempo real legacy: `python -m lab.realtime --once` (foto en `state/live.json`); no lanzarlo contra el estado activo mientras otro escritor esté corriendo. En Railway usar exclusivamente `lab.hosted`/`lab.runtime`; en GCP, systemd/`lab.runtime`.
- Investigación: `python -m lab.research_multi --describe` no ejecuta experimentos. Para correr, seguir `docs/RESEARCH_PROTOCOL.md`: preregistro aprobado en commit previo, IDs/config exactos y árbol limpio. Las rutas legacy RT/corto plazo también requieren preregistro conforme a la regla 4; no ejecutarlas para explorar sin declarar.
- Tablero: `python -m lab.dashboard` regenera `dashboard/index.html`

## Reglas duras

1. Nunca cambies `mode`, nunca agregues `--live` fuera de la condición existente en `.github/workflows/daily.yml`, nunca escribas en `.env` ni en secrets. Pasar a real lo decide y lo hace Brandon a mano.
2. Nunca agregues código que retire fondos, transfiera entre cuentas o use apalancamiento, margen, futuros o cortos.
3. Toda variante nueva va en el `grid` de `SLEEVES` en `src/lab/research_multi.py`, para que cuente como un intento más en el Sharpe deflactado.
4. No propongas cambiar la estrategia por su rendimiento reciente. Un cambio solo se considera si mejora el walk-forward fuera de muestra, el placebo (p < 0.05) y el bootstrap contra la referencia, y aun así pasa 4 semanas en simulado. Las pruebas nuevas se declaran antes de correrlas (`reports/*_preregistro.md`, con su propio commit).
5. Las señales usan solo datos hasta el cierre del día. Toda estrategia nueva necesita su prueba de "sin mirar al futuro" en `tests/`.
6. El bot y la investigación usan las mismas funciones (`lab.portfolio`). No dupliques lógica.
7. Un activo sin precio nunca se valúa en cero (dispararía un kill switch falso).
8. No inventes números: cita `reports/*.json` o corre el código.
9. No edites `state/` ni SQLite a mano salvo una migración documentada en el commit. Usar `lab.ops` para importación/backup/restore; restaurar a un destino vacío y desactivado. La activación requiere corte y conciliación. Nunca resolver órdenes desconocidas reenviando a ciegas.
10. Cambiar `capital` en `config.yaml` es una aportación o un retiro del bloque: el bot lo aplica solo en su siguiente corrida.

## Alcance operativo vigente

- Conservar cripto diaria top 5 / volatilidad 40% y ETFs SPY/IEF 60/40. El control supera a la candidata agresiva rechazada; la candidata de menor rotación supera el diagnóstico retrospectivo y sigue aislada en observación futura. Ninguna demuestra rentabilidad futura ni preparación real.
- `aggressive-v2` está retirado de operación. Conservar pruebas, corridas, SQLite, capturas, backups, preregistros e imagen f6 como historial. No continuar sus 28 días ni instalar timers; `scripts/paper/run.sh` bloquea el arranque.
- Docker/CI operativos usan target `runtime` y perfil `operational-paper`, sin planes/informes experimentales. La etapa `research` es separada, explícita y no se instala como runtime.
- Disco experimental opcional y deshabilitado por defecto; si existe una instalación anterior, no destruirlo para retirar el experimento.
- Conexión inicial: simulación sin credenciales privadas. Consulta GET real posterior separada; alta Alpaca paper externa/adopción de inversiones todavía requieren migración y validación propias.

## Al revisar el bot

Reporta capital y caída de cada bloque, operaciones de la semana, días `blocked`/`error` y su causa, el estado del kill switch y si el bot hizo lo que la regla indicaba. Una línea contra la referencia (BTC o SPY). Sin pronósticos de precio. En pesos, usa `usd_mxn` de `state/equity.csv` o `state/live.json`.

## Commits

Mensajes en español, en presente, explicando qué cambia y por qué. Corre las pruebas antes de cada commit.

## Evidencia de operación GCP

Distinguir preparación local, pruebas, imagen construida, infraestructura aplicada, runtime verificado, broker paper externo y cuatro semanas observadas. No autenticar, desplegar ni activar hasta la instrucción posterior de Brandon. No tocar secrets; Brandon los gestiona a mano. Alertas de presupuesto no son un tope de gasto. Guardar evidencia SHA → digest → instalación → lectura del estado y restore probado.


## Arena autorizada — 4-oct-2026

Brandon solicita y aprueba una plataforma experimental separada con cuatro
estrategias y US$1,000 ficticios cada una, BTC/USD en Bitso. Autoriza protocolo,
commits locales e inicio local paper; no push, cloud ni dinero real. Ver
`reports/four_strategy_arena_v1_preregistro.md` y `docs/ARENA_RUNBOOK.md`.
Las señales intradía de esta arena usan cierres completos5m/1h; swing usa1d y
market making libro/trades públicos posteriores a cada cotización. Esta excepción
solicitada no altera la regla diaria, capital ni estado del piloto habitual.
Las matemáticas de señales viven en `lab.portfolio` y se prueban con datos artificiales;
`lab.arena` reutiliza esas funciones en su motor financiado. Ninguna variante se presume rentable ni aprobada
para promoción. Preregistro previo, contabilidad de intentos y validaciones siguen
vigentes. Una base iniciada congela su versión: no cambiar código a mitad de la
observación sin detenerla y registrar el alcance de una nueva versión.


## Arena Railway autorizada — 4-oct-2026

Brandon solicita publicar la arena en Railway después de su entrega local.
Se autoriza preparar y desplegar un servicio/volumen independiente y trasladar
la simulación sin reiniciar saldos. El alcance nuevo sustituye únicamente la
restricción anterior de alojamiento local; siguen vigentes modo paper, protocolo,
no push y ninguna llave privada de exchange. La autenticación de panel reutiliza
referencias a las variables existentes en Railway, sin cambiar sus valores.
Migración documentada en `docs/ARENA_RAILWAY_RUNBOOK.md`: detener propietario local,
backup/restore, conciliación, evento explícito de cambio de identidad del código
y activación remota. El cambio de versión es de alojamiento, sin nuevas señales
ni parámetros ni reinicio del periodo científico.


## Auditoría diaria autorizada — 4-oct-2026

Brandon pide agregar una herramienta de auditoría y resumen diario entre todas
las estrategias en la plataforma publicada. Se implementa y publica una vista
de solo lectura con días CDMX, costos, actividad, calidad e integridad. Código
de trading y plan intactos; actualización de identidad documentada y comprobada
por hashes desde `4ac103b`. Ver `docs/ARENA_DAILY_AUDIT.md`. No se reinicia capital
ni observación, no se alteran parámetros ni se promueve ninguna estrategia.
