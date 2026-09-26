# ¿Operar en tiempo real mejora al bot cripto?

Prueba declarada antes de correrla en `reports/tiempo_real_preregistro.md`. Velas de 1 hora (Coinbase y Bitstamp) de 2020-01-01 a 2026-09-26; fuera de muestra desde 2021; costo 0.45% por operación; misma regla y mismos candados que el bot. Solo cambia cada cuánto revisa.

| Variante | Rend. anual | Sharpe | Caída máx. | Rebalanceos al año | Costo al año | Veredicto |
|---|---:|---:|---:|---:|---:|---|
| R0 · Una vez al día, 00:00 UTC (lo que hace hoy el bot) | −0.1% | 0.08 | −45% | 50 | 4.2% | referencia |
| R1 · Cada 4 horas | −1.5% | -0.00 | −44% | 135 | 8.9% | no aprobada |
| R2 · Cada hora | −2.3% | -0.10 | −45% | 162 | 9.3% | no aprobada |
| R3 · Vigía: rebalanceo diario; freno y kill switch cada hora | 0.0% | 0.09 | −45% | 52 | 4.1% | no aprobada |

## Criterios

**R1 · Cada 4 horas: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-0.004, 0.079)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.228)
- ❌ Placebo p < 0.05 (0.180)
- ✅ Caída máxima no peor que R0 por más de 1 punto (-0.440, -0.454)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-0.082, 0.068)

**R2 · Cada hora: no aprobada**
- ❌ Sharpe fuera de muestra mayor que R0 (-0.100, 0.079)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.179)
- ❌ Placebo p < 0.05 (0.060)
- ✅ Caída máxima no peor que R0 por más de 1 punto (-0.447, -0.454)
- ❌ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (-0.228, 0.068)

**R3 · Vigía: rebalanceo diario; freno y kill switch cada hora: no aprobada**
- ✅ Sharpe fuera de muestra mayor que R0 (0.087, 0.079)
- ❌ Bootstrap: P(Sharpe mejor que R0) ≥ 80% (0.647)
- ❌ Placebo p < 0.05 (0.220)
- ✅ Caída máxima no peor que R0 por más de 1 punto (-0.447, -0.454)
- ✅ Con 0.60% por operación, Sharpe mayor que R0 con 0.60% (0.073, 0.068)

## Análisis adicional (no pre-registrado; no cambia la decisión)

Con este universo las cuatro variantes tocan el kill switch de 45% (R0: 2023-06-08) y después quedan en efectivo, así que la comparación de 2023 en adelante es plana. Sin kill switch se ve el efecto de revisar más seguido en todo el periodo:

| Variante | Rend. anual | Sharpe | Caída máx. | Costo al año |
|---|---:|---:|---:|---:|
| R0 · Una vez al día, 00:00 UTC (lo que hace hoy el bot) | 21.6% | 0.81 | −50% | 12.1% |
| R1 · Cada 4 horas | 12.9% | 0.56 | −51% | 26.4% |
| R2 · Cada hora | −8.3% | -0.19 | −71% | 42.8% |
| R3 · Vigía: rebalanceo diario; freno y kill switch cada hora | 22.5% | 0.84 | −50% | 12.0% |

## Qué se decidió

Ninguna variante pasó. El bot sigue operando una vez al día y el motor en tiempo real queda en **modo observación**: cada hora actualiza valuación, caída y precios, sin operar.

## Notas

- Control: la referencia simulada por hora da −0.1% anual y el simulador diario sobre los mismos cierres −0.1%; el motor por hora reproduce al diario.
- El universo es el del bot, con historia por hora en esas fuentes: SOL, ADA, DOGE, AVAX, HBAR y NEAR entran más tarde que en la investigación diaria y TRX casi no tiene historia. Por eso el rendimiento absoluto no es comparable con `multi_informe.md`; la comparación entre variantes sí, porque comparten datos.
- Placebo: los mismos pesos desfasados días completos; mide si el timing de la variante tiene señal.
