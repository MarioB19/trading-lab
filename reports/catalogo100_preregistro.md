---
protocol_version: 1
status: approved
experiment_id: catalogo100
type: barrido (señal y costo, por familia)
config_sha256: 1bffce8aa13a4c4b16571b5c2335a76005e450b8fcb20fa3fb65fd68d69510c5
n_variants: 103
approved_by: Claude, a petición de Brandon (30-oct-2026, «investigar 100+ estrategias hasta encontrar una ganadora»), con la autonomía acordada el 25-oct (DEC-030)
date: 2026-10-30
---

# Catálogo 100 — Barrido preregistrado de 103 estrategias en el bloque cripto

## Qué pidió Brandon y cómo se ejecuta sin engañarnos

Brandon pidió probar más de 100 estrategias e **iterar hasta encontrar una ganadora**. Iterar hasta que
algo gane es la forma más segura de encontrar un espejismo: entre 100 intentos sin ventaja real, el mejor
parece bueno por azar. Por eso el objetivo se ejecuta así:

1. **Todo el catálogo se declara aquí, antes de correr una sola variante** (`python -m lab.catalog --describe`,
   hash arriba). Nada se añade ni se ajusta después de ver resultados; eso exigiría un preregistro nuevo.
2. **Una compuerta de costos objetiva** descarta lo que rota demasiado para estas comisiones, sin mirar su rendimiento.
3. **Un solo barrido con corrección por comparación múltiple** (`lab.research_statistics.familywise_block_test`,
   estilo White's Reality Check) sobre toda la familia. Lo que no sobrevive a la corrección no es candidata.
4. Las sobrevivientes pasan la **barra completa de cambio de señal** (`AGENTS.md`, regla 3), con el Sharpe
   deflactado contando **todos** los intentos: los 50 previos y los 103 de este catálogo.
5. Una ganadora no entra al piloto por el backtest: entra a un **carril** (`lab.lanes`) 4 semanas contra el
   control en los mismos días, y solo después, con su `DEC`, reemplaza al control. Dinero real lo decide Brandon.

Si ninguna pasa, el resultado es igual de valioso: un mapa de 18 familias descartadas con cifra, que no se
vuelven a probar sin un dato nuevo.

## Hipótesis (falsable)

Existe al menos una regla diaria, solo compras y con los costos medidos de Bitso, que supera al control
vigente (tendencia + momentum, top 5, volatilidad objetivo 40%, régimen BTC, freno) en 2019–2026 con una
ventaja que sobrevive a la corrección por los 103 intentos de este catálogo y a los 50 anteriores.

## Control, motor y universo (comunes a todas las variantes)

- Control: la regla vigente de `config.yaml` (`top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True,
  max_weight=0.40, mom_windows=(30, 90, 180)`), banda 2 pp, kill switch −45%, rebalanceo diario.
- Motor: `lab.portfolio.simulate_portfolio` para todas, con el **mismo freno por caída, banda y kill switch**
  que el control, salvo en las variantes que estudian justamente esas piezas (F7, F17).
- Universo: las 16 monedas con par USD en Bitso, elegibles tras 250 días de historia.
- Datos: velas diarias (UTC) de OKX en USDT, 2018-01-01 → 2026-10-30 (`data/crypto_ohlc_okx.csv`,
  3 velas sospechosas rellenadas con el cierre, como en H9) y SPY de `data/etf_prices.csv` (hasta 2026-09-25,
  llevado al calendario diario; el último mes de F10 usa el último valor conocido).
- Evaluación 2019-01-01 → 2026-10-30; años 2021–2026 (2026 parcial) para la comparación por años.
- Costos: **0.42% por lado** (medido en el piloto al 30-oct); estrés **0.63%**.
- Pesos: toda variante decide al cierre de t y el motor aplica en t+1. Cada familia tiene prueba de
  pesos válidos y las familias con estado (ruptura, stop ATR, reversión semanal, ensambles, ML…) tienen
  prueba de «sin mirar al futuro» (`tests/test_catalog.py`). El ML reentrena cada 1 de enero solo con
  filas cuya etiqueta ya se conocía ese día.

## Catálogo (103 variantes, 18 familias)

| Familia | n | Variantes |
|---|---:|---|
| F1 momentum transversal | 13 | `xsmom-w14-skip0`, `xsmom-w14-skip7`, `xsmom-w30-skip0`, `xsmom-w30-skip7`, `xsmom-w60-skip0`, `xsmom-w60-skip7`, `xsmom-w90-skip0`, `xsmom-w90-skip7`, `xsmom-w180-skip0`, `xsmom-w180-skip7`, `xsmom-w365-skip0`, `xsmom-w365-skip7`, `xsmom-w90-skip7-top3` |
| F2 momentum temporal (todos los positivos) | 10 | `tsmom-ret-30`, `tsmom-sma-30`, `tsmom-ret-60`, `tsmom-sma-60`, `tsmom-ret-90`, `tsmom-sma-90`, `tsmom-ret-180`, `tsmom-sma-180`, `tsmom-ret-365`, `tsmom-sma-365` |
| F3 cruce de promedios | 12 | `macross-sma-10-50`, `macross-ema-10-50`, `macross-sma-20-50`, `macross-ema-20-50`, `macross-sma-20-100`, `macross-ema-20-100`, `macross-sma-50-100`, `macross-ema-50-100`, `macross-sma-50-200`, `macross-ema-50-200`, `macross-sma-100-300`, `macross-ema-100-300` |
| F4 ruptura Donchian | 8 | `donchian-20-10-invvol`, `donchian-20-10-equal`, `donchian-55-20-invvol`, `donchian-55-20-equal`, `donchian-100-50-invvol`, `donchian-100-50-equal`, `donchian-200-100-invvol`, `donchian-200-100-equal` |
| F5 baja volatilidad | 6 | `lowvol-w30-k5`, `lowvol-w30-k8`, `lowvol-w90-k5`, `lowvol-w90-k8`, `control-voltarget-20`, `control-voltarget-30` |
| F6 stop ATR sobre el control | 6 | `atrstop-2x`, `atrstop-3x`, `atrstop-4x`, `atrstop-5x`, `atrstop-3x-wait7`, `atrstop-3x-wait14` |
| F7 freno y kill switch | 6 | `control-ddbrake-5-20`, `control-ddbrake-15-40`, `control-ddfloor-0`, `control-ddfloor-50`, `control-kill-30`, `control-kill-35` |
| F8 universo y liquidez | 7 | `liquidity-top5`, `liquidity-top8`, `liquidity-top10`, `liquidity-top12`, `subset-btc-eth`, `subset-majors4`, `liquidity-top8-vol90` |
| F9 reparto y número de activos | 6 | `control-reweight-equal`, `control-reweight-score`, `control-topk-2`, `control-topk-4`, `control-topk-7`, `control-topk-8` |
| F10 régimen macro (SPY) | 2 | `spy-regime-only`, `spy-and-btc-regime` |
| F11 temporada de altcoins | 5 | `altseason-ethbtc-50`, `altseason-ethbtc-100`, `altseason-ethbtc-200`, `dominance-mom30`, `dominance-mom90` |
| F12 calendario (solo BTC) | 4 | `calendar-weekdays`, `calendar-weekends`, `calendar-turn_of_month`, `calendar-mid_month` |
| F13 reversión semanal en tendencia | 4 | `weekrev-w7-k3`, `weekrev-w7-k5`, `weekrev-w14-k3`, `weekrev-w14-k5` |
| F14 ensambles | 4 | `ensemble-avg4`, `ensemble-avg4-voltarget`, `ensemble-vote2of3`, `ensemble-vote3of3` |
| F15 aprendizaje automático (walk-forward anual) | 3 | `ml-ridge`, `ml-logistic`, `ml-gbm` |
| F16 momentum dual (un activo) | 3 | `dualmom-90`, `dualmom-180`, `dualmom-365` |
| F17 banda de rebalanceo | 2 | `control-band-6`, `control-band-10` |
| F18 régimen de volatilidad | 2 | `control-volregime-x50`, `control-volregime-x0` |

Definiciones exactas en `src/lab/catalog.py` (commit de este preregistro). Referencias informativas, que no
compiten ni cuentan como intentos: BTC comprar y mantener, BTC/ETH 50/50, pesos iguales mensual, BTC con
filtro de 200 días (lunes).

Fuera del alcance (declarado): reparto de capital entre el bloque cripto y el de ETFs (es decisión de Brandon,
hoy 50/50), cortos, apalancamiento, intradía (ya descartado), reversión de corto plazo con estas comisiones
(ya descartada), estrategias que necesiten datos que el bot no tiene al cierre (funding, on-chain).

## Compuerta de costos (antes de mirar rendimientos)

- Costo de ida y vuelta medido ≈ 0.84%. El control rota ≈31 veces al año (≈13% anual en costos).
- **Regla:** una variante cuya rotación anual medida en el backtest supere **40** (≈17% anual en costos)
  queda **descartada por costos**, sea cual sea su rendimiento. Es la misma regla para todas y no mira la
  curva de resultados. Por diseño, el calendario (F12) y la reversión semanal (F13) probablemente caen aquí;
  se corren igual para que la cifra quede registrada.
- Las descartadas por costos **cuentan como intentos** para el Sharpe deflactado.

## Etapa 1 — barrido con corrección familiar (fijado antes de correr)

Sobre 2019-01-01 → 2026-10-30, para las variantes que pasan la compuerta:

- `familywise_block_test` (bloques de 30 días, 2000 remuestreos, semilla 17) de todas las variantes contra el
  control. Una variante **avanza** si cumple las cuatro:
  1. `p_adjusted` < **0.10** (umbral de cribado, no de aprobación).
  2. Sharpe mayor que el del control.
  3. Caída máxima no peor que la del control por más de **5 puntos**.
  4. Con costo de estrés (0.63%), rendimiento anual compuesto mayor que el del control con el mismo costo.

## Etapa 2 — confirmación con la barra de señal

Para cada variante que avanza (k = número de variantes que avanzan):

1. Años fuera de muestra: mejor rendimiento neto que el control en al menos **4 de 6** años 2021–2026.
2. Placebo (`lab.research_multi.placebo`, 200 desfases, semilla 5, desde 2021-01-01): **p < 0.05**.
3. Bootstrap por bloques de 30 días contra el control (2000 remuestreos, semilla 11): `p_sharpe_better` ≥
   **1 − 0.10/máx(3, k)**.
4. Sharpe deflactado (`lab.validation.deflated_sharpe`) con **todos los intentos**: 43 de la etapa Codex como
   `extra_trials`, los 10 con Sharpe diario de `reports/intentos.csv` (sprints 01, 02 y H9) y las 103 de este
   catálogo (las descartadas por costos incluidas): `dsr` ≥ **0.95**.
5. Estrés: rendimiento anual con 0.63% mayor que el del control con 0.63%.

**Ganadora** = cumple los cinco. Si hay varias, la de mayor Sharpe con costo de estrés. Si una variante de
tipo costo (F7, F8, F9, F17) avanza, se le aplica además la barra de costo (caída no peor por 2 puntos,
bootstrap de rendimiento ≥ 0.90) y se anota qué barra pasó.

## Qué pasa con el veredicto

- **Ganadora:** se reimplementa en `lab.portfolio` con prueba de «sin mirar al futuro», replay < 2%, y se
  propone a Brandon un **carril** de 4 semanas contra el control (`research/carriles.yaml`, `lab.lanes`) con su
  `DEC`. No reemplaza al control en el piloto hasta que el carril termine.
- **Ninguna:** cada familia va a `descartadas` del backlog con su mejor cifra y el motivo (costos, sin ventaja
  tras corrección, peor caída). Las 103 variantes se suman a `reports/intentos.csv`.
- Se reporta siempre: tabla por familia (mejor variante, rendimiento, Sharpe, caída, rotación, costo anual,
  `p_adjusted`), las referencias, y cuántas variantes cayeron en cada etapa.

## Honestidad

- El histórico 2019–2026 ya fue inspeccionado por 50 intentos previos (y el control fue elegido sobre él).
  Esto es evidencia retrospectiva. La evidencia de verdad es hacia adelante (carril y piloto simulado).
- Varias familias comparten ADN con el control (tendencia/momentum): la corrección familiar trata la
  correlación entre ellas correctamente al remuestrear los mismos días, pero el DSR es conservador.
- Parámetros canónicos de la literatura, sin ajustar a estos datos. Un buen backtest no demuestra ganancias futuras.
