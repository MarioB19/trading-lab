---
protocol_version: 1
status: approved
experiment_id: h9-parabolic-sar
type: señal
approved_by: Claude, a petición de Brandon (30-oct-2026), con la autonomía acordada el 25-oct-2026 (DEC-030)
date: 2026-10-30
---

# H9 — Parabolic SAR como capa de salida (y como señal) en el bloque cripto (preregistro)

## Hipótesis

**Falsable:** añadir el Parabolic SAR de Wilder (diario) a la regla vigente del bloque cripto mejora el
rendimiento neto de costos **porque sale antes de las caídas** que la regla actual (que espera a que el
precio pierda los promedios de 20/50/100/200 días). La afirmación es de *timing*, así que es un
**cambio de señal** (`AGENTS.md`, regla 3): aplica la barra completa (walk-forward, placebo, bootstrap,
Sharpe deflactado, estrés de costos).

Motivación: la atribución al 30-oct da −US$29.5 por «estrategia» desde el 24-sep (selección y salidas
tardías en SOL, LTC y ETH). Evidencia externa previa (recogida antes de correr): el SAR solo le gana a
comprar y mantener en 19–30% de las acciones del Dow en velas diarias; en BTC diario 2023–2026 fue 3.º de
49 estrategias por Sharpe (1.25) pero con 94 operaciones en 37 meses, 36% de aciertos y factor de ganancia
1.09 con costos de 0.15%. Las fuentes coinciden en que **solo funciona con un filtro de tendencia encima**.
Por eso la variante principal es el SAR *sobre* la regla actual, no en su lugar.

## Definición del indicador (fija, sin optimizar)

Parabolic SAR de Wilder sobre máximos y mínimos diarios, por activo:
- Inicio alcista si el cierre del segundo día supera al del primero. SAR inicial = extremo opuesto.
- Factor de aceleración `af` que empieza en `af0`, sube `step` con cada nuevo extremo y se topa en `af_max`.
- El SAR del día t se calcula solo con datos hasta t−1 y se limita a los extremos de los dos días anteriores;
  si el mínimo (alcista) o el máximo (bajista) del día t lo cruzan, la tendencia cambia ese día al cierre.
- `psar_bull[t]` = True si al cierre de t la tendencia es alcista. Se usa en la decisión de t, que el motor
  aplica al día t+1 (mismo convenio que el resto de la regla).
- Si para un día no hay máximo/mínimo (activo aún no listado en la fuente OHLC), se usa el cierre como
  máximo y mínimo de ese día. Se reporta cuántos días-activo caen en ese caso.

## Control y variantes (exactas)

Universo: las 16 monedas con par USD en Bitso (`BITSO_TRADABLE`), elegibles tras 250 días de historia.
Parámetros comunes del control vigente (`config.yaml`): `top_k=5, vol_target=0.40, regime_asset=BTC,
dd_brake=True, max_weight=0.40, mom_windows=(30, 90, 180)`, banda 2 pp, kill switch −45%, rebalanceo diario.

| ID | Qué cambia respecto al control | `af0 / step / af_max` |
|---|---|---|
| control | nada: tendencia ≥ 0.5 y momentum > 0; régimen por tendencia de BTC | — |
| v1-sar-filtro | **SAR como capa de salida:** un activo solo es elegible si además `psar_bull` es True. Se vende cuando el SAR gira; se recompra solo cuando la regla actual y el SAR coinciden. Régimen y pesos sin cambio | 0.02 / 0.02 / 0.20 |
| v2-sar-filtro-lento | igual que v1 con SAR lento (menos giros, salida más tardía) | 0.01 / 0.01 / 0.10 |
| v3-sar-tendencia | **SAR en lugar del filtro de tendencia:** `trend` := `psar_bull` (1 o 0) para elegibilidad, régimen de BTC y pesos (1/vol). Momentum sigue ordenando | 0.02 / 0.02 / 0.20 |

No se probará ningún otro juego de parámetros en este sprint. Cambiarlos después de ver resultados
exige un preregistro nuevo y este intento queda registrado.

## Datos y ventana

- Cierres: `data/crypto_prices.csv` (CoinMetrics/Yahoo hasta 2026-09-26), el mismo panel que el bot y que
  los sprints 01 y 02 (`lab.data.load_crypto_panel`). Así el control reproduce exactamente al de esos sprints.
