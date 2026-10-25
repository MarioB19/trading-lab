---
experiment_id: sprint01-costo-cripto
fecha: 2026-10-25
veredicto: ninguna variante aprobada; se conserva el control
---

# Sprint 01 — Menos rotación en el bloque cripto (resultado)

Preregistro: `reports/sprint01_costo_cripto_preregistro.md` (commit `6593cd3`, antes de correr). Script: `scripts/research/sprint01_costo_cripto.py`.
Ventana 2019-01-01 → 2026-09-26, 16 monedas de Bitso, costo 0.37% por lado (estrés 0.555%), kill switch −45%.

## Resultado

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. anual con estrés |
|---|---:|---:|---:|---:|---:|---:|
| Control (diario, banda 2 pp) | +42.7% | 1.31 | -36.7% | 29.6× | 10.9% | +35.2% |
| V1: banda 4 pp + margen 15% | +45.4% | 1.37 | -34.9% | 22.0× | 8.2% | +39.5% |
| V2: rebalanceo semanal | +53.2% | 1.51 | -42.5% | 11.1× | 4.1% | +50.0% |
| V3: semanal + banda 4 pp + margen 15% | +54.8% | 1.53 | -44.6% | 9.7× | 3.6% | +30.7% |
| Referencia: BTC comprar y mantener | +49.2% | 0.97 | -76.7% | 0.0× | 0.0% | — |
| Referencia: BTC con filtro de 200 días (lunes) | +37.2% | 0.93 | -52.1% | 3.5× | 1.3% | — |

### Por año

| Variante | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| Control (diario, banda 2 pp) | +170.8% | -14.2% | +34.6% | +67.9% | -15.2% | +38.8% |
| V1: banda 4 pp + margen 15% | +194.6% | -13.5% | +39.4% | +66.0% | -11.8% | +39.0% |
| V2: rebalanceo semanal | +230.4% | -29.6% | +53.1% | +33.7% | +4.4% | +61.7% |
| V3: semanal + banda 4 pp + margen 15% | +256.0% | -30.5% | +63.5% | +22.9% | +0.5% | +62.8% |

## Criterios (umbral de bootstrap 0.967, corregido por 3 variantes)

| Variante | 1. Mayoría de años | 2. Bootstrap | 3. Caída máx. vs control | 4. Estrés vs control | Aprobada |
|---|---|---|---|---|---|
| V1: banda 4 pp + margen 15% | ✅ 5/6 | ❌ 0.807 | ✅ +1.8 pts | ✅ +4.4 pts | ❌ |
| V2: rebalanceo semanal | ✅ 4/6 | ❌ 0.886 | ❌ -5.7 pts | ✅ +14.8 pts | ❌ |
| V3: semanal + banda 4 pp + margen 15% | ✅ 4/6 | ❌ 0.907 | ❌ -7.9 pts | ❌ -4.5 pts | ❌ |

## Lectura

- **Veredicto: el control se conserva.** Ninguna variante cumple los cuatro criterios fijados antes de correr.
- **El costo de rotar es enorme:** el control rota su cartera ~30 veces al año y paga ≈11% del capital al año en costos. La estrategia aun así rinde ≈43% anual en esta ventana, con la mitad de la caída de BTC (−37% contra −77%).
- **V1 (banda 4 pp + margen 15%)** mejora todo: más rendimiento, menos caída, 5 de 6 años y aguanta el estrés. Pero la mejora es chica frente al ruido (bootstrap 0.81): no es concluyente con este histórico. Es la mejor candidata para observarla hacia adelante.
- **El rebalanceo semanal (V2, V3)** paga menos de la mitad en costos y rinde más en promedio, pero reacciona tarde en las caídas: 2022 con −30% contra −14%, y una caída máxima de 42–45%, en el límite del kill switch. Con costos de estrés, V3 llega a activarlo. Cambia el perfil de riesgo, no solo el costo.
- **Implicación:** con la señal actual, la forma más limpia de ganar más es abaratar **cada** operación (ejecución maker, comisión, universo líquido) sin cambiar cuáles se hacen. Ese ahorro llega casi entero al resultado, sin el ruido de cambiar el camino de la cartera.

## Limitaciones

- Histórico ya inspeccionado en estudios previos (retrospectivo, no holdout). Datos CoinMetrics/Yahoo, no el libro de Bitso. Costo constante por lado.
- La ventana incluye el mercado alcista de 2020–2021; el rendimiento pasado no se repite necesariamente.
