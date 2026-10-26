---
experiment_id: sprint02-costo-ejecucion
fecha: 2026-10-25
veredicto: H2: h2-min25; H8: aprobada en backtest; falta dato operativo; H4: análisis; prueba hacia adelante propuesta
---

# Sprint 02 — Abaratar cada operación sin cambiar cuáles se hacen (resultado)

Preregistro: `reports/sprint02_costo_ejecucion_preregistro.md` (commit `2f9cee4`, antes de correr). Script: `scripts/research/sprint02_costo_ejecucion.py`.
Ventana 2019-01-01 → 2026-09-26, 16 monedas de Bitso, costo 0.37% por lado (estrés 0.555%), kill switch −45%, umbral de bootstrap 0.967.

## H2 — Orden mínima (modo A: US$500 cada 1 de enero, 2021–2026)

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. con estrés |
|---|---:|---:|---:|---:|---:|---:|
| control | +36.2% | 1.18 | -36.6% | 33.1× | 12.3% | +28.8% |
| h2-min20 | +36.9% | 1.18 | -34.9% | 31.1× | 11.5% | +30.7% |
| h2-min25 | +41.0% | 1.26 | -33.7% | 30.2× | 11.2% | +34.4% |

| Variante | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| control | +166.5% | -13.6% | +34.9% | +68.3% | -16.1% | +34.3% |
| h2-min20 | +168.0% | -12.9% | +35.7% | +67.0% | -14.9% | +34.7% |
| h2-min25 | +195.5% | -13.6% | +39.1% | +67.7% | -10.8% | +35.1% |

Criterios:

| Variante | 1. Mayoría de años | 2. Bootstrap | 3. Caída vs control | 4. Estrés vs control | Aprobada |
|---|---:|---:|---:|---:|---:|
| h2-min20 | ✅ 5/6 | ❌ 0.599 | ✅ +1.7 pts | ✅ +1.8 pts | ❌ |
| h2-min25 | ✅ 4/6 | ✅ 0.971 | ✅ +2.9 pts | ✅ +5.6 pts | ✅ |

Sensibilidad **post hoc** (no decide; muestra si el efecto es una vecindad o un punto):

| Orden mínima | Rend. anual | Caída máx. | Costo/año | Bootstrap | Años > control |
|---:|---:|---:|---:|---:|---:|
| US$5 | +36.2% | -36.6% | 12.3% | — | 0/6 |
| US$10 | +36.0% | -37.0% | 12.2% | 0.127 | 1/6 |
| US$15 | +37.1% | -36.3% | 11.8% | 0.714 | 4/6 |
| US$20 | +36.9% | -34.9% | 11.5% | 0.600 | 5/6 |
| US$22 | +37.7% | -34.9% | 11.4% | 0.809 | 5/6 |
| US$24 | +40.1% | -34.1% | 11.3% | 0.910 | 4/6 |
| US$25 | +41.0% | -33.7% | 11.2% | 0.974 | 4/6 |
| US$26 | +41.4% | -33.9% | 11.0% | 0.980 | 5/6 |
| US$28 | +41.4% | -35.7% | 11.1% | 0.946 | 4/6 |
| US$30 | +40.8% | -32.4% | 10.7% | 0.906 | 6/6 |
| US$35 | +38.6% | -38.8% | 10.2% | 0.630 | 4/6 |
| US$40 | +45.7% | -36.0% | 10.1% | 0.982 | 5/6 |
| US$50 | +36.5% | -35.8% | 9.0% | 0.611 | 4/6 |

Modo B (informativo, una corrida compuesta desde US$500):

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. con estrés |
|---|---:|---:|---:|---:|---:|---:|
| control | +42.3% | 1.30 | -37.1% | 29.5× | 10.9% | +34.9% |
| h2-min20 | +42.5% | 1.31 | -37.1% | 29.3× | 10.8% | +35.2% |
| h2-min25 | +41.9% | 1.29 | -37.1% | 29.1× | 10.8% | +35.1% |

## H8 — Efectivo con rendimiento (superpuesto al control)

DTB3 promedio +2.7% en la ventana; último dato +4.0% (2026-10-22). Efectivo promedio del control: 67%.

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. con estrés |
|---|---:|---:|---:|---:|---:|---:|
| control | +42.7% | 1.31 | -36.7% | 29.6× | 10.9% | +35.2% |
| h8-tbill | +44.5% | 1.35 | -34.8% | 29.6× | 10.9% | +37.0% |
| info-tbill-completa | +45.1% | 1.37 | -34.1% | 29.6× | 10.9% | +37.6% |
| info-4pct-fija | +46.6% | 1.40 | -32.8% | 29.6× | 10.9% | +38.9% |

Criterios (h8-tbill):

