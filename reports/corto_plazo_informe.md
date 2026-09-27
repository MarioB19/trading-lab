# ¿Estrategias de corto plazo en cripto?

Prueba declarada antes de correrla en `reports/corto_plazo_preregistro.md`. Velas de 1 hora de 2020-01-01 a 2026-09-27; fuera de muestra desde 2021; costo 0.45% por operación; solo compras; sin kill switch (se reporta aparte).

| Estrategia | Rend. anual | Sharpe | Caída máx. | Operaciones al año* | Costo al año | Sin costos | Con 0.30% | Veredicto |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| R0 · bot diario actual | 21.6% | 0.81 | −50% | 139 | 12.1% | – | 25.9% | referencia |
| C1 · Reversión: las 3 que más cayeron en 24 h, cada 4 h | −99.9% | -8.14 | −100% | 1767 | 725.0% | 66.4% | −98.7% | no aprobada |
| C2 · Reversión con umbral: caída de más de 5% en 24 h | −70.6% | -2.30 | −100% | 712 | 204.4% | 128.0% | −41.7% | no aprobada |
| C3 · Ruptura: máximo de 24 h / mínimo de 12 h | −97.6% | -6.16 | −100% | 2544 | 374.0% | 2.4% | −91.6% | no aprobada |
| C4 · Ruptura: máximo de 72 h / mínimo de 36 h | −57.6% | -1.23 | −100% | 1100 | 128.7% | 53.8% | −34.8% | no aprobada |

\* Revisiones en las que se operó al menos un activo.

## Criterios

**C1 · Reversión: las 3 que más cayeron en 24 h, cada 4 h: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-8.135, 0.814)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.000)
- ❌ Placebo p < 0.05 (0.410)
- ❌ Caída máxima no peor que R0 por más de 1 punto (-1.000, -0.503)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-11.230, 0.695)

**C2 · Reversión con umbral: caída de más de 5% en 24 h: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-2.301, 0.814)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.000)
- ✅ Placebo p < 0.05 (0.000)
- ❌ Caída máxima no peor que R0 por más de 1 punto (-0.999, -0.503)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-3.660, 0.695)

**C3 · Ruptura: máximo de 24 h / mínimo de 12 h: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-6.156, 0.814)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.000)
- ❌ Placebo p < 0.05 (0.510)
- ❌ Caída máxima no peor que R0 por más de 1 punto (-1.000, -0.503)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-8.192, 0.695)

**C4 · Ruptura: máximo de 72 h / mínimo de 36 h: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-1.227, 0.814)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.000)
- ✅ Placebo p < 0.05 (0.000)
- ❌ Caída máxima no peor que R0 por más de 1 punto (-0.998, -0.503)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-1.963, 0.695)

## Qué se decidió

Ninguna variante pasó. No se agrega nada; el bot sigue operando una vez al día.

## Notas

- Con kill switch de 45%: C1 0.0%; C2 −4.6%; C3 −1.0%; C4 9.5%; R0 −0.1% anual.
- La banda de 2 puntos solo evita rebalancear por la deriva de precios: entrar o salir de una cripto siempre se opera, como dice el pre-registro.
- "Sin costos" muestra si la regla tiene alguna ventaja antes de pagar comisiones. Parte de esa ventaja en velas de 1 hora es ilusoria: el cierre de cada hora cae a veces en el precio de compra y a veces en el de venta, y ese rebote no se puede capturar.
- Rendimiento anual según el costo por operación: C1: 0.05% → −25.7%, 0.10% → −66.8%, 0.15% → −85.2%, 0.20% → −93.4%; C2: 0.05% → 81.7%, 0.10% → 44.8%, 0.15% → 15.3%, 0.20% → −8.1%; C3: 0.05% → −32.4%, 0.10% → −55.4%, 0.15% → −70.6%, 0.20% → −80.6%; C4: 0.05% → 33.3%, 0.10% → 15.6%, 0.15% → 0.2%, 0.20% → −13.2%. Bitso cobra como mínimo 0.30% (orden límite) en el nivel de volumen más bajo.
