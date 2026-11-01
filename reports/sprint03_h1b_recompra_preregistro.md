---
protocol_version: 1
status: approved
experiment_id: sprint03-h1b-recompra
type: costo
approved_by: Claude, con la autonomía acordada por Brandon el 25-oct-2026 (DEC-030); tarea programada del domingo 1-nov-2026
date: 2026-11-01
---

# Sprint 03 — H1b: no recomprar una moneda recién vendida (preregistro)

Hipótesis de arriba de `research/backlog.yaml` (H1b). El plan la tenía para el 8-nov; el sprint 02 se adelantó al
25-oct, así que hoy toca. Tipo: **cambio de costo** (`AGENTS.md`, regla 3): misma señal, se bloquea la recompra
durante unos días después de una salida total. No se afirma mejor timing; el placebo no aplica.

**Hipótesis falsable:** si después de que una moneda sale del objetivo (peso objetivo pasa de > 0 a 0) se prohíbe
volver a comprarla durante N días, el bloque cripto rinde más neto de costos que el control en la mayoría de los
años 2021–2026, con bootstrap de la diferencia de rendimiento ≥ 0.95, caída máxima no peor por más de 2 puntos y
ventaja que se sostiene con costos ×1.5.

## La cuenta de costos (antes de correr las variantes)

1. Costo medido en el piloto (snapshot del 1-nov): 49 pb por movimiento desde el inicio, 57 pb en 30 días (sube por
   TRX: 165 pb al comprar el 30-oct y 197 pb al vender el 31-oct). El backtest usa 0.37% por lado, como el sprint 01–02.
2. El piloto registró 4 recompras en menos de 48 h en 30 días (LTC ×2, BTC, LINK). La de LINK: vendió US$44 el 30-oct
   y recompró US$36 el 31-oct, ≈US$0.5 de costo por nada.
3. Medición previa en el control (solo el control, sin variantes; 2019-01-01 → 2026-09-26): **26 reentradas al día
   siguiente de salir por año** (de 102 entradas al año), con peso medio de 15%; 39 por año en ≤ 2 días y 47 en ≤ 3.
4. Techo de ahorro con N = 2: 26 × 2 lados × 15% ≈ 7.8 veces el bloque al año de rotación (de ≈29) × 0.37% ≈
   **2.9 puntos al año**. Con N = 3, algo más. El riesgo: la moneda bloqueada era una que la señal quería, y se pierde
   su rendimiento esos días (efecto de camino, puede ser positivo o negativo).
5. No hace falta ganancia bruta nueva: es solo menos fricción.

## Control y variantes (exactas, 2 variantes)

Universo: las 16 monedas con par USD en Bitso (`BITSO_TRADABLE`), elegibles tras 250 días de historia. Parámetros de
`config.yaml`: `top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True, max_weight=0.40, mom_windows=(30, 90, 180)`,
banda 2 pp, kill switch −45%, **orden mínima US$25** (vigente desde DEC-033).

| ID | Regla |
|---|---|
| control | vigente |
| h1b-espera2 | tras una salida total decidida el día e, el peso objetivo de esa moneda queda en 0 los días e+1; la primera recompra posible es e+2 (≈48 h) |
| h1b-espera3 | igual, con primera recompra posible en e+3 (≈72 h) |

El peso bloqueado no se reparte: queda en efectivo (repartirlo cambiaría la selección, que es la señal). Se implementa
como `PortfolioParams.reentry_cooldown_days` (0 = apagado) aplicado al final de `target_weights`, compartido con el bot,
con prueba de «sin mirar al futuro» en `tests/`.

## Datos, simulador y ventana

- Precios diarios CoinMetrics/Yahoo de la caché (`data/crypto_prices.csv`), 2019-01-01 → 2026-09-26, igual que el
  sprint 02. **Evidencia retrospectiva**: 2021–2026 ya se inspeccionó en estudios previos; no es un holdout limpio.
- Simulador con efectivo (`simulate_funded_portfolio`), **modo A (decide)**: libro nuevo de US$500 cada 1 de enero,
  2021–2026, porque ese es el tamaño real del bloque y la orden mínima de US$25 importa a ese tamaño.
- Modo B (informativo): una corrida compuesta desde US$500, 2019-01-01 → 2026-09-26.
- Costo 0.37% por lado; estrés 0.555% (×1.5).

## Métricas y regla de decisión (fijadas antes de ver resultados)

Por variante, contra el control en modo A: CAGR neto, Sharpe, caída máxima, rotación al año, costo al año y
rendimiento por año. Una variante **se aprueba** si cumple las cuatro:

1. Mejor rendimiento neto en al menos 4 de los 6 años (2021–2026).
2. `bootstrap_compare(var, control, n=2000, block=30, seed=11)['p_return_better']` ≥ **0.95** (90% corregido por 2 variantes).
3. Caída máxima no peor que la del control por más de 2 puntos.
4. Con costos ×1.5, CAGR mayor que el del control con costos ×1.5.

Si las dos pasan, se elige la de mayor CAGR con estrés. Si pasa, va al piloto simulado con su DEC (o a un carril si
el riesgo de despliegue lo aconseja), con revisión a las 4 semanas. Si ninguna pasa, se conserva el control y H1b se
anota como descartada o no concluyente con su cifra. Cada variante se registra en `reports/intentos.csv`.
