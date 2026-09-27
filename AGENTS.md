# AGENTS.md — Trading Lab (para Codex y otros agentes)

Laboratorio y bot de inversión de Brandon, con dinero potencialmente real. El objetivo es no engañarse, no maximizar el backtest. Las mismas reglas están en `CLAUDE.md`; si cambias una, cambia las dos.

## Qué es

- Bot diario en GitHub Actions (`.github/workflows/daily.yml`) con dos bloques de $500 USD cada uno:
  - **Cripto:** portafolio táctico (tendencia + momentum + paridad de riesgo + volatilidad objetivo 40%) en los mercados contra USD de Bitso. Simulado contra el libro real de Bitso, con órdenes límite primero.
  - **Acciones:** 60/40 SPY/IEF pasivo en Alpaca (simulado interno mientras no haya llaves de Alpaca paper).
- Revisa cada hora (`lab.realtime`, solo observa) y opera una vez al día tras el cierre de las 00:00 UTC (`lab.bot --if-due`).
- Todo está en **modo simulado**. Nada mueve dinero real.
- Tablero: https://claude.ai/artifact/YLtHeryBpEfs882YJafAGG (lee `state/` del repositorio con el conector de GitHub).

## Antes de trabajar

1. `git pull --rebase`: el bot hace commit de `state/` varias veces al día desde GitHub Actions. Trabajar sobre una copia vieja provoca conflictos.
2. Entorno (una vez): `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`.
3. Lee `README.md` (qué hace, qué dice la evidencia, candados) y el informe que toque en `reports/`.

## Comandos

- Pruebas: `python -m pytest -q -W ignore` (todas deben pasar antes de terminar cualquier cambio)
- Consistencia bot/backtest: `python -m lab.bot --replay 365 --sleeve crypto` (diferencia < 2%)
- Estado: `python -m lab.bot --status`; capital diario en `state/equity.csv`, operaciones en `state/trades.csv`, análisis FIFO en `state/analysis.json`
- Tiempo real: `python -m lab.realtime --once` (foto en `state/live.json`)
- Investigación: `python -m lab.research_multi --refresh`; tiempo real: `python -m lab.research_rt`; corto plazo: `python -m lab.research_short`
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
9. No edites `state/` a mano salvo una migración documentada en el commit; lo escribe el bot.
10. Cambiar `capital` en `config.yaml` es una aportación o un retiro del bloque: el bot lo aplica solo en su siguiente corrida.

## Al revisar el bot

Reporta capital y caída de cada bloque, operaciones de la semana, días `blocked`/`error` y su causa, el estado del kill switch y si el bot hizo lo que la regla indicaba. Una línea contra la referencia (BTC o SPY). Sin pronósticos de precio. En pesos, usa `usd_mxn` de `state/equity.csv` o `state/live.json`.

## Commits

Mensajes en español, en presente, explicando qué cambia y por qué. Corre las pruebas antes de cada commit.
