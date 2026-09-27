# Portafolio multi-activo: resultados de la investigación

Estrategia: tendencia + momentum ajustado por riesgo + paridad de riesgo + volatilidad objetivo + filtro de régimen (cripto) + freno por caída. Candidatas declaradas antes de ver resultados.

## Criptomonedas

Datos 2014-01-01 a 2026-09-26; fuera de muestra desde 2021; costo 0.45% por lado; candidata: top5 · vol 40% · con filtro BTC · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 40% · con filtro BTC · freno | 33.2% | 1.12 | −42% | 34% |
| Optimizador (elige la mejor cada año) | 49.9% | 1.16 | −50% | 38% |
| Comprar y aguantar BTC | 20.4% | 0.61 | −77% | 100% |
| Pesos iguales, rebalanceo mensual | 20.0% | 0.61 | −78% | 84% |
| Regla de tendencia solo BTC | 17.0% | 0.61 | −56% | 53% |

- Placebo (pesos desfasados al azar): p = 0.000.
- Mejor variante de 43 en todo el periodo: top3 · vol sin · con filtro BTC · freno (DSR vs 0: 0.993; DSR vs referencia: 0.296).
- Bootstrap de la candidata: vs Comprar y aguantar BTC: P(más rendimiento) 66%, P(menor caída) 98%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 73%, P(menor caída) 100%; vs Regla de tendencia solo BTC: P(más rendimiento) 84%, P(menor caída) 87%
- Costos: 0.30% → 38.9%, 0.45% → 33.2%, 0.60% → 27.7%, 1.00% → 15.4%
- Kill switch: a 35%: se habría activado el 2023-06-09; a 45%: no se habría activado.
- 12 meses con $1,000: peor 5% $731, mediana $1,224, P(pérdida) 28%, P(caída >30%) 20% (referencia: P(pérdida) 40%, P(caída >30%) 81%).
- Solo con las 16 criptos operables hoy en Bitso: 34.1% anual, caída máx. −39% (estas sobrevivieron, así que es optimista).
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
| 2026 | 46% | −4% |

## Acciones y ETFs

Datos 1998-01-02 a 2026-09-25; fuera de muestra desde 2010; costo 0.05% por lado; candidata: top5 · vol 10% · sin filtro · freno.

| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| CANDIDATA: top5 · vol 10% · sin filtro · freno | 4.6% | 0.53 | −17% | 86% |
| Optimizador (elige la mejor cada año) | 4.3% | 0.47 | −17% | 88% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% | 100% |
| Pesos iguales, rebalanceo mensual | 10.4% | 0.78 | −29% | 94% |
| 60/40 (SPY/IEF) | 9.9% | 1.00 | −22% | 100% |

- Placebo (pesos desfasados al azar): p = 0.350.
- Mejor variante de 18 en todo el periodo: top5 · vol 10% · sin filtro · sin freno (DSR vs 0: 0.839; DSR vs referencia: 0.006).
- Bootstrap de la candidata: vs Comprar y aguantar SPY: P(más rendimiento) 0%, P(menor caída) 88%; vs Pesos iguales, rebalanceo mensual: P(más rendimiento) 2%, P(menor caída) 78%; vs 60/40 (SPY/IEF): P(más rendimiento) 1%, P(menor caída) 40%
- Costos: 0.02% → 6.2%, 0.05% → 4.6%, 0.20% → −3.3%, 0.50% → −16.2%
- Kill switch: a 35%: no se habría activado; a 25%: no se habría activado.
- 12 meses con $1,000: peor 5% $909, mediana $1,049, P(pérdida) 30%, P(caída >30%) 0% (referencia: P(pérdida) 16%, P(caída >30%) 4%).
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
| 2026 | 4% | 14% |

## Combinado de ejemplo

50% cripto (candidata) / 50% ETFs (60/40 pasivo) sin rebalancear entre cuentas: 23.7% anual, caída máx. −32%, P(pérdida en 12 meses) 26%.

## Limitaciones

- El universo cripto incluye monedas que se desplomaron (LUNA, FTT, EOS...) y se elige por capitalización de cada día, pero la lista inicial la hice en 2026: queda algo de sesgo de supervivencia.
- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.
- Cripto: precios de CoinMetrics y Yahoo en USD. ETFs: cierres ajustados de Yahoo. Sin impuestos.
