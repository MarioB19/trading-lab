---
experiment_id: catalogo100
fecha: 2026-10-30
veredicto: ninguna de las 103 estrategias supera al control tras corregir por comparación múltiple; se conserva el control
---

# Catálogo 100 — Barrido de 103 estrategias contra el control (resultado)

Preregistro: `reports/catalogo100_preregistro.md` (commits `b4b378a` y `1919273`, antes de correr; hash del plan
`5214792904311b2c5dde03478fa39664e7d3595bc156b26051e4f92294f74d35`). Script: `scripts/research/catalogo100.py`;
definiciones: `src/lab/catalog.py`. Datos: velas diarias de OKX (USDT) 2018–2026 para las 16 monedas de Bitso y SPY
hasta 2026-09-25. Evaluación 2019-01-01 → 2026-10-30, costo 0.42% por lado (estrés 0.63%), banda 2 pp, kill −45%.

## Resultado en una línea

**Ninguna gana.** 2 variantes cayeron por costos, 101 entraron al barrido y **ninguna avanzó**: la mejor ventaja
observada sobre el control es la que se espera por azar entre 101 intentos (p global = 0.69; la mejor variante
individual tiene p sin corregir = 0.08 y corregida = 0.69). Las 103 quedan en `reports/intentos.csv`; el Sharpe
deflactado de cualquier candidata futura cuenta ahora 155 intentos.

| Control (regla vigente) | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Con estrés |
|---|---:|---:|---:|---:|---:|---:|
| tendencia + momentum, top 5, vol 40%, régimen BTC, freno | +38.3% | 1.19 | −34.3% | 30.7× | 12.9% | +29.8% |

De las 103: 16 tienen Sharpe mayor que el control, 14 más rendimiento, 23 menor caída. Ninguna las tres cosas
con significancia.

## Lo mejor de cada familia

| Familia | Mejor variante | Rend. anual | Sharpe | Caída máx. | Rot./año | p corregida |
|---|---|---:|---:|---:|---:|---:|
| F4 ruptura Donchian | `donchian-55-20-equal` | **+53.4%** | **1.34** | −37.3% | 15.9 | 0.69 |
| F9 reparto y número de activos | `control-topk-2` | +49.1% | 1.35 | −32.8% | 25.9 | 0.83 |
| F6 stop ATR sobre el control | `atrstop-3x-wait14` | +41.5% | 1.28 | −36.4% | 32.2 | 0.99 |
| F8 universo y liquidez | `subset-btc-eth` | +34.5% | 1.24 | **−28.5%** | 10.5 | 1.00 |
| F7 freno y kill switch | `control-ddbrake-5-20` | +35.9% | 1.23 | −27.1% | 25.0 | 1.00 |
| F17 banda de rebalanceo | `control-band-10` | +38.8% | 1.21 | −29.7% | 22.5 | 1.00 |
| F5 baja volatilidad | `control-voltarget-30` | +30.6% | 1.17 | −29.0% | 25.5 | 1.00 |
| F10 régimen macro (SPY) | `spy-and-btc-regime` | +33.5% | 1.14 | −31.6% | 27.3 | 1.00 |
| F14 ensambles | `ensemble-avg4` | +34.6% | 1.08 | −38.4% | 14.6 | 1.00 |
| F11 temporada de altcoins | `altseason-ethbtc-50` | +27.0% | 1.04 | −33.0% | 26.4 | 1.00 |
| F1 momentum transversal | `xsmom-w60-skip0` | +30.0% | 1.03 | −39.7% | 23.3 | 1.00 |
| F2 momentum temporal | `tsmom-sma-30` | +23.8% | 1.02 | −45.3% | 15.7 | 1.00 |
| F18 régimen de volatilidad | `control-volregime-x50` | +24.9% | 0.98 | −31.3% | 29.3 | 1.00 |
| F16 momentum dual | `dualmom-90` | +23.2% | 0.83 | −37.0% | 22.7 | 1.00 |
| F3 cruce de promedios | `macross-sma-100-300` | +18.7% | 0.83 | −45.7% | 2.0 | 1.00 |
| F13 reversión semanal | `weekrev-w7-k5` | +19.2% | 0.74 | −33.0% | 18.4 | 1.00 |
| F12 calendario (solo BTC) | `calendar-mid_month` | +15.0% | 0.64 | −45.2% | 8.3 | 1.00 |
| F15 aprendizaje automático | `ml-logistic` | +3.0% | 0.40 | −14.9% | 2.8 | 1.00 |

