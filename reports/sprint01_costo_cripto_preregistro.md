---
protocol_version: 1
status: approved
experiment_id: sprint01-costo-cripto
type: costo
approved_by: Claude, con la autonomía acordada por Brandon el 25-oct-2026 (DEC-030)
date: 2026-10-25
---

# Sprint 01 — Menos rotación en el bloque cripto (preregistro)

## Hipótesis

Con la misma señal (tendencia + momentum, top 5, volatilidad objetivo 40%, régimen BTC, freno
por caída), **rebalancear menos** (banda de 4 puntos con margen de sustitución de 15%, rebalanceo
semanal, o ambos) obtiene más rendimiento neto que el control diario, porque paga menos costos,
sin empeorar la caída máxima más de 2 puntos.

Tipo: **cambio de costo** (`AGENTS.md`, regla 3). No se afirma un mejor timing, así que el placebo no aplica.

## Control y variantes (exactas)

Universo: las 16 monedas con par USD en Bitso (`BITSO_TRADABLE`), elegibles tras 250 días de historia.
Parámetros comunes: `top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True, max_weight=0.40`,
`mom_windows=(30, 90, 180)`, kill switch −45%.

| ID | Banda | Margen de sustitución | Rebalanceo | Freno y kill switch |
|---|---:|---:|---|---|
| control | 0.02 | 0.00 | diario | diario |
| v1-banda4-margen15 | 0.04 | 0.15 | diario | diario |
| v2-semanal | 0.02 | 0.00 | lunes (UTC) | diario, solo vende (vigía) |
| v3-semanal-banda4-margen15 | 0.04 | 0.15 | lunes (UTC) | diario, solo vende (vigía) |

Referencias, solo informativas (no son candidatas en este sprint): BTC comprar y mantener, y BTC
con filtro de 200 días revisado los lunes.

## Datos y ventana

- `data/crypto_prices.csv` (CoinMetrics/Yahoo, cierres diarios hasta 2026-09-26), mismo cargador que el bot (`lab.data.load_crypto_panel`).
- Evaluación de 2019-01-01 a 2026-09-26. Comparación año por año de 2021 a 2026 (2026 parcial).
- **Honestidad:** este histórico ya se inspeccionó en estudios previos, y `cost-aware-v1` ya vio una variante
  parecida a v1. Es evidencia retrospectiva, no un holdout limpio. La evidencia hacia adelante será el piloto simulado.

## Costos

- Base: **0.37% por lado** (costo medido del piloto en Bitso: comisión + diferencia contra la referencia, ~37 pb).
- Estrés: **0.555% por lado** (×1.5).

## Métricas y regla de decisión (fijadas antes de correr)

Para cada variante contra el control, con costo base salvo que se indique:

1. Mejor rendimiento neto en la mayoría de los años 2021–2026 (al menos 4 de 6).
2. Bootstrap por bloques de 30 días (`lab.validation.bootstrap_compare`, 2000 remuestreos, semilla 11):
   `p_return_better` ≥ **0.967** (0.90 corregido por 3 variantes: 1 − 0.10/3).
3. Caída máxima no peor que la del control por más de 2 puntos.
4. Con costo de estrés, rendimiento anual compuesto mayor que el del control.

Se aprueba la variante que cumpla los cuatro criterios. Si pasan varias, se elige la de mayor
rendimiento anual compuesto con costo de estrés. Si ninguna pasa, el control sigue y se anota el motivo.

Se reportan también: Sharpe, rotación anual, costo anual (rotación × costo), años con resultado y
las referencias. Las 3 variantes se suman a `reports/intentos.csv`.
