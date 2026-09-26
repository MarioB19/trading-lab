# Bloque multi-mercado: prueba del 25-sep-2026

**Veredicto: no aprobado.** La regla declarada antes de la prueba (hasta 8 de 19 ETFs de materias primas,
divisas, bonos y bolsas; pesos por riesgo; volatilidad objetivo 10%; efectivo en BIL) perdió 1.4% anual
fuera de muestra (2012–2026) y falló los cinco criterios. El 60/40 SPY/IEF ganó 9.8% anual.

| Criterio | Resultado |
|---|---|
| Placebo p < 0.05 | Falla (p = 0.80) |
| Sharpe mayor que el 60/40 con P ≥ 80% | Falla (0%) |
| Caída máxima no peor que el 60/40 | Falla (−29% vs −22%) |
| Con 0.3% de costos, Sharpe mayor que el 60/40 | Falla (−1.59 vs 1.00) |
| Con cripto 30/70 mejora Sharpe sin más caída | Falla (18.4% vs 21.2% anual) |

Diagnóstico: sin costos rinde 3.7% anual (sigue debajo del 60/40); la lista de ETFs cambia 133 días al año
(rotación de 51 veces el capital por año); la mejor de 36 variantes dio 0.5% anual y no es significativa
(Sharpe deflactado 0.35).

Decisión: el bloque queda apagado (`enabled: false`). No se ajustan parámetros para que pase.
Reproducir: `python -m lab.research_multi --multi-market --refresh`.
