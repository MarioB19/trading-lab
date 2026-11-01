---
experiment_id: semaforo-s02-medicion
fecha: 2026-11-01
veredicto: el control no es «ganadora» en ningún escenario; con un exchange a 0.10% cumple M1–M4 y falla M5 por poco
---

# Semáforo de «ganadora»: el control en M1–M5 y M7 (resultado)

Preregistro: `reports/semaforo_s02_medicion_preregistro.md` (commit `a52fc1e`, antes de correr). Script:
`scripts/research/semaforo_s02_medicion.py`; cifras en `semaforo_s02_medicion_resultado.json`. Control vigente, US$500
cripto + US$500 ETFs sin traspasos, 2019-01-01 → 2026-09-25, Railway US$60 al año restado de la cartera total en M1.
Umbrales del semáforo sin cambios (`research/semaforo.yaml`, 25-oct).

## Semáforo por escenario

| Métrica (umbral) | Bitso, costo medido (0.49%) | Bitso, modelo (0.37%) | Global a 0.10% (0.12%) |
|---|---|---|---|
| **M1** contra 60/40: ≥ 4 de 6 años y bootstrap ≥ 0.90 | ❌ 4/6, 0.882 | ✅ 5/6, 0.922 | ✅ 5/6, 0.978 |
| **M2** contra BTC + efectivo a igual volatilidad: bootstrap ≥ 0.90 | ❌ 0.677 | ❌ 0.765 | ✅ 0.9035 |
| **M3** caída con costos ×1.5: total ≤ 30%, cripto ≤ 40% | ❌ −41.4% / −45.1% | ❌ −39.5% / −43.2% | ✅ −29.4% / −30.3% |
| **M4** costo cripto ≤ 6% al año y ≤ 1/3 de la ganancia bruta | ❌ 14.0% | ❌ 10.8% | ✅ 3.6% (bruta 56.2%) |
| **M5** M1 y M2 con costos ×1.5 | ❌ M1 1/6, 0.521; M2 0.359 | ❌ M1 4/6, 0.842; M2 0.625 | ❌ M1 5/6, 0.973 ✅; **M2 0.875** ❌ |
| **Ganadora en backtest (M1–M5)** | **No** | **No** | **No (4 de 5; falla M2 con estrés)** |

**M6** (4 semanas en simulado en el exchange elegido) no se mide en backtest. En Bitso, el piloto **no cumple la
fidelidad de costo**: mide 49 pb por movimiento desde el 24-sep contra 37 pb modelados (+32%, el umbral es +20%). Kill
switch a 25 puntos (caída −19.5% contra −45%) y sin ciclos fallidos (snapshot del 1-nov).

## Las cifras detrás

| | Bitso medido | Bitso modelo | Global 0.10% |
|---|---:|---:|---:|
| Cartera total, neta de Railway | +25.4% (caída −38.1%) | +29.0% (−34.8%) | **+38.1% (−27.3%)** |
| Cartera total sin Railway | +28.5% | +32.1% | +41.0% |
| 60/40 solo (referencia de M1) | +11.0% (−21.2%) | +11.0% (−21.2%) | +11.0% (−21.2%) |
| Bloque cripto | +37.4% (−41.4%), Sharpe 1.19 | +41.9% (−37.1%), Sharpe 1.29 | **+52.6% (−28.4%), Sharpe 1.51** |
| BTC + efectivo a igual volatilidad (referencia de M2) | +28.2% (−49.2%), 50% BTC | +28.4% (−49.4%), 51% BTC | +28.9% (−49.9%), 51% BTC |
| BTC puro (sin umbral) | +49.1% (−76.7%) | +49.1% (−76.7%) | +49.1% (−76.7%) |
| Contra BTC puro: años / bootstrap | 3/6, 0.289 | 3/6, 0.346 | 3/6, 0.503 |
| M7: comisiones / Railway en 7.7 años | US$3,409 / US$464 | US$3,067 / US$464 | US$1,498 / US$464 |

Por año, cartera total con exchange global contra el 60/40: 2021 +124.1% contra +15.7%; 2022 −13.0% contra −16.8%;
2023 +41.3% contra +16.8%; 2024 +69.7% contra +14.6%; 2025 −6.1% contra +14.1%; 2026 +43.9% contra +6.9%. Con Bitso
medido: +101.7%, −17.3%, +24.2%, +49.5%, −15.5%, +27.2%.

## Lectura

- **Con Bitso, el bot no es rentable según tu propia definición.** Al costo que de verdad paga hoy (49 pb), gana al 60/40
  en 4 de 6 años pero sin la confianza pedida (0.88), no le gana a BTC con el mismo riesgo y se come 14% al año en costos.
- **Con un exchange a 0.10% está cerca:** cumple M1 a M4 (le gana al 60/40 con 0.98 de confianza, a BTC a igual riesgo con
  0.90 —justo en el umbral—, caída total −27% y 3.6% de costo). Falla M5: con costos 1.5 veces más altos, la ventaja sobre
  BTC a igual riesgo baja a 0.875. Por la regla preregistrada **no es «ganadora»**, y no se mueve el umbral.
- **Contra BTC puro no gana en rendimiento** en ningún escenario (+52.6% contra +49.1%, bootstrap 0.50 con 0.10%): lo que
  el bot aporta es mucho menos caída (−28% contra −77%), no más rendimiento.
- **Railway pesa ≈3 puntos al año** sobre US$1,000 (+41.0% → +38.1%). Con hosting propio o más barato (I1), M1 mejora.
- **Las cifras absolutas son optimistas** (2019–2026 incluye la subida de 2020–2021); las diferencias entre escenarios y
  contra las referencias en los mismos días son lo comparable.

## Qué sigue

1. La elección de exchange (H7) es de Brandon: es lo que separa «no rentable» de «casi».
2. Si elige uno a 0.10%, la evidencia que falta (M5 y M6) solo la da el simulado hacia adelante contra el libro de ese
   exchange. Hoy el simulador contra el libro solo existe para Bitso.
3. Si se queda en Bitso, lo que mueve el semáforo es bajar el costo medido: órdenes maker (H4, se evalúa el 22-nov) y
   universo líquido con filtro de spread (H6, siguiente sprint).