Referencias: BTC comprar y mantener +21.5% (Sharpe 0.77, −49.8%); BTC/ETH 50/50 +28.5% (0.91, −45.7%); pesos iguales
mensual +36.5% (1.01, −46.4%); BTC con filtro de 200 días +17.2% (0.68, −45.9%). Descartadas por costos (rotación
> 40): `xsmom-w14-skip0` (46.9) y `xsmom-w14-skip7` (47.8). Tabla completa de las 103 en `catalogo100_resultado.json`.

### Las dos que más se acercaron, por año

| | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (a oct) | Años que gana |
|---|---:|---:|---:|---:|---:|---:|---:|
| Control | +155% | −8% | +56% | +58% | −25% | +17% | — |
| `donchian-55-20-equal` | +131% | −2% | **+143%** | +64% | −15% | +3% | 4/6 |
| `control-topk-2` | +235% | −11% | +59% | +43% | −24% | +44% | 4/6 |

La ventaja de Donchian 55/20 está casi toda en **un año** (2023: +143% contra +56%); en 2021 y 2026 pierde contra el
control. La de top 2 está en 2021 y 2026, con la mitad de activos (más concentración, no más ventaja).

## Lectura

- **El control ya es una de las mejores reglas del catálogo.** Era de esperar: se eligió sobre este mismo histórico.
  Con 104 reglas comparables, solo 16 tienen mejor Sharpe y ninguna por un margen que el azar no explique.
- **No hay familia que cambie el juego.** Cruces de promedios, momentum temporal, ML, calendario, reversión semanal y
  momentum dual rinden claramente **peor** que el control (Sharpe 0.4–1.0 contra 1.19). Los ensambles y el régimen
  macro quedan parejos. Las ideas de «señal nueva» no aportan sobre tendencia + momentum con estos costos.
- **Donde sí hay algo que mirar hacia adelante, sin aprobarlo:** la ruptura Donchian 55/20 con pesos iguales rinde
  +15 puntos anuales más que el control con **la mitad de la rotación** (16 contra 31; ≈6 puntos anuales menos en
  costos) y aguanta mejor el estrés (+48.8% contra +29.8%). Pero su ventaja depende de 2023 y no sobrevive la
  corrección (p = 0.69). La forma honesta de saber si es real no es otro backtest: es un **carril** de 4 semanas en
  simulado, en los mismos días que el control. Es una propuesta para Brandon, no una decisión.
- **Las variantes de riesgo** (vol objetivo 30%, freno 5–20, solo BTC+ETH, banda 10 pp) no ganan más, pero recortan la
  caída máxima 5–7 puntos con Sharpe igual o mejor. Si Brandon prefiere menos caída a más rendimiento, es ahí donde
  está la palanca, y son cambios de costo/riesgo, no de señal.
- **Lo que la petición original habría producido:** iterar «hasta que una gane» habría promovido Donchian 55/20 o
  top 2 con un backtest de +50% anual. El test corregido dice que esa cifra no se distingue de la suerte. Eso es
  exactamente lo que el protocolo está para evitar.

## Limitaciones

- Histórico ya inspeccionado por 52 intentos previos y usado para elegir el control: retrospectivo, no holdout.
- Velas OKX en USDT y costo constante por lado; SPY termina el 25-sep-2026 (último mes de F10 con el último valor).
- Parámetros canónicos sin ajustar. El ML no se afinó (a propósito). Las familias con estado se evaluaron con el
  mismo freno y kill switch del control, lo que favorece al control en las comparaciones de riesgo.
- Un buen backtest no demuestra ganancias futuras; la evidencia es hacia adelante.
