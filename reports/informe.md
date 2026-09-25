# Informe del laboratorio de trading BTC
Datos 2012-01-01 a 2026-09-24 · costo por operación 0.20% por lado · fuera de muestra desde 2018.

## Veredicto

- De 2018 a hoy, fuera de muestra, la regla candidata rindió 33% anual contra 23% de solo tener BTC, con una caída máxima de −51% contra −81%.
- Su timing supera al azar (p = 0.013): es una ventaja medible en el pasado, no un accidente.
- Lo que más aporta es reducir el daño en los desplomes: la probabilidad de que tenga menos caída que comprar y aguantar es 99%, pero la de que gane MÁS dinero es solo 71%.
- El optimizador que cada año cambia a la estrategia que mejor venía funcionando rindió 22%: buscar la regla más lista empeoró el resultado frente a dejar una regla fija.
- En cualquier periodo de 12 meses hay alrededor de 28% de probabilidad de terminar con pérdida.

## Resultados fuera de muestra (2018–hoy)

| Estrategia | Rend. anual | Sharpe | Caída máx. | Tiempo dentro | Operaciones/año |
|---|---:|---:|---:|---:|---:|
| Comprar y aguantar | 22.9% | 0.65 | −81% | 100% | 0 |
| Regla candidata: tendencia promediada 20/50/100/200 | 33.2% | 0.92 | −51% | 52% | 68 |
| Optimizador: elige la mejor cada año | 22.0% | 0.71 | −71% | 42% | 53 |
| Tendencia promediada + control de volatilidad | 29.6% | 1.07 | −38% | 39% | 68 |
| Machine learning (logística / boosting) | 36.4% | 0.93 | −71% | 45% | 28 |
| Tendencia promediada | 33.3% | 0.92 | −51% | 52% | 68 |
| Cruce de promedios | 28.7% | 0.80 | −68% | 51% | 9 |
| Ruptura de canal (Donchian) | 25.9% | 0.79 | −62% | 40% | 15 |
| Precio vs. promedio móvil | 21.2% | 0.66 | −68% | 52% | 27 |
| Momentum (rendimiento pasado > 0) | 15.4% | 0.54 | −75% | 54% | 23 |
| Reversión a la media (RSI) | 9.1% | 0.42 | −60% | 42% | 3 |

## ¿Ventaja real o suerte?

- **Pruebas múltiples:** se probaron 28 variantes. La mejor en todo el periodo fue `ml_model(model=logistic)` (Sharpe 1.45). Sharpe deflactado contra cero: 0.995; contra comprar y aguantar: 0.044. Es decir: le gana a no invertir, pero no hay evidencia de que gane más dinero que solo tener BTC.
- **Placebo (posiciones desfasadas al azar):** candidata Sharpe 0.92 vs mediana al azar 0.38 (p = 0.013); optimizador p = 0.071.
- **Bootstrap contra comprar y aguantar (candidata):** P(mejor Sharpe) 89%, P(más rendimiento) 71%, P(menor caída) 99%.
- **BTC sin tendencia anual** (cada año termina donde empezó): candidata 9.7% anual vs 0.0% de comprar y aguantar.
- **ETH, sin re-optimizar:** candidata 45.6% anual, caída máx. −56%; comprar y aguantar 15.8%, caída máx. −94%.
- **Desde 2022 (mercado más maduro):** candidata 18.8% anual, caída −33%; comprar y aguantar 13.4%, caída −67%.
- **Machine learning:** AUC fuera de muestra al predecir si BTC sube en 5 días: logística 0.499, boosting 0.511 (0.5 = moneda al aire).

## Sensibilidad a comisiones (rendimiento anual fuera de muestra)

| Costo por lado | Candidata | Optimizador | Comprar y aguantar |
|---|---:|---:|---:|
| 0.0% | 38.6% | 27.4% | 22.9% |
| 0.1% | 35.9% | 24.6% | 22.9% |
| 0.2% | 33.2% | 22.0% | 22.9% |
| 0.5% | 25.5% | 14.2% | 22.8% |
| 1.0% | 13.6% | 2.4% | 22.8% |

## Año por año

| Año | Comprar y aguantar | Candidata | Optimizador |
|---|---:|---:|---:|
| 2015 | +34% | +41% | – |
| 2016 | +126% | +86% | – |
| 2017 | +1337% | +954% | – |
| 2018 | −74% | −38% | −56% |
| 2019 | +94% | +92% | +113% |
| 2020 | +305% | +209% | +136% |
| 2021 | +60% | +47% | +19% |
| 2022 | −64% | −32% | −24% |
| 2023 | +155% | +84% | +70% |
| 2024 | +121% | +67% | +71% |
| 2025 | −6% | −9% | −4% |
| 2026 | −4% | +18% | +1% |

## Riesgo a 12 meses con $10,000 (Monte Carlo por bloques)

| | Peor 5% | Mediana | Mejor 5% | P(pérdida) | P(caída >30% en el camino) | P(caída >50%) |
|---|---:|---:|---:|---:|---:|---:|
| Candidata | $6,652 | $13,014 | $29,957 | 28% | 39% | 3% |
| Comprar y aguantar | $4,042 | $12,484 | $35,762 | 38% | 87% | 42% |

## Tamaño de posición

Kelly estimado de la candidata: 2.35 (intervalo ±2σ: 0.63 a 4.07). El rendimiento esperado anual va de 10% a 63% con el mismo intervalo. Esa incertidumbre es la razón para NO usar apalancamiento y operar solo capital que puedas perder.

## Señal de hoy

Cierre 2026-09-24: $84,380 USD. Exposición objetivo de la candidata: 100%.

## Qué supone este análisis

- Precios diarios de cierre (CoinMetrics + Kraken). Se decide al cierre y se ejecuta al siguiente precio.
- Sin cortos ni apalancamiento. El efectivo no genera intereses (en la vida real podría estar en CETES).
- El pasado de BTC incluye una subida de cientos de veces que no se va a repetir; los números absolutos están inflados por eso. La comparación relevante es contra comprar y aguantar.
- Impuestos, tipo de cambio MXN/USD y fallas del exchange no están modelados.
