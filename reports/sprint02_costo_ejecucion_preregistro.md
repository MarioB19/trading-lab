---
protocol_version: 1
status: approved
experiment_id: sprint02-costo-ejecucion
type: costo
approved_by: Claude, con la autonomía acordada por Brandon el 25-oct-2026 (DEC-030); sprint adelantado del 1-nov al 25-oct a petición de Brandon
date: 2026-10-25
---

# Sprint 02 — Abaratar cada operación sin cambiar cuáles se hacen (preregistro)

Sigue al sprint 01: con la señal vigente, la palanca más limpia es pagar menos por **cada** operación.
Se prueban tres hipótesis del backlog (`research/backlog.yaml`): H2 (orden mínima), H8 (efectivo con
rendimiento) y H4 (más órdenes maker). Tipo: **cambio de costo** (`AGENTS.md`, regla 3). No se afirma
un mejor timing: el placebo no aplica.

## La cuenta de costos (antes de escribir código)

Datos del piloto, 30 días al 25-oct (`/api/execution-quality` y `/api/trades`):

1. Costo medido por movimiento: **36.7 pb** sobre 31 operaciones medidas contra el libro; 24% maker por importe.
   La comisión taker de Bitso (36 pb) es casi todo el costo; el medio spread aporta 0.1–15 pb según la moneda
   (BTC/ETH 0.1–2.6 pb de spread; LTC 12–30 pb; LINK 22 pb).
2. **H2.** 7 de 38 operaciones fueron menores a US$20 (SOL, LINK, NEAR, de US$10–19), pero sumaron US$92 de
   US$2,151 negociados (4.3%). Techo de ahorro ≈ 4% del costo anual (11%) ≈ **0.5 puntos al año**. Gratis,
   pero chico; también puede cambiar el camino de la cartera (polvo que no se vende).
3. **H4.** A 100% maker el costo bajaría de 36.7 a ≈30 pb (6 pb de comisión más medio spread): el costo anual
   pasaría de ≈11% a ≈9%, **≈2 puntos al año**. Hoy solo 5 de 18 órdenes con dato se llenaron como maker
   (todas en 36–105 s); las 13 restantes agotaron los 120 s de espera y fueron a mercado. **No se puede
   backtestear:** no hay histórico del libro. Su evidencia es el registro de fills del piloto.
4. **H8.** El control está invertido en promedio 33% (2019–2026) y 66% en el último mes: el resto es efectivo
   sin rendimiento. Con la tasa de T-bill a 3 meses (DTB3, promedio ≈2.3% en 2019–2026; 4.0% hoy) el techo es
   **+1.5 a +2.7 puntos al año**, sin tocar la señal. Depende de que el exchange pague rendimiento sobre el
   efectivo ocioso (Bitso+ lo paga sobre stablecoins en USD, no sobre USD fiat) y de que mover el dinero sea
   inmediato y sin costo.
5. Ninguna de las tres necesita ganancia bruta nueva: no hay idea de señal en este sprint.

## Control y variantes (exactas)

Universo: las 16 monedas con par USD en Bitso (`BITSO_TRADABLE`), elegibles tras 250 días de historia.
Parámetros comunes (los de `config.yaml`): `top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True,
max_weight=0.40, mom_windows=(30, 90, 180)`, banda 2 pp, kill switch −45%.

### H2 — orden mínima (simulador con efectivo, `lab.portfolio.simulate_funded_portfolio`)

El simulador con efectivo (US$500 de capital, compras financiadas con el efectivo disponible, órdenes
menores al mínimo no se ejecutan) es el que puede representar una orden mínima. Se corre en dos modos:

- **Modo A (el que decide): capital reiniciado a US$500 cada 1 de enero, 2021–2026.** Es el tamaño real del
  bloque; con interés compuesto desde 2019 el capital crece y una orden de US$20 deja de importar.
- Modo B (informativo): una sola corrida compuesta 2019-01-01 → 2026-09-26 desde US$500.

