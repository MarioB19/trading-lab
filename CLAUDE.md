# AGENTS.md — Trading Lab (para Codex y otros agentes)

Laboratorio y bot de inversión de Brandon, con dinero potencialmente real. El objetivo es no engañarse, no maximizar el backtest. Las mismas reglas están en `CLAUDE.md`; si cambias una, cambia las dos.

## Qué es

- Bot diario en GitHub Actions (`.github/workflows/daily.yml`) con dos bloques de $500 USD cada uno:
  - **Cripto:** portafolio táctico (tendencia + momentum + paridad de riesgo + volatilidad objetivo 40%) en los mercados contra USD de Bitso. Simulado contra el libro real de Bitso, con órdenes límite primero.
  - **Acciones:** 60/40 SPY/IEF pasivo en Alpaca (simulado interno mientras no haya llaves de Alpaca paper).
- Revisa cada hora (`lab.realtime`, solo observa) y opera una vez al día tras el cierre de las 00:00 UTC (`lab.bot --if-due`).
- Todo está en **modo simulado**. Nada mueve dinero real.
- Plataforma GCP implementada localmente, pendiente de conexión y despliegue. Cuenta prevista `brandonmuro.work@gmail.com`; US$60/mes máximo. Empezar por `docs/CONNECT_CHECKLIST.md` y `docs/CONNECTION_READINESS.md`; detalles en `GCP_RUNBOOK.md`. Tras el corte, SQLite será la fuente primaria; `state/` será histórico/exportación. No ejecutar dos escritores.
- Tablero: https://claude.ai/artifact/YLtHeryBpEfs882YJafAGG (lee `state/` del repositorio con el conector de GitHub).

## Antes de trabajar

1. Revisar cambios locales y usar `git pull --ff-only origin main`: el bot hace commit de `state/` varias veces al día. Si hay divergencia, inspeccionar e integrar sin reescribir commits utilizados por preregistros, corridas o imágenes. No hacer rebase de evidencia publicada o registrada; conservar cambios ajenos y SHAs científicos.
2. Entorno Python 3.13: crear `.venv`, instalar `requirements-dev.lock.txt` y luego `pip install --no-deps -e .`.
3. Lee `README.md` (qué hace, qué dice la evidencia, candados) y el informe que toque en `reports/`.

## Comandos

- Pruebas: `python -m pytest -q -W ignore` (todas deben pasar antes de terminar cualquier cambio)
- Consistencia bot/backtest: `python -m lab.bot --replay 365 --sleeve crypto` (diferencia < 2%)
- Estado: `python -m lab.bot --status`; capital diario en `state/equity.csv`, operaciones en `state/trades.csv`, análisis FIFO en `state/analysis.json`
- Tiempo real legacy: `python -m lab.realtime --once` (foto en `state/live.json`); no lanzarlo contra el estado activo mientras otro escritor esté corriendo. En GCP usar exclusivamente systemd/`lab.runtime`.
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

- Conservar cripto diaria top 5 / volatilidad 40% y ETFs SPY/IEF 60/40. El control supera a la candidata rechazada, pero no demuestra rentabilidad futura ni preparación real.
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
