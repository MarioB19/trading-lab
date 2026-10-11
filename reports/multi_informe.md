# Portafolio multi-activo: resultados de la investigación

Estrategia: tendencia + momentum ajustado por riesgo + paridad de riesgo + volatilidad objetivo + filtro de régimen (cripto) + freno por caída. Candidatas declaradas antes de ver resultados.

## Criptomonedas

Datos 2014-01-01 a 2026-10-10; fuera de muestra desde 2021; costo 0.45% por lado; candidata: top5 · vol 40% · con filtro BTC · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 40% · con filtro BTC · freno | 30.8% | 1.06 | −42% | 35% |
| Optimizador (elige la mejor cada año) | 44.0% | 1.06 | −50% | 38% |
| Comprar y aguantar BTC | 19.9% | 0.60 | −77% | 100% |
| Pesos iguales, rebalanceo mensual | 17.9% | 0.58 | −78% | 84% |
| Regla de tendencia solo BTC | 16.5% | 0.60 | −56% | 53% |

- Placebo (pesos desfasados al azar): p = 0.000.
- Mejor variante de 43 en todo el periodo: top3 · vol sin · con filtro BTC · freno (DSR vs 0: 0.990; DSR vs referencia: 0.265).
- Bootstrap de la candidata: vs Comprar y aguantar BTC: P(más rendimiento) 69%, P(menor caída) 98%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 75%, P(menor caída) 99%; vs Regla de tendencia solo BTC: P(más rendimiento) 85%, P(menor caída) 87%
- Costos: 0.30% → 36.4%, 0.45% → 30.8%, 0.60% → 25.3%, 1.00% → 13.1%
- Kill switch: a 35%: se habría activado el 2023-06-09; a 45%: no se habría activado.
- 12 meses con $1,000: peor 5% $738, mediana $1,241, P(pérdida) 26%, P(caída >30%) 19% (referencia: P(pérdida) 40%, P(caída >30%) 82%).
- Solo con las 16 criptos operables hoy en Bitso: 31.7% anual, caída máx. −39% (estas sobrevivieron, así que es optimista).
- **Qué usa el bot en este bloque:** CANDIDATA: top5 · vol 40% · con filtro BTC · freno.

| Año | Candidata | Referencia |
|---|---:|---:|
| 2019 | 39% | 94% |
| 2020 | 67% | 305% |
| 2021 | 122% | 60% |
| 2022 | −8% | −64% |
| 2023 | 34% | 155% |
| 2024 | 45% | 121% |
| 2025 | −11% | −6% |
| 2026 | 33% | −5% |

## Acciones y ETFs

Datos 1998-01-02 a 2026-10-09; fuera de muestra desde 2010; costo 0.05% por lado; candidata: top5 · vol 10% · sin filtro · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 10% · sin filtro · freno | 4.6% | 0.53 | −17% | 86% |
| Optimizador (elige la mejor cada año) | 4.3% | 0.48 | −17% | 88% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% | 100% |
| Pesos iguales, rebalanceo mensual | 10.4% | 0.78 | −29% | 94% |
| 60/40 (SPY/IEF) | 9.9% | 1.00 | −22% | 100% |

- Placebo (pesos desfasados al azar): p = 0.315.
- Mejor variante de 18 en todo el periodo: top5 · vol 10% · sin filtro · sin freno (DSR vs 0: 0.844; DSR vs referencia: 0.006).
- Bootstrap de la candidata: vs Comprar y aguantar SPY: P(más rendimiento) 0%, P(menor caída) 88%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 1%, P(menor caída) 78%; vs 60/40 (SPY/IEF): P(más rendimiento) 0%, P(menor caída) 40%
- Costos: 0.02% → 6.2%, 0.05% → 4.6%, 0.20% → −3.2%, 0.50% → −16.2%
- Kill switch: a 35%: no se habría activado; a 25%: no se habría activado.
- 12 meses con $1,000: peor 5% $909, mediana $1,049, P(pérdida) 29%, P(caída >30%) 0% (referencia: P(pérdida) 16%, P(caída >30%) 4%).
- **Qué usa el bot en este bloque:** 60/40 (SPY/IEF).

| Año | Candidata | Referencia |
|---|---:|---:|
| 2005 | 5% | 5% |
| 2006 | 10% | 16% |
| 2007 | −2% | 5% |
| 2008 | −6% | −37% |
| 2009 | 10% | 26% |
| 2010 | 4% | 15% |
| 2011 | 6% | 2% |
| 2012 | 1% | 16% |
| 2013 | 23% | 32% |
| 2014 | −0% | 13% |
| 2015 | −7% | 1% |
| 2016 | 1% | 12% |
| 2017 | 14% | 22% |
| 2018 | −8% | −5% |
| 2019 | 7% | 31% |
| 2020 | 14% | 18% |
| 2021 | 13% | 29% |
| 2022 | −5% | −18% |
| 2023 | 4% | 26% |
| 2024 | 4% | 25% |
| 2025 | 5% | 18% |
| 2026 | 5% | 15% |

## Combinado de ejemplo

50% cripto (candidata) / 50% ETFs (60/40 pasivo) sin rebalancear entre cuentas: 22.0% anual, caída máx. −32%, P(pérdida en 12 meses) 25%.

## Limitaciones

- El universo cripto incluye monedas que se desplomaron (LUNA, FTT, EOS...) y se elige por capitalización de cada día, pero la lista inicial la hice en 2026: queda algo de sesgo de supervivencia.
- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.
- Cripto: precios de CoinMetrics y Yahoo en USD. ETFs: cierres ajustados de Yahoo. Sin impuestos.
