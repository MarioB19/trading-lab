# Portafolio multi-activo: resultados de la investigación

Estrategia: tendencia + momentum ajustado por riesgo + paridad de riesgo + volatilidad objetivo + filtro de régimen (cripto) + freno por caída. Candidatas declaradas antes de ver resultados.

## Criptomonedas

Datos 2014-01-01 a 2026-09-23; fuera de muestra desde 2021; costo 0.45% por lado; candidata: top5 · vol 40% · con filtro BTC · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 40% · con filtro BTC · freno | 32.3% | 1.10 | −42% | 34% |
| Optimizador (elige la mejor cada año) | 47.4% | 1.13 | −50% | 38% |
| Comprar y aguantar BTC | 20.5% | 0.61 | −77% | 100% |
| Pesos iguales, rebalanceo mensual | 19.2% | 0.60 | −78% | 84% |
| Regla de tendencia solo BTC | 17.0% | 0.62 | −56% | 53% |

- Placebo (pesos desfasados al azar): p = 0.000.
- Mejor variante de 39 en todo el periodo: top3 · vol sin · con filtro BTC · freno (DSR vs 0: 0.993; DSR vs referencia: 0.288).
- Bootstrap de la candidata: vs Comprar y aguantar BTC: P(más rendimiento) 66%, P(menor caída) 97%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 73%, P(menor caída) 100%; vs Regla de tendencia solo BTC: P(más rendimiento) 83%, P(menor caída) 87%
- Costos: 0.30% → 37.9%, 0.45% → 32.3%, 0.60% → 26.8%, 1.00% → 14.7%
- Kill switch: a 35%: se habría activado el 2023-06-09; a 45%: no se habría activado.
- 12 meses con $1,000: peor 5% $719, mediana $1,227, P(pérdida) 28%, P(caída >30%) 20% (referencia: P(pérdida) 41%, P(caída >30%) 81%).
- Solo con las 16 criptos operables hoy en Bitso: 33.1% anual, caída máx. −39% (estas sobrevivieron, así que es optimista).
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
| 2026 | 40% | −4% |

## Acciones y ETFs

Datos 1998-01-02 a 2026-09-24; fuera de muestra desde 2010; costo 0.05% por lado; candidata: top5 · vol 10% · sin filtro · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 10% · sin filtro · freno | 4.5% | 0.53 | −17% | 86% |
| Optimizador (elige la mejor cada año) | 4.3% | 0.47 | −17% | 88% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% | 100% |
| Pesos iguales, rebalanceo mensual | 10.3% | 0.78 | −29% | 94% |
| 60/40 (SPY/IEF) | 9.9% | 1.00 | −22% | 100% |

- Placebo (pesos desfasados al azar): p = 0.340.
- Mejor variante de 18 en todo el periodo: top5 · vol 10% · sin filtro · sin freno (DSR vs 0: 0.843; DSR vs referencia: 0.006).
- Bootstrap de la candidata: vs Comprar y aguantar SPY: P(más rendimiento) 0%, P(menor caída) 89%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 2%, P(menor caída) 78%; vs 60/40 (SPY/IEF): P(más rendimiento) 1%, P(menor caída) 40%
- Costos: 0.02% → 6.2%, 0.05% → 4.5%, 0.20% → −3.3%, 0.50% → −16.3%
- Kill switch: a 35%: no se habría activado; a 25%: no se habría activado.
- 12 meses con $1,000: peor 5% $908, mediana $1,046, P(pérdida) 30%, P(caída >30%) 0% (referencia: P(pérdida) 16%, P(caída >30%) 4%).
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
| 2026 | 4% | 13% |

## Combinado de ejemplo

30% cripto (candidata) / 70% ETFs (60/40 pasivo) sin rebalancear entre cuentas: 18.2% anual, caída máx. −27%, P(pérdida en 12 meses) 24%.

## Limitaciones

- El universo cripto incluye monedas que se desplomaron (LUNA, FTT, EOS...) y se elige por capitalización de cada día, pero la lista inicial la hice en 2026: queda algo de sesgo de supervivencia.
- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.
- Cripto: precios de CoinMetrics y Yahoo en USD. ETFs: cierres ajustados de Yahoo. Sin impuestos.
