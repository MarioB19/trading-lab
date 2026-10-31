---
protocol_version: 1
status: approved
experiment_id: catalogo3-exog
type: barrido (señal) con datos exógenos sobre el control de cripto
config_sha256: 844ba5121dc2aaa194df0d6d0d81a63897d4913983c48f6023036d2aab127243
n_variants: 33
approved_by: Claude, siguiendo la petición de Brandon de seguir investigando (31-oct-2026: «no hemos encontrado la forma de hacer dinero, ayúdame a seguir con el research»), con la autonomía del 25-oct (DEC-030)
date: 2026-10-31
---

# Catálogo 3 — Señales exógenas (sentimiento, on-chain, stablecoins) sobre el control de cripto (preregistro)

## Por qué esto y no más permutaciones

Los Catálogos 100 y 2 agotaron lo que los **precios** pueden decir: 156 reglas y ninguna le gana al control después
de costos. Lo único que añade información nueva son **series que no son precios**. Las que existen con historia
suficiente y acceso público:

| Fuente | Serie | Desde | Rezago aplicado |
|---|---|---|---|
| alternative.me | Índice de miedo y codicia (0–100) | 2018-02 | 0 (se publica al abrir el día) |
| CoinMetrics community | MVRV de BTC, direcciones activas, BTC en exchanges, hash rate | 2015 | 1 día (se calcula al cierre) |
| DefiLlama | Oferta total de stablecoins (USD) | fiable desde 2020-07 (antes incompleta) | 1 día |

Descartadas por falta de historia: funding rates de OKX (3 meses) y open interest (desde 2024). Descargador:
`scripts/research/catalogo3_data.py` → `data/exog_*.csv`.

## Hipótesis (falsable)

Al menos una de estas señales exógenas, usada como capa que **reduce** la exposición del control (nunca la aumenta) en
los momentos que la señal marca como adversos (codicia extrema, MVRV alto, entradas de BTC a exchanges, caída de
direcciones activas, contracción de stablecoins, capitulación minera), mejora el resultado neto de costos del control en
2019–2026 con una ventaja que sobrevive a la corrección por las 33 comparaciones y a los 261 intentos previos.

## Control, motor y datos

- Idénticos al Catálogo 100: panel OKX 2018–2026 (16 monedas de Bitso), control = regla vigente, costo 0.42%/lado
  (estrés 0.63%), banda 2 pp, kill −45%, evaluación 2019-01-01 → 2026-10-30, años 2021–2026. Así el control reproduce
  exactamente +38.3% anual / Sharpe 1.19 / −34.3% del Catálogo 100.
- Las capas multiplican los pesos del control por m(t) ∈ [0, 1]; donde la serie aún no existe, m = 1 (la variante es el
  control). Las dos reglas autónomas (X8) son 100% BTC o efectivo.
- Pruebas: pesos válidos y nunca por encima del control (capas), rezago causal y «sin mirar al futuro» para una muestra
  de cada familia (`tests/test_catalog_exog.py`).

## Catálogo (33 variantes, 8 familias; umbrales canónicos, sin ajustar)

| Familia | n | Variantes |
|---|---:|---|
| X1 miedo y codicia | 8 | `fng-cut75`, `fng-cut80`, `fng-cut90`, `fng-half75`, `fng-sma7-cut75`, `fng-sma7-cut80`, `fng-linear`, `fng-follow50` |
| X2 MVRV de BTC | 7 | `mvrv-cut2.5`, `mvrv-cut3`, `mvrv-cut3.5`, `mvrv-half3`, `mvrv-half3.5`, `mvrv-linear`, `mvrv-z2` |
| X3 BTC en exchanges | 4 | `exsup-in30-half`, `exsup-in90-half`, `exsup-in30-cut2pct`, `exsup-z2-cut` |
| X4 direcciones activas | 3 | `adr-mom30-half`, `adr-mom90-half`, `adr-drop10-cut` |
| X5 oferta de stablecoins | 4 | `stab-g30-half`, `stab-g90-half`, `stab-shrink1pct-cut`, `stab-linear` |
| X6 hash ribbon | 2 | `hash-ribbon-half`, `hash-ribbon-cut` |
| X7 compuesto (4 señales) | 3 | `comp-cut-1`, `comp-half-05`, `comp-linear` |
| X8 miedo y codicia como regla sobre BTC | 2 | `fngbtc-20-80`, `fngbtc-25-75` |

`cut` = exposición 0 cuando la señal cruza el umbral; `half` = exposición 50%; `linear` = escala continua acotada
a [0.25, 1]; `z` = z-score de un año. Definiciones exactas en `src/lab/catalog_exog.py`.

## Reglas de decisión (las mismas del Catálogo 100)

- **Compuerta de costos:** rotación anual medida ≤ 40.
- **Etapa 1:** `familywise_block_test` (bloques 30 días, 2000, semilla 17) contra el control; avanza si p ajustada < 0.10,
  Sharpe > control, caída máxima no peor por más de 5 puntos y rendimiento con estrés > control con estrés.
- **Etapa 2 (señal):** ≥ 4 de 6 años 2021–2026; placebo (200 desfases, semilla 5, desde 2021) p < 0.05; bootstrap
  `p_sharpe_better` ≥ 1 − 0.10/máx(3, k); Sharpe deflactado ≥ 0.95 con **todos** los intentos (43 + los 218 con Sharpe
  de `intentos.csv` + estas 33 = 294); estrés.
- Ganadora → carril (no al piloto). Ninguna → cada familia a `descartadas` con su mejor cifra.

## Honestidad

- Las capas solo reducen exposición: en un periodo mayormente alcista (2019–2026) eso baja el rendimiento salvo que la
  señal evite las caídas de verdad. Es la prueba correcta: la pregunta es si la señal ahorra más de lo que cuesta.
- El miedo/codicia y el MVRV son muy conocidos: su valor histórico ya está en la literatura y en el precio; un backtest
  bueno aquí sigue siendo retrospectivo.
- La oferta de stablecoins antes de 2020-07 no es fiable; esas variantes son el control hasta esa fecha.
