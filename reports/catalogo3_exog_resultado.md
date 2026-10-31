---
experiment_id: catalogo3-exog
fecha: 2026-10-31
veredicto: ninguna de las 33 capas exógenas mejora al control; las de sentimiento y MVRV lo empeoran claramente
---

# Catálogo 3 — Señales exógenas sobre el control de cripto (resultado)

Preregistro: `reports/catalogo3_exog_preregistro.md` (commit `8c2bf39`, antes de correr). Script:
`scripts/research/catalogo3_exog.py`; definiciones `src/lab/catalog_exog.py`; datos `data/exog_*.csv` (alternative.me,
CoinMetrics community, DefiLlama). Mismo panel, control, costos y ventana que el Catálogo 100 (2019-01-01 → 2026-10-30).

## Resultado en una línea

**Ninguna gana.** 33 pasaron la compuerta de costos, ninguna avanzó: p global 0.98. Solo 6 de 33 mejoran el Sharpe del
control y solo 4 el rendimiento, todas por poco; la mayoría **destruye** rendimiento. 294 intentos acumulados.

| Control | Rend. anual | Sharpe | Caída máx. | Exposición media |
|---|---:|---:|---:|---:|
| tendencia + momentum (regla vigente) | +38.3% | 1.19 | −34.3% | 0.35 |

## Lo mejor de cada familia

| Familia | Mejor variante | Rend. anual | Sharpe | Caída máx. | p corregida |
|---|---|---:|---:|---:|---:|
| X5 oferta de stablecoins | `stab-shrink1pct-cut` (fuera cuando las stablecoins se contraen >1% en 30 días) | **+40.3%** | **1.30** | −34.3% | 0.98 |
| X2 MVRV de BTC | `mvrv-cut3.5` | +39.2% | 1.22 | −34.3% | 0.99 |
| X1 miedo y codicia | `fng-follow50` (seguir al sentimiento, no contrariarlo) | +35.1% | 1.19 | −32.8% | 1.00 |
| X3 BTC en exchanges | `exsup-z2-cut` | +37.7% | 1.18 | −34.3% | 1.00 |
| X4 direcciones activas | `adr-mom90-half` | +32.8% | 1.13 | −32.1% | 1.00 |
| X6 hash ribbon | `hash-ribbon-half` | +32.5% | 1.09 | −36.0% | 1.00 |
| X7 compuesto (4 señales) | `comp-half-05` | +26.0% | 1.00 | −35.2% | 1.00 |
| X8 miedo/codicia como regla sobre BTC | `fngbtc-20-80` | +4.5% | 0.34 | −45.1% | 1.00 |

Peores: `fng-cut75` (salir en codicia ≥ 75) +9.7% anual; `fngbtc-25-75` +1.0%; `mvrv-z2` +12.5%; `mvrv-cut2.5` +14.5%.
Tabla completa de las 33 en `catalogo3_exog_resultado.json`.

## Lectura

- **El "sabiduría contraria" no funciona sobre una estrategia de tendencia.** Salir cuando hay codicia extrema o cuando
  el MVRV es alto corta justo los tramos donde la tendencia gana más: el índice de miedo/codicia marcó ≥ 75 durante gran
  parte de 2021 y de finales de 2024. La única capa de sentimiento que no destruye valor es la que lo **sigue**
  (`fng-follow50`), y esa no aporta nada sobre el control (ya es tendencia).
- **Lo on-chain tampoco:** direcciones activas, BTC en exchanges y hash ribbon quitan entre 1 y 6 puntos anuales. La
  "capitulación minera" (hash ribbon) está en el precio antes de que la serie reaccione.
- **La única pista** es la oferta de stablecoins: salir cuando se contrae más de 1% en 30 días da +2 puntos anuales y
  Sharpe 1.30 contra 1.19, ganando en 2023 y 2026 y perdiendo en 2022 (−14% contra −8%). Con p corregida 0.98 y datos
  fiables solo desde mediados de 2020, es exactamente lo que el azar produce entre 33 intentos. No se promueve ni se
  reabre sin un dato nuevo (por ejemplo, otra fuente de oferta de stablecoins con historia más larga).
- **Para Brandon:** tres catálogos, 189 estrategias y 294 intentos sobre datos de precios, de ETFs y ahora exógenos, y la
  conclusión no se mueve: con estas comisiones no hay señal que le gane al control de forma distinguible del azar. Eso
  **no** significa que el bot no pueda ganar dinero: significa que su resultado dependerá de que la ventaja histórica de
  tendencia + momentum (+38% anual, con la mitad de la caída de BTC) sea real, y eso solo lo dirá el tiempo hacia adelante.
  Mientras, lo que sí mueve el neto son los costos (ejecución maker H4, liquidez H6, recompras H1b).

## Limitaciones

- Rezagos conservadores (1 día on-chain y stablecoins; 0 para miedo/codicia). Umbrales canónicos sin ajustar.
- Las capas solo reducen exposición; una señal que sugiriera **aumentarla** necesitaría apalancamiento, prohibido.
- Serie de stablecoins incompleta antes de 2020-07 (esas variantes son el control hasta esa fecha).
