# Reglas del repositorio para Claude

Laboratorio y bot de inversión con dinero potencialmente real. El objetivo es no engañarse, no maximizar el backtest.

## Comandos

- Pruebas: `python -m pytest -q -W ignore` (todas deben pasar antes de terminar cualquier cambio)
- Investigación: `python -m lab.research_multi --refresh`
- Consistencia bot/backtest: `python -m lab.bot --replay 365 --sleeve crypto` (diferencia < 2%)
- Estado: `python -m lab.bot --status`; capital diario en `state/equity.csv`, operaciones en `state/trades.csv`

## Reglas duras

1. Nunca cambies `mode`, nunca agregues `--live` fuera de la condición existente en `.github/workflows/daily.yml`, nunca escribas en `.env` ni en secrets. Pasar a real lo decide y lo hace Brandon a mano.
2. Nunca agregues código que retire fondos, transfiera entre cuentas o use apalancamiento, margen, futuros o cortos.
3. Toda variante nueva va en el `grid` de `SLEEVES` en `src/lab/research_multi.py`, para que cuente como un intento más en el Sharpe deflactado.
4. No propongas cambiar la estrategia por su rendimiento reciente. Un cambio solo se considera si mejora el walk-forward fuera de muestra, el placebo (p < 0.05) y el bootstrap contra la referencia, y aun así pasa 4 semanas en simulado.
5. Las señales usan solo datos hasta el cierre del día. Toda estrategia nueva necesita su prueba de "sin mirar al futuro" en `tests/`.
6. El bot y la investigación usan las mismas funciones (`lab.portfolio`). No dupliques lógica.
7. Un activo sin precio nunca se valúa en cero (dispararía un kill switch falso).
8. No inventes números: cita `reports/multi_results.json` o corre el código.

## Al revisar el bot

Reporta capital y caída de cada bloque, operaciones de la semana, días `blocked`/`error` y su causa, el estado del kill switch y si el bot hizo lo que la regla indicaba. Sin pronósticos de precio.