| Variante | 1. Mayoría de años | 2. Bootstrap | 3. Caída vs control | 4. Estrés vs control | Aprobada |
|---|---:|---:|---:|---:|---:|
| h8-tbill | ✅ 6/6 | ✅ 1.000 | ✅ +1.9 pts | ✅ +1.8 pts | ✅ |

## H4 — Más órdenes maker (análisis de fills del piloto, no backtest)

- 38 fills cripto en 30 días; 18 con metadata de ejecución. Solo **6** se llenaron como maker; 24% maker por importe.
- Las órdenes maker se llenaron en 36–139 s; las que no, agotaron la espera (media 141 s) y fueron a mercado.
- Costo medio: 28.8 pb cuando maker, 39.5 pb cuando taker.
- Órdenes menores a US$20: 7 de 38, US$92 (3.9% del importe).

| Moneda | Ops | Importe US$ | Costo medio pb | Spread medio pb |
|---|---:|---:|---:|---:|
| NEAR | 1 | 16 | 55.3 | — |
| UNI | 1 | 20 | 43.7 | — |
| LTC | 8 | 594 | 43.2 | 21.6 |
| SOL | 8 | 375 | 34.0 | 4.2 |
| BTC | 4 | 394 | 33.2 | 1.6 |
| ETH | 6 | 578 | 32.7 | 0.9 |
| LINK | 3 | 55 | 30.3 | 22.4 |

## Lectura

- **H2, orden mínima de US$25: aprobada por la barra preregistrada** (modo A, US$500 cada año): +41.0% anual contra +36.2% del control, caída máxima -33.7% contra -36.6%, 4 de 6 años, bootstrap 0.971 (umbral 0.967) y aguanta el estrés. US$20 no es concluyente (0.599).
- **Con cautela:** el ahorro en costos es de ≈1 punto al año (12.3% → 11.2%), pero la mejora de rendimiento es de ≈5 puntos. El resto viene de que, al no hacer ajustes chicos, la cartera sigue otro camino (sobre todo 2021 y 2025). Es un efecto de camino, no una ganancia de costos pura, y el bootstrap pasa por poco. La sensibilidad post hoc muestra una vecindad consistente entre US$24 y US$30 (rendimiento de 40–41%, caída de 32–36%) y ruido a partir de US$35; con el capital compuesto (modo B) el efecto desaparece porque US$25 deja de ser relevante cuando el bloque vale miles.
- **Qué cambia:** `min_order_value` del bloque cripto pasa de 5 a 25 en `config.yaml` (DEC-033). Misma señal, mismas reglas; solo no se ejecutan ajustes menores a US$25 (7 de 38 órdenes del último mes). Se revisa a las 4 semanas contra el control recalculado en los mismos días; si el costo medido no baja o la cartera se desvía más de lo esperado, se revierte.
- **H8, efectivo con rendimiento: aprobada en backtest, pero «falta dato» para operarla.** Con el T-bill menos 25%, +44.5% contra +42.7%, 6 de 6 años, caída 1.9 puntos menor. Con la tasa actual (4.0%) y 67% de efectivo promedio, vale ≈+2 puntos al año sin tocar la señal. Lo que falta: la tasa real que paga la plataforma sobre el efectivo ocioso (Bitso+ paga sobre stablecoins en USD, no sobre USD fiat), si el retiro es inmediato y si mover el dinero cuesta. Sin eso no entra al piloto. Es un dato que decide Brandon al elegir exchange (H7).
- **H4, más órdenes maker: sin veredicto por backtest.** De 18 órdenes con dato, solo 6 se llenaron como maker (29 pb) y el resto fue a mercado al agotar los 120 s (39 pb). El techo de la mejora es ≈2 puntos al año. Propuesta preregistrada: subir `execution.wait_s` de 120 a 300 s y medir 4 semanas (éxito: ≥50% maker por importe y costo ≤ 33 pb). Es un cambio de ejecución en simulado; Brandon decide si se activa junto con DEC-033 o después.
- **Dato nuevo para H6 (universo):** LTC costó 43 pb de promedio con 22 pb de spread, contra 33 pb de BTC/ETH; LINK y NEAR también son caros. El universo de 16 monedas incluye pares poco líquidos en Bitso USD.

## Limitaciones

- Histórico ya inspeccionado (retrospectivo, no holdout). Datos CoinMetrics/Yahoo, no el libro de Bitso. Costo constante por lado.
- H2 en modo A reinicia el libro cada año: aísla el tamaño de US$500, pero no es un camino compuesto real.
- H8 supone que el efectivo se mueve a diario sin costo ni demora, y que la plataforma paga una tasa cercana a la del T-bill; ninguna de las dos está verificada.
- H4: 18 órdenes con metadata es muy poco para concluir; el modelo de llenado maker del simulador es conservador.
