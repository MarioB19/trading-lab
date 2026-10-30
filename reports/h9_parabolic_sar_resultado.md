---
experiment_id: h9-parabolic-sar
fecha: 2026-10-30
veredicto: descartada; ninguna variante aprobada, se conserva el control
---

# H9 — Parabolic SAR como capa de salida y como señal en cripto (resultado)

Preregistro: `reports/h9_parabolic_sar_preregistro.md` (commits `5cb5f2b` y `9788ca6`, antes de correr).
Script: `scripts/research/h9_parabolic_sar.py`. Datos: velas diarias de OKX (USDT) para las 16 monedas de Bitso,
2018-01-01 → 2026-10-30; 3 velas sospechosas (máximo > 3× o mínimo < ⅓ del cierre) se rellenaron con el cierre.
Evaluación 2019-01-01 → 2026-10-30, costo 0.42% por lado (estrés 0.63%), banda 2 pp, kill switch −45%.

## Resultado

| Variante | Rend. anual | Sharpe | Caída máx. | Rotación/año | Costo/año | Rend. anual con estrés |
|---|---:|---:|---:|---:|---:|---:|
| Control (tendencia + momentum) | +38.3% | 1.19 | −34.3% | 30.7× | 12.9% | +29.8% |
| V1: SAR como filtro de salida (0.02/0.02/0.20) | +37.1% | 1.14 | −43.6% | 41.0× | 17.2% | +23.8% |
| V2: SAR filtro lento (0.01/0.01/0.10) | +39.1% | 1.20 | −44.3% | 35.2× | 14.8% | +27.0% |
| V3: SAR en lugar de la tendencia | +16.9% | 0.72 | −43.6% | 36.0× | 15.1% | +8.4% |

Comprobación del panel: el mismo control sobre el panel CoinMetrics/Yahoo de los sprints 01–02 (hasta 2026-09-26)
da +40.5% anual, Sharpe 1.26, caída −38.5% y 29.4 rotaciones/año. El control se comporta igual en ambos paneles.

### Por año

| Variante | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (a oct) |
|---|---:|---:|---:|---:|---:|---:|
| Control | +155% | −8% | +56% | +58% | −25% | +17% |
| V1: SAR filtro | +168% | −6% | +50% | +17% | −29% | +16% |
| V2: SAR filtro lento | +161% | −2% | +29% | +39% | −31% | +27% |
| V3: SAR tendencia | +30% | −28% | +43% | +36% | −23% | −9% |

## Criterios (fijados antes de correr)

| Variante | 1. Años fuera de muestra (≥4/6) | 2. Placebo (p<0.05) | 3. Bootstrap Sharpe (≥0.967) | 4. Sharpe deflactado (≥0.95, 52 intentos) | 5. Estrés vs control | Aprobada |
|---|---|---|---|---|---|---|
| V1: SAR filtro | ❌ 2/6 | ✅ 0.005 | ❌ 0.353 | ✅ 0.959 | ❌ −6.0 pts | ❌ |
| V2: SAR filtro lento | ❌ 3/6 | ✅ 0.015 | ❌ 0.505 | ✅ 0.971 | ❌ −2.8 pts | ❌ |
| V3: SAR tendencia | ❌ 1/6 | ❌ 0.209 | ❌ 0.017 | ❌ 0.678 | ❌ −21.4 pts | ❌ |

Informativo: la caída máxima **empeora** 9–10 puntos en las tres variantes respecto al control. El SAR estándar
gira ≈26 veces por activo y año; el lento, ≈16.

## Lectura

- **Veredicto: H9 descartada; el control se conserva.** Ninguna variante cumple los cinco criterios. V1 y V2 pasan
  el placebo y el Sharpe deflactado (su timing no es ruido puro), pero no le ganan al control: la mejora de Sharpe
  es nula (bootstrap 0.35 y 0.50 = cara o cruz), pierden más años de los que ganan y con costos de estrés quedan
  3–6 puntos anuales por debajo.
- **La hipótesis salió al revés.** El SAR debía *reducir* las caídas saliendo antes; en cambio la caída máxima pasó
  de −34% a −44%. La peor racha del control va de dic-2024 a abr-2026; la de V1 arranca igual y es más profunda
  porque el SAR sale en cada rebote fallido y recompra tarde: en 2024 V1 ganó +17% contra +58% del control por
  quedarse fuera en los meses de subida (marzo +7% contra +14%, noviembre +73% contra +79%, enero −17% contra −11%).
  Los ETFs del bloque de acciones no participan en esto; el bloque cripto ya tiene un freno por caída que hace
  el trabajo de forma más barata.
- **El costo de rotar, otra vez.** V1 añade ~10 operaciones al año (41 contra 31) y paga 17% anual en costos contra
  13% del control. Cada giro del SAR es una ida y vuelta de ≈0.84%. Con la comisión de Bitso, un stop más rápido
  se paga solo; no gana.
- **Como señal única (V3) es claramente peor:** +17% anual contra +38%, falla los cinco criterios y pierde en
  5 de 6 años. Coincide con la evidencia externa recogida antes de correr (el SAR solo le gana a comprar y mantener
  en 19–30% de las acciones del Dow y necesita un filtro de tendencia encima).
- **Implicación para el bot:** la pérdida de −US$29.5 por «estrategia» desde el 24-sep no se arregla con una
  salida más rápida; las salidas rápidas cuestan más de lo que ahorran con estas comisiones. Las palancas con
  evidencia siguen siendo abaratar cada operación (maker H4, universo más líquido H6, no recomprar en 48 h H1b)
  y evitar entradas caras como la de TRX del 30-oct (spread 2.4%), que es un filtro de liquidez, no de timing.

## Limitaciones

- Histórico ya inspeccionado por 50 intentos previos (retrospectivo, no holdout). Velas de OKX en USDT, no el
  libro de Bitso; costo constante por lado.
- Parámetros canónicos de Wilder sin ajuste; otros valores podrían dar otro resultado, pero ajustarlos a estos
  datos sería optimizar hasta que «se vea bien» (prohibido en `AGENTS.md`). No se vuelve a probar sin un dato nuevo
  (por ejemplo, comisiones por debajo de 0.15% por lado, donde la evidencia externa sitúa el umbral del SAR).
- La ventana incluye el mercado alcista de 2020–2021; el rendimiento pasado no se repite necesariamente.
