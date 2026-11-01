---
protocol_version: 1
status: approved
experiment_id: sprint04-h13-rebalanceo-bloques
type: costo
approved_by: Brandon («la mejor, te doy permiso», 1-nov-2026 14:16 CDMX, tras la propuesta de Claude de probar el rebalanceo entre bloques); Claude con la autonomía de DEC-030
date: 2026-11-01
---

# Sprint 04 — H13: rebalancear entre el bloque cripto y el de ETFs (preregistro)

Hoy los dos bloques del piloto arrancaron con US$500 cada uno (reparto 50/50 decidido por Brandon) y nunca se pasan
dinero: cada uno se capitaliza por su cuenta, así que el reparto deriva (el 31-oct iba ≈45% cripto / 55% ETFs). La
idea es devolverlo a 50/50 cuando se aleje. No cambia qué compra cada bloque ni cuándo: es la estructura de la cartera.
Tipo: **cambio de costo/estructura** (`AGENTS.md`, regla 3: «frecuencia de rebalanceo»). No se afirma timing; el
placebo no aplica. Pedida por Brandon el 1-nov como la primera de las «otras formas de operar».

**Hipótesis falsable:** devolver la cartera a 50/50 entre bloques cuando el peso de cripto sale de una banda (o una vez
al año) rinde más neto de costos y fricción que dejar los bloques sin traspasos, en la mayoría de los años 2021–2026,
con bootstrap de la diferencia de rendimiento ≥ 0.967, caída máxima no peor por más de 2 puntos y ventaja que se
sostiene con costos ×1.5.

## La cuenta (antes de correr las variantes)

Con cifras ya publicadas (no se corrió ninguna variante):

1. Bloque cripto (control, `reports/sprint03_h1b_recompra_resultado.json`, modo B 2019–2026): +41.9% anual, volatilidad 30.8%.
   Bloque ETFs (60/40, `reports/catalogo2_etf_resultado.json`, 2008–2026): +8.5% anual, volatilidad 11.3%.
2. **Prima de rebalanceo** frente al promedio de los crecimientos logarítmicos: ½[Σwσ² − σ²cartera]. Con correlación
   supuesta de 0.3 entre bloques: ½(0.0539 − 0.0322) ≈ **1.1 puntos al año**.
3. **Pero el control no es ese promedio.** Sin traspasos, el bloque que más crece pesa cada vez más. Con esas cifras, en
   7.7 años: sin rebalanceo ≈ **+31.7% anual**; rebalanceado ≈ **+25.4% anual**. La brecha de crecimiento entre bloques
   (≈0.27 en logaritmos al año) es mucho mayor que la prima (≈0.011). **Expectativa a priori: las variantes pierden
   rendimiento y ganan en caída máxima.** Se corre igual porque Brandon lo pidió y porque la respuesta define una
   decisión suya: mantener 50/50 de capital o dejar que el reparto derive.
4. Fricción: cada traspaso paga el costo de cripto (0.37%) + ETFs (0.05%) + **traspaso entre plataformas 1.0%**
   (supuesto conservador: retiro de Bitso, conversión de divisas y depósito en el bróker; sin dato medido) ≈ 1.42% de lo
   que se mueve. Con banda de 15 pp se mueve ≈15% de la cartera por evento, ≈0.2% de la cartera por traspaso, 1–2 al año.
5. Con dinero real, cada traspaso lo haría Brandon a mano (regla dura 2: Claude no hace transferencias).

## Control y variantes (exactas, 3 variantes)

| ID | Regla |
|---|---|
| control | vigente: sin traspasos; cada bloque se capitaliza por separado desde 50/50 |
| h13-banda10 | al cierre de cada día, si el peso de cripto sale de 40–60%, se devuelve a 50/50 |
| h13-banda15 | igual con banda 35–65% |
| h13-anual | al cierre de cada 31 de diciembre se devuelve a 50/50 |

Mecánica: al cierre del día t se suman los rendimientos del día de cada bloque; si toca, se mueve X = |E_cripto − 50% del
total| del bloque sobrepesado al otro y el receptor recibe X × (1 − fricción). La decisión usa solo datos hasta t. Se
implementa en `lab.sleeve_rebalance` con pruebas: el control (sin regla) es exactamente la suma de los dos bloques sin
traspasos, y «sin mirar al futuro» (cambiar rendimientos después de t no cambia los traspasos hasta t).

## Datos, simulador y ventana

- Bloque cripto: el control vigente (`top_k=5, vol_target=0.40, regime_asset=BTC, dd_brake=True, max_weight=0.40,
  mom_windows=(30, 90, 180)`, banda 2 pp, kill −45%, orden mínima US$25) con `simulate_funded_portfolio`, US$500, costo
  0.37% por lado, 16 monedas de Bitso, caché CoinMetrics/Yahoo.
- Bloque ETFs: 60% SPY / 40% IEF, banda 5 pp, kill −25% como el piloto (`simulate_portfolio`), costo 0.05%, caché Yahoo.
  Sus rendimientos se pasan a días de calendario (0 los días sin bolsa).
- Ventana: **2019-01-01 → 2026-09-25**, una sola corrida compuesta desde US$1,000 (aquí no sirve el modo A de los sprints
  previos: reiniciar 50/50 cada año ya es rebalanceo anual). Años comparados: 2021–2026 del mismo camino (2026 parcial).
- **Evidencia retrospectiva**: 2019–2026 ya se inspeccionó; no es un holdout limpio. Seis años y medio incluyen un solo
  ciclo grande de cripto.
- Supuesto de simulación: los rendimientos de cada bloque no dependen de su tamaño (la orden mínima y las bandas internas
  se ignoran al mover dinero) y el freno del bloque cripto no se distorsiona por los traspasos (en el bot habría que
  ajustar el pico por flujos).
- Estrés ×1.5 en todo: cripto 0.555%, ETFs 0.075%, traspaso 1.5%.

## Métricas y regla de decisión (fijadas antes de ver resultados)

Por variante y control: CAGR neto, volatilidad, Sharpe, caída máxima, número de traspasos, fricción pagada, peso medio y
máximo de cripto, y rendimiento por año. Una variante **se aprueba** si cumple las cuatro:

1. Mejor rendimiento neto que el control en al menos 4 de los 6 años (2021–2026).
2. `bootstrap_compare(var, control, n=2000, block=30, seed=11)['p_return_better']` ≥ **0.967** (90% corregido por 3 variantes).
3. Caída máxima no peor que la del control por más de 2 puntos.
4. Con costos ×1.5, CAGR mayor que el del control con costos ×1.5.

Informativo (no decide): `p_sharpe_better` y `p_drawdown_smaller` del mismo bootstrap; fricción 0% (el piloto simulado no
paga traspasos); y **inicio móvil**: la misma comparación arrancando cada 1 de enero de 2019 a 2024 hasta el final, porque
con traspasos el resultado depende mucho de dónde empieza el camino.

Si una pasa: **no se despliega sin decisión explícita de Brandon**, porque con dinero real exige traspasos entre
plataformas (regla dura 2) y toca su reparto 50/50; se le presenta con su DEC propuesto. Si ninguna pasa pero alguna baja
la caída con un costo de rendimiento claro, se le presenta como decisión de riesgo (igual que H12), no como ganadora.
Si nada de eso, se conserva el control y H13 va a descartadas con su cifra. Cada variante se registra en
`reports/intentos.csv`.
