---
experiment_id: catalogo2-etf
fecha: 2026-10-31
veredicto: ninguna de las 53 estrategias supera al 60/40 tras la corrección; se conserva el control. Hallazgo de riesgo: el 60/40 habría tocado el kill switch de −25% en 2008
---

# Catálogo 2 — 53 estrategias para el bloque de ETFs contra el 60/40 (resultado)

Preregistro: `reports/catalogo2_etf_preregistro.md` (commit `708eebf`, enmienda `38325f9` antes del intento válido).
Script: `scripts/research/catalogo2_etf.py`; definiciones: `src/lab/catalog_etf.py`. Datos: `data/etf_prices.csv`
(Yahoo, ajustados, hasta 2026-09-25). Evaluación 2008-01-01 → 2026-09-25, costo 0.05% por lado (estrés 0.075%),
banda 5 pp, 252 días/año, **sin kill switch en la simulación** (ver intento 1).

## Intento 1, inválido por diseño (registrado)

El primer barrido aplicó el kill switch de −25% desde 2008 y **apagó al propio 60/40 el 28-oct-2008** (caída −25.2%)
y a la mayoría de las mezclas: carteras en efectivo 18 años y un "control" con −1.5% anual. Medía quién sobrevivió a 2008
con un dispositivo pensado para el bloque vivo, no las estrategias. Quedó en `catalogo2_etf_intento1_invalido.json` y
sus 53 filas siguen en `intentos.csv` (cuentan para el Sharpe deflactado, castigo conservador por haber mirado).

## Resultado en una línea

**Ninguna gana.** 53 pasaron la compuerta de costos, **ninguna avanzó**: p global 0.72. 23 de 53 tienen mejor Sharpe que
el 60/40, pero casi todas con **menos** rendimiento (solo 9 rinden más, y esas con más caída); ninguna supera la
corrección por 53 comparaciones. El 60/40 sigue.

| Control | Rend. anual 2008–2026 | Sharpe | Caída máx. | Rotación/año | Habría tocado −25% |
|---|---:|---:|---:|---:|---|
| 60/40 SPY/IEF, banda 5 pp | +8.5% | 0.77 | **−31.2%** (mar-2009) | 0.2 | **sí (oct-2008)** |
| Referencia SPY | +11.4% | 0.64 | −51.9% | — | sí |
| Referencia IEF | +2.6% | 0.41 | −23.9% | — | no |

## Lo mejor de cada familia

| Familia | Mejor variante | Rend. anual | Sharpe | Caída máx. | Rot./año | p sin corregir | p corregida |
|---|---|---:|---:|---:|---:|---:|---:|
| E3 tendencia sobre el 60/40 | `trend-spy300-to-cash` | +7.1% | **0.97** | −16.3% | 3.5 | 0.78 | 1.00 |
| E2 paridad de riesgo | `rp-spy-tlt-gld-w63` | +8.5% | 0.93 | −22.8% | 0.7 | 0.47 | 1.00 |
| E7 volatilidad objetivo | `voltarget-10` | +7.5% | 0.88 | −20.3% | 0.5 | 0.87 | 1.00 |
| E1 mezclas fijas | `mix-40-60` | +6.7% | 0.87 | −20.1% | 0.2 | 0.96 | 1.00 |
| E10 freno por caída | `control-ddbrake-5-20` | +8.1% | 0.87 | −23.3% | 0.5 | 0.74 | 1.00 |
| E8 rebalanceo | `control-band-10` | **+9.0%** | 0.81 | −29.6% | 0.2 | **0.01** | 0.99 |
| E5 momentum de sectores | `sector-12m-top3-ief40` | +8.0% | 0.77 | −27.2% | 3.1 | 0.64 | 1.00 |
| E4 momentum dual (GEM) | `gem-3m` | +9.9% | 0.76 | −35.1% | 7.6 | 0.27 | 0.89 |
| E9 duración del bono | `bondswitch-tlt200` | +7.6% | 0.71 | −30.9% | 9.1 | 0.88 | 1.00 |
| E6 momentum entre clases | `class-top4-equal` | +8.4% | 0.68 | −22.7% | 3.0 | 0.54 | 1.00 |

Las de más rendimiento bruto (sectores top 5 +10.9%, GEM 3 meses +9.9%, 70/30 +9.3%) pagan con caídas de 35–50%.
Tabla completa de las 53 en `catalogo2_etf_resultado.json`.

## Lectura

- **El 60/40 es difícil de batir en rendimiento con estos ETFs.** Todo lo que "mejora el Sharpe" lo hace bajando riesgo
  y rendimiento a la vez (paridad de riesgo, volatilidad objetivo, tendencia a efectivo). Nada añade rendimiento sin
  añadir caída. Momentum de sectores, GEM y momentum entre clases rinden parecido o menos con caídas mucho peores:
  **las ideas de timing en ETFs no pagan ni con costos de 0.05%** en 2008–2026.
- **Hallazgo de riesgo que sí importa (no es una estrategia):** el 60/40 vigente cayó −31% en 2008–2009 y habría tocado el
  kill switch de −25% del bloque, que lo deja en efectivo hasta que un humano lo rearme. 27 de las 53 variantes también.
  Hoy el bloque va en −0.1% y el kill está lejos, pero con otro 2008 **el bloque de ETFs se apaga solo**. Es una decisión
  para Brandon: subir el kill del bloque ETF (por ejemplo a −35%, donde ninguna de las carteras razonables lo toca),
  aceptar que se apague, o cambiar a una variante de menor caída (`control-ddbrake-5-20`: −23% con 8.1% anual;
  `voltarget-10`: −20% con 7.5%; `rp-spy-tlt-gld`: −23% con 8.5%). Son cambios de riesgo, no de señal; cualquiera
  de ellos iría a un preregistro propio con la barra de costo.
- **La única pista con señal estadística sin corregir:** `control-band-10` (rebalancear solo cuando un ETF se desvía 10
  puntos en vez de 5): +9.0% contra +8.5%, caída −29.6% contra −31.2%, gana 10 de 17 años, p sin corregir 0.01. No pasó
  el barrido (p corregida 0.99: la corrección familiar castiga una mejora pequeña y consistente igual que una grande y
  ruidosa). Es un cambio de costo puro y merece su sprint propio con la barra de costo (H11). Ojo: con US$500 y órdenes
  de US$1 el ahorro real es centavos; la ganancia viene de dejar correr al activo que sube, no de comisiones.
- **Para la misión** (ventaja después de costos o dejar de perder en costos): el bloque de ETFs ya está donde la evidencia
  dice. El dinero del proyecto se pierde en cripto, y ahí el Catálogo 100 ya dijo que no hay señal que pague las
  comisiones. Lo que queda es abaratar la ejecución (H4 en curso, H1b, H6) y la observación hacia adelante (carril 1).

## Limitaciones

- 2008–2026: una sola gran crisis y un solo año de subida de tasas (2022); las reglas que salen a bonos se ven mejor de lo
  que se verían en otro régimen. Precios ajustados de Yahoo, costo constante, sin impuestos ni rebalanceo fraccional real.
- El 60/40 se eligió sobre este mismo histórico el 25-sep: retrospectivo. 261 intentos acumulados en `intentos.csv`.