- Máximos y mínimos: velas diarias (UTC) de **OKX, pares USDT**, descargadas con `scripts/research/h9_ohlc.py`
  a `data/crypto_ohlc_okx.csv`. Se aplican al panel de cierres como razones `alto/cierre` y `bajo/cierre` del
  mismo día (así una diferencia de venue no desplaza la serie de cierres). Fuente única para las 16 monedas.
- Evaluación 2019-01-01 → 2026-09-26; comparación por año 2021–2026 (2026 parcial, hasta septiembre).
- **Honestidad:** este histórico ya se inspeccionó en estudios previos (43 intentos de la etapa Codex más 7 de
  los sprints 01 y 02). Es evidencia retrospectiva, no un holdout limpio. Los parámetros del SAR son los
  canónicos de Wilder, no se ajustan a los datos. La evidencia hacia adelante será el piloto simulado.

## Costos

- Base: **0.42% por lado** (costo medido del piloto desde el 24-sep: comisión + diferencia contra la
  referencia, 42 pb según `review.py weekly` al 30-oct; el de 30 días es 46 pb).
- Estrés: **0.63% por lado** (×1.5).

## Cuenta de costos (antes de correr)

- Ida y vuelta medida ≈ 0.84%. El control rota ≈30× al año y paga ≈11% anual (sprint 01).
- v1/v2 solo pueden *añadir* salidas y recompras: la rotación sube. Si el SAR gira ~30 veces al año por
  activo en diario, el costo extra en el peor caso ronda 10–15 puntos anuales. Para aprobarse, la mejor
  salida tiene que pagar eso y además superar al control con claridad estadística.
- v3 cambia la señal de tendencia por una más rápida: se espera más rotación que el control.
- Pasa el filtro rápido (ganancia bruta esperada ≈ 2.1% por operación en BTC diario según la evidencia
  externa, > 2× el costo de ida y vuelta), pero por poco y en un periodo alcista; por eso se prueba.

## Métricas y regla de decisión (fijadas antes de correr)

Para cada variante contra el control, costo base salvo que se indique:

1. **Fuera de muestra por años (walk-forward sin ajuste):** mejor rendimiento neto que el control en al
   menos **4 de 6** años 2021–2026 (`lab.research_statistics.chronological_folds`; 2026 parcial se evalúa
   como año con los datos disponibles).
2. **Placebo** (`lab.research_multi.placebo`, pesos desfasados al azar, 200 desfases, semilla 5), evaluado
   desde 2021-01-01: **p < 0.05**.
3. **Bootstrap por bloques de 30 días** contra el control (`lab.validation.bootstrap_compare`, 2000
   remuestreos, semilla 11): `p_sharpe_better` ≥ **0.967** (0.90 corregido por 3 variantes).
4. **Sharpe deflactado** (`lab.validation.deflated_sharpe`) con todos los intentos de `reports/intentos.csv`
   (43 previos como `extra_trials`, los 7 con Sharpe de los sprints 01–02 y las 3 variantes de este sprint):
   `dsr` ≥ **0.95**.
5. **Estrés:** con 0.63% por lado, rendimiento anual compuesto mayor que el del control con el mismo costo.

Se aprueba la variante que cumpla los cinco criterios. Si pasan varias, se elige la de mayor Sharpe con
costo de estrés. Si ninguna pasa, el control sigue, la hipótesis va a `descartadas` con su cifra clave y
las 3 variantes quedan en `intentos.csv`.

Se reportan además, sin peso en la decisión: caída máxima (informativa: v1 afirma salir antes), rotación
anual, costo anual, Sharpe, número de giros del SAR por activo y año, y días-activo con relleno
cierre=alto=bajo.

## Qué no se hace

- No se tocan `config.yaml`, el piloto ni el bot en este sprint. El SAR entra en `lab.portfolio` como
  parámetro opt-in (`psar_mode`, por omisión apagado) con su prueba de «sin mirar al futuro», para que
  bot e investigación compartan la función (regla 6).
- Si una variante se aprobara, su paso al piloto sería un DEC aparte y exigiría que el bot reciba máximos y
  mínimos diarios de su fuente (Kraken vía ccxt da OHLCV), replay < 2% y 4 semanas de observación.
