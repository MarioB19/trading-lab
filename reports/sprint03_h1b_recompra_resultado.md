---
experiment_id: sprint03-h1b-recompra
fecha: 2026-11-01
veredicto: ninguna variante aprobada; se conserva el control; H1b descartada
---

# Sprint 03 — H1b: no recomprar una moneda recién vendida (resultado)

Preregistro: `reports/sprint03_h1b_recompra_preregistro.md` (commit `7b48a6b`, antes de correr). Script: `scripts/research/sprint03_h1b_recompra.py`. Regla: `lab.reentry.apply_reentry_cooldown` sobre los pesos de `target_weights`. **Desviación de implementación respecto al preregistro** (no de la regla): iba a ser un campo de `PortfolioParams`, pero el archivo de la arena congela el hash de `lab/portfolio.py`; como la variante no se aprobó, vive en un módulo de investigación aparte y no toca el bot.
Ventana 2019-01-01 → 2026-09-26, 16 monedas de Bitso, costo 0.37% por lado (estrés 0.555%), orden mínima US$25, kill switch −45%, umbral de bootstrap 0.95.

## Modo A (decide): US$500 cada 1 de enero, 2021–2026

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. con estrés |
|---|---:|---:|---:|---:|---:|---:|
| Control (vigente, orden mínima US$25) | +41.0% | 1.26 | -33.7% | 30.2× | 11.2% | +34.4% |
| h1b-espera2 (recompra desde el día 2) | +40.9% | 1.26 | -33.1% | 28.6× | 10.6% | +33.3% |
| h1b-espera3 (recompra desde el día 3) | +39.2% | 1.24 | -33.7% | 27.4× | 10.1% | +34.5% |

| Variante | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| control | +195.5% | -13.6% | +39.1% | +67.7% | -10.8% | +35.1% |
| h1b-espera2 | +183.9% | -11.7% | +34.7% | +67.6% | -6.3% | +35.0% |
| h1b-espera3 | +188.0% | -11.7% | +36.7% | +58.9% | -10.1% | +34.3% |

### Criterios

| Variante | 1. Mayoría de años | 2. Bootstrap | 3. Caída vs control | 4. Estrés vs control | Aprobada |
|---|---|---|---|---|---|
| h1b-espera2 | ❌ 2/6 | ❌ 0.454 | ✅ +0.6 pts | ❌ -1.1 pts | ❌ |
| h1b-espera3 | ❌ 2/6 | ❌ 0.218 | ✅ +0.0 pts | ✅ +0.1 pts | ❌ |

## Modo B (informativo): una corrida compuesta desde US$500, 2019–2026

| Variante | Rend. anual | Caída máx. | Rotación/año | Costo/año | Bootstrap vs control |
|---|---:|---:|---:|---:|---:|
| control | +41.9% | -37.1% | 29.1× | 10.8% | — |
| h1b-espera2 | +40.4% | -36.2% | 27.7× | 10.2% | 0.181 |
| h1b-espera3 | +39.0% | -35.9% | 26.2× | 9.7% | 0.095 |

## Lectura

- **Veredicto: H1b descartada; el control se conserva.** Ninguna variante cumple la barra: ganan solo 2 de 6 años, el bootstrap queda en 0.45 y 0.22 (umbral 0.95), y con costos ×1.5 la espera de 2 días pierde 1.1 puntos.
- **El ahorro de costos es mucho menor que el techo calculado.** La cuenta previa suponía ≈2.9 puntos al año; en el simulador con orden mínima y banda la rotación baja solo de 30.2× a 28.6× (costo 11.2% → 10.6%, ≈0.6 puntos). Muchas «reentradas» del objetivo eran pesos chicos que la banda y la orden mínima ya no ejecutaban.
- **Cambia el perfil, no el costo:** la espera ayuda en años bajistas (2022: −11.7% contra −13.6%; 2025: −6.3% contra −10.8%) y cuesta en los alcistas (2021, 2023, 2024 con 3 días), porque bloquea la recompra de monedas que la señal vuelve a querer cuando rebotan. Es efecto de camino, no ahorro, y no se distingue del azar.
- **Qué cambia en el bot:** nada. La función queda en `lab.reentry` con su prueba de «sin mirar al futuro»; si algún día se aprueba, pasa a `PortfolioParams` para que bot y backtest la compartan.

## Limitaciones

- Histórico ya inspeccionado (retrospectivo, no holdout). Datos CoinMetrics/Yahoo, no el libro de Bitso. Costo constante por lado; el piloto mide 49–57 pb, más que los 37 pb del modelo.
- La regla solo bloquea tras una **salida total**. Las recompras del piloto tras una venta parcial (LINK: vendió US$44 el 30-oct y compró US$36 el 31-oct) no las cubre; esas son churn de la banda, no del ranking, y ya se probaron bandas más anchas en el sprint 01 (no concluyente).
- Modo A reinicia el libro cada año: aísla el tamaño de US$500, pero no es un camino compuesto real.