| ID | `min_order_value` | Resto |
|---|---:|---|
| control | US$5 (vigente) | igual |
| h2-min20 | US$20 | igual |
| h2-min25 | US$25 | igual |

### H8 — efectivo con rendimiento (superpuesto al control)

Sobre el control del modo B (simulador clásico `simulate_portfolio`, costo 0.37%), el efectivo no invertido
cada día `(1 − exposición)` devenga la tasa DTB3 del día anterior hábil (`research/series/dtb3.csv`, FRED, base 360), sin
costo de entrada ni salida. Una variante:

| ID | Tasa sobre el efectivo |
|---|---|
| control | 0% |
| h8-tbill | DTB3 × 0.75 (descuento de 25% por comisión y spread de la plataforma que lo pague) |

Informativo: la misma superposición con DTB3 completa, y con una tasa fija de 4%.

### H4 — más órdenes maker (análisis de fills, no backtest)

Se analiza el registro de fills del piloto (`/api/trades`, 18 órdenes con metadata de ejecución al 25-oct):
proporción maker, tiempo de llenado, spread por moneda y costo en pb por moneda y por lado. **No se puede
aprobar ni descartar con backtest.** Se preregistra una prueba hacia adelante, que Brandon decide si activar:

- Cambio propuesto: `execution.wait_s` de 120 a 300 s (dentro de `budget_s` 480). Misma señal, mismas órdenes.
- Criterio de éxito a 4 semanas: proporción maker por importe ≥ 50% **y** costo medido ≤ 33 pb, sin ciclos
  fallidos por presupuesto de tiempo. Si no se cumple, se revierte a 120 s.

## Datos y ventana

- `data/crypto_prices.csv` (CoinMetrics/Yahoo, cierres diarios hasta 2026-09-26), cargador `lab.data.load_crypto_panel`.
- `research/series/dtb3.csv`: T-bill a 3 meses, FRED serie DTB3, 2018-12-03 → 2026-10-22, descargada el 25-oct-2026.
- Evaluación 2019-01-01 → 2026-09-26; comparación año por año 2021–2026 (2026 parcial).
- **Honestidad:** este histórico ya se inspeccionó en estudios previos y en el sprint 01. Es evidencia
  retrospectiva, no un holdout limpio. La evidencia hacia adelante será el piloto simulado.

## Costos

- Base: **0.37% por lado** (medido en Bitso). Estrés: **0.555% por lado** (×1.5).

## Métricas y regla de decisión (fijadas antes de correr)

Para cada variante contra el control, con costo base salvo que se indique:

1. Mejor rendimiento neto en la mayoría de los años 2021–2026 (al menos 4 de 6). Para H2, años del modo A.
2. Bootstrap por bloques de 30 días (`lab.validation.bootstrap_compare`, 2000 remuestreos, semilla 11) sobre
   los retornos diarios de la serie evaluada: `p_return_better` ≥ **0.967** (0.90 corregido por 3 variantes:
   h2-min20, h2-min25, h8-tbill).
3. Caída máxima no peor que la del control por más de 2 puntos.
4. Con costo de estrés, rendimiento anual compuesto mayor que el del control.

Se aprueba la variante que cumpla los cuatro criterios. Si pasan h2-min20 y h2-min25, se elige la de mayor
rendimiento con estrés. H8 aprobada en backtest **no entra al piloto** hasta tener la tasa real de la plataforma
y la mecánica de mover el efectivo: su veredicto operativo será «falta dato» con la cifra que justifica
conseguirlo. Si ninguna pasa, el control sigue y se anota el motivo.

Se reportan también: Sharpe, rotación anual, costo anual, años con resultado. Las 3 variantes se suman a
`reports/intentos.csv`. H4 se registra como análisis, sin Sharpe (no es una variante de backtest).

## Semáforo de «ganadora»

Con este commit queda preregistrado `research/semaforo.yaml` (M1–M7) tal como lo propuso el plan del 25-oct,
sin cambios. Lo que este sprint mide del control se anota ahí después de correr; los umbrales no se tocan.
