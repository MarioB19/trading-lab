---
experiment_id: sprint04-h13-rebalanceo-bloques
fecha: 2026-11-01
veredicto: ninguna variante aprobada como mejora; se conserva el control; queda como decisión de riesgo para Brandon
---

# Sprint 04 — H13: rebalancear entre el bloque cripto y el de ETFs (resultado)

Preregistro: `reports/sprint04_h13_rebalanceo_bloques_preregistro.md` (commit `cbe82b5`, antes de correr). Script:
`scripts/research/sprint04_h13_rebalanceo_bloques.py`. Regla: `lab.sleeve_rebalance.combine_sleeves`, con pruebas de
identidad (sin regla = suma de los bloques) y de «sin mirar al futuro» en `tests/test_sleeve_rebalance.py`.
Ventana 2019-01-01 → 2026-09-25, una corrida compuesta desde US$1,000 (US$500 + US$500). Bloque cripto: control vigente
con 0.37% por lado y orden mínima US$25. Bloque ETFs: 60/40 SPY/IEF, banda 5 pp, kill −25% (no se activó; caída máxima
−21.2%). Fricción por traspaso: 1.42% de lo movido (0.37% cripto + 0.05% ETFs + 1.0% de plataforma, supuesto); estrés 2.13%.

**Los bloques en la ventana:** cripto +41.9% anual (volatilidad 30.8%, caída −37.1%); ETFs +11.0% anual (11.6%, −21.2%);
correlación diaria 0.16.

## Resultado

| Variante | Rend. anual | Volatilidad | Sharpe | Caída máx. | Traspasos | Fricción | Peso cripto medio / máx. | Final (de US$1,000) | Con estrés |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Control (sin traspasos) | **+32.1%** | 23.7% | 1.29 | −32.3% | 0 | — | 75% / 89% | **US$8,606** | +26.7% |
| h13-banda10 (40–60%) | +26.9% | 17.8% | **1.43** | −25.4% | 4 | US$16 | 51% / 60% | US$6,330 | +24.1% |
| h13-banda15 (35–65%) | +27.9% | 18.4% | **1.43** | **−25.2%** | 3 | US$24 | 52% / 65% | US$6,718 | +24.1% |
| h13-anual (31-dic) | +27.9% | 18.4% | 1.43 | −26.6% | 7 | US$30 | 53% / 73% | US$6,707 | +24.4% |

| Variante | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---:|---:|---:|---:|---:|---:|
| control | +113.6% | −14.7% | +31.2% | +57.0% | −11.9% | +33.2% |
| h13-banda10 | +84.4% | −15.4% | +26.4% | +40.2% | −2.7% | +22.2% |
| h13-banda15 | +88.5% | −15.4% | +26.2% | +43.1% | −0.9% | +20.3% |
| h13-anual | +92.3% | −15.5% | +25.6% | +40.0% | −0.9% | +22.6% |

\*2026 hasta el 25-sep.

### Criterios (barra de costo)

| Variante | 1. Mayoría de años | 2. Bootstrap rendimiento (≥ 0.967) | 3. Caída vs control | 4. Estrés vs control | Aprobada |
|---|---|---|---|---|---|
| h13-banda10 | ❌ 1/6 | ❌ 0.156 | ✅ +6.9 pts | ❌ −2.6 pts | ❌ |
| h13-banda15 | ❌ 1/6 | ❌ 0.208 | ✅ +7.1 pts | ❌ −2.6 pts | ❌ |
| h13-anual | ❌ 1/6 | ❌ 0.212 | ✅ +5.7 pts | ❌ −2.3 pts | ❌ |

Informativo, mismo bootstrap: probabilidad de mejor Sharpe 0.955 / 0.957 / 0.940 (no llega a 0.967) y de menor caída
0.996 / 0.985 / 0.984. Sin fricción de traspaso el rendimiento casi no cambia (+27.0% / +28.0% / +28.0%): la fricción no
es el problema.

### Inicio móvil (informativo): misma comparación empezando cada 1 de enero

| Inicio | Control | banda10 | banda15 | anual |
|---|---|---|---|---|
| 2019 | +32.1% (−32.3%) | +26.9% (−25.4%) | +27.9% (−25.2%) | +27.9% (−26.6%) |
| 2020 | +33.4% (−32.3%) | +27.5% (−25.4%) | +28.6% (−25.2%) | +28.8% (−26.6%) |
| 2021 | +27.9% (−30.1%) | +24.1% (−25.2%) | +24.8% (−26.6%) | +25.7% (−26.8%) |
| 2022 | +14.7% (−18.7%) | +14.2% (−17.7%) | +14.9% (−17.7%) | +14.5% (−17.9%) |
| 2023 | +23.3% (−18.3%) | +24.4% (−16.9%) | +23.9% (−16.4%) | +23.5% (−17.6%) |
| 2024 | +21.9% (−18.0%) | +22.1% (−16.7%) | +21.9% (−18.0%) | +22.6% (−17.9%) |

Rendimiento anual (caída máxima). Desde 2022 las variantes empatan o ganan poco en rendimiento y siempre caen menos;
desde 2019–2021 pierden 4–6 puntos al año, porque en esos caminos cripto subió mucho más que los ETFs.

## Lectura

- **Veredicto: H13 no es una mejora; el control se conserva.** Ninguna variante cumple la barra de costo: ganan 1 de 6
  años, el bootstrap del rendimiento queda en 0.16–0.21 y pierden 2.3–2.6 puntos con estrés.
- **Lo que pasó es lo que anticipaba la cuenta previa** (sin rebalanceo ≈ +31.7%, rebalanceado ≈ +25.4%; salió +32.1% y
  +26.9–27.9%). La prima de rebalanceo existe (≈1 punto), pero es mucho menor que la diferencia de crecimiento entre un
  bloque que rindió +42% y otro que rindió +11%. Sin traspasos, el que más crece termina mandando.
- **El hallazgo útil es de riesgo, no de rendimiento:** sin traspasos, el «50/50» del piloto fue en promedio **75% cripto
  y llegó a 89%**. Rebalancear lo mantiene cerca de 50%, baja la volatilidad de 24% a 18%, la caída máxima de −32% a −25%
  y sube el Sharpe de 1.29 a 1.43, a cambio de ≈4–5 puntos de rendimiento al año en esta muestra (US$6.3–6.7 mil contra
  US$8.6 mil sobre US$1,000 en 7.7 años). Es la misma clase de decisión que H12: cuánto riesgo de cripto quiere Brandon.
- **Qué cambia en el bot:** nada. La función queda en `lab.sleeve_rebalance` con sus pruebas. Si Brandon decide mantener
  el reparto, la opción más simple es la banda de 15 pp (3 traspasos en 7.7 años), y con dinero real cada traspaso lo
  haría él a mano (regla dura 2).

## Limitaciones

- Histórico ya inspeccionado (retrospectivo, no holdout). Datos CoinMetrics/Yahoo, no el libro de Bitso. Una sola gran
  subida de cripto (2020–2021) domina el resultado del control.
- La fricción de traspaso entre plataformas (1%) es un supuesto: no hay dato medido. No cambia el veredicto.
- Los rendimientos de cada bloque se toman como independientes de su tamaño; en el bot, el freno del bloque cripto tendría
  que ajustar su pico por los flujos para no confundir un traspaso con una caída.
