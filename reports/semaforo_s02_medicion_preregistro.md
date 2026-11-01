---
protocol_version: 1
status: approved
experiment_id: semaforo-s02-medicion
type: medición (no cambia la estrategia)
approved_by: Brandon («si», 1-nov-2026 14:55 CDMX, a la propuesta de medir M1 y M2 en Bitso y en un exchange a 0.10%); Claude con la autonomía de DEC-030
date: 2026-11-01
---

# Semáforo de «ganadora»: medición del control en M1–M5 y M7 (preregistro)

Parte (a) del sprint S02 del plan «Un dominio y estrategia ganadora» (sección 2.1). El semáforo y sus umbrales están
preregistrados desde el 25-oct (`research/semaforo.yaml`) y no cambian. Aquí se fijan, antes de correr, los detalles
que el semáforo deja abiertos. No es una variante nueva: es el control vigente medido contra sus dos referencias, en
tres condiciones de costo externas. No se agregan filas a `reports/intentos.csv`.

## Escenarios (el control vigente, sin cambios en la regla)

| ID | Costo por lado del bloque cripto | Por qué |
|---|---:|---|
| bitso-medido | 0.49% | Lo que de verdad paga el piloto desde el 24-sep (snapshot del 1-nov) |
| bitso-modelo | 0.37% | El modelo de los sprints (informativo) |
| global-010 | 0.12% | Exchange global a 0.10% + 2 pb de medio spread (`reports/h7b_exchanges_mexico.md`) |

Bloque cripto: `top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True, max_weight=0.40, mom_windows=(30, 90, 180)`,
banda 2 pp, kill −45%, orden mínima US$25, 16 monedas de Bitso, US$500. Bloque ETFs: 60/40 SPY/IEF, banda 5 pp, kill
−25%, 0.05%, US$500. Cartera total = suma de los bloques, sin traspasos (como el piloto). Ventana 2019-01-01 →
2026-09-25, compuesta. **Railway: US$60 al año** (US$60/365 por día) restados de la cartera total en M1 (lo pide M7).

## Métricas y umbrales (los del semáforo, con los detalles fijados hoy)

- **M1 — contra el 60/40 (cartera total):** cartera total neta de Railway contra US$1,000 en el 60/40 (sin Railway).
  Pasa si gana en al menos 4 de los 6 años 2021–2026 **y** `bootstrap_compare(total, 60/40, n=2000, block=30,
  seed=11)['p_return_better']` ≥ 0.90.
- **M2 — contra BTC a igual riesgo (bloque cripto):** referencia «BTC + efectivo» con peso fijo w = volatilidad diaria
  del bloque / volatilidad diaria de BTC en la ventana, efectivo al 0% (como el del bot), rebalanceo con banda de 5 pp
  y el mismo costo por lado que el escenario (`simulate_portfolio`). Pasa si `p_return_better` ≥ 0.90. Contra BTC puro
  (comprar y mantener) se muestra sin umbral.
- **M3 — caída máxima con costos ×1.5:** cartera total ≤ 30% y bloque cripto ≤ 40%.
- **M4 — costo de operar del bloque cripto:** ≤ 6% al año y ≤ 1/3 de la ganancia bruta (bruta ≈ rendimiento neto
  anual + costo anual).
- **M5 — robustez:** M1 y M2 pasan también con costos ×1.5 (cripto y ETFs; Railway igual). No aplica placebo ni Sharpe
  deflactado: no es cambio de señal.
- **M6 — fidelidad en simulado:** no se mide en backtest. Se informa el estado del piloto en Bitso con el snapshot del
  1-nov (costo medido contra modelado + 20%, distancia al kill switch).
- **M7 — costo total:** comisiones + Railway, en US$ y como % del capital, informativo.

**Veredicto por escenario:** «ganadora en backtest» si pasa M1 a M5; M6 queda pendiente de las 4 semanas en el exchange
elegido. Los tres escenarios usan el umbral de 0.90 sin corrección: no se elige entre estrategias, se mide la misma
regla con costos externos distintos (lo que se decide es el exchange, y eso es de Brandon). Informativo: M1 sin Railway
(hosting propio).

## Limitaciones declaradas antes de correr

Histórico 2019–2026 ya inspeccionado (incluye la subida de 2020–2021): evidencia retrospectiva, no holdout. Spreads de
los globales supuestos. El peso w de M2 usa la volatilidad de toda la ventana (es la definición de «igual riesgo»).
