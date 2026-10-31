---
protocol_version: 1
status: approved
experiment_id: catalogo2-etf
type: barrido (asignación y señal, por familia) en el bloque de ETFs
config_sha256: 2a50b1d298a4848065c897db8a4e4c0064adfe5d61cb40ca428cde706a90ccd1
n_variants: 53
approved_by: Claude, siguiendo la petición de Brandon de seguir investigando más estrategias (30 y 31-oct-2026), con la autonomía del 25-oct (DEC-030)
date: 2026-10-31
---

# Catálogo 2 — 53 estrategias para el bloque de ETFs contra el 60/40 (preregistro)

## Por qué el bloque de ETFs

Es la mitad del capital (US$500) y casi no se ha estudiado: solo se descartó la táctica (4.5% contra 9.9% del 60/40,
`reports/multi_informe.md`) y el multi-mercado. Su costo es **0.05% por lado** (contra 0.42% en cripto), así que aquí
una ventaja pequeña sí puede sobrevivir a los costos. El Catálogo 100 enseñó que en cripto no hay señal que pague las
comisiones; esta es la otra mitad de la pregunta.

## Hipótesis (falsable)

Existe al menos una asignación o regla mensual/diaria solo compras sobre ETFs líquidos (SPY, EFA, EEM, TLT, IEF, GLD,
DBC, VNQ y los nueve sectores SPDR) que supera al 60/40 SPY/IEF vigente en 2008–2026 con una ventaja que sobrevive a la
corrección por las 53 comparaciones de este catálogo, y cuyo riesgo (caída máxima) no es peor en más de 5 puntos.

## Control, motor y datos (comunes)

- Control: la regla vigente del bloque (`config.yaml`): 60% SPY / 40% IEF, banda de 5 puntos, rebalanceo diario,
  sin freno por caída (estrategia `passive`), kill switch −25%.
- Motor: `lab.portfolio.simulate_portfolio` con 252 días por año, banda 5 pp y kill −25% para todas; sin freno por
  caída salvo E10, que lo estudia. Decisiones «mensuales» el primer día de bolsa del mes; el resto deriva.
- Datos: `data/etf_prices.csv` (Yahoo, precios ajustados por dividendos, 1998 → 2026-09-25), los 20 ETFs del universo
  del bloque; elegibles tras 250 días de historia (DBC desde 2007, GLD desde 2005…). Las mezclas reparten entre los
  ETFs ya listados hasta que el resto cotiza.
- Evaluación 2008-01-01 → 2026-09-25; años 2010–2026 (17, 2026 parcial) para la comparación por años, como en el
  estudio del 25-sep (`oos_year` 2010).
- Costos: **0.05% por lado** (comisión 0 + deslizamiento 0.05%, el del bot); estrés **0.075%**.
- Pruebas: pesos válidos para las 53 y «sin mirar al futuro» para una muestra de cada familia con estado
  (`tests/test_catalog_etf.py`).

## Catálogo (53 variantes, 10 familias)

| Familia | n | Variantes |
|---|---:|---|
| E1 mezclas fijas | 8 | `mix-50-50`, `mix-70-30`, `mix-40-60`, `mix-60-40-tlt`, `mix-permanente`, `mix-todo-clima`, `mix-60-40-oro10`, `mix-global-4` |
| E2 paridad de riesgo (mensual) | 8 | `rp-spy-ief-w63`, `rp-spy-ief-w126`, `rp-spy-tlt-gld-w63`, `rp-spy-tlt-gld-w126`, `rp-spy-ief-gld-dbc-w63`, `rp-spy-ief-gld-dbc-w126`, `rp-spy-efa-eem-ief-tlt-gld-w63`, `rp-spy-efa-eem-ief-tlt-gld-w126` |
| E3 tendencia sobre el 60/40 | 6 | `trend-spy100-to-ief`, `trend-spy100-to-cash`, `trend-spy200-to-ief`, `trend-spy200-to-cash`, `trend-spy300-to-ief`, `trend-spy300-to-cash` |
| E4 momentum dual (GEM) | 3 | `gem-3m`, `gem-6m`, `gem-12m` |
| E5 momentum de sectores | 8 | `sector-6m-top3`, `sector-6m-top5`, `sector-6m-top3-ief40`, `sector-6m-top3-trend`, `sector-12m-top3`, `sector-12m-top5`, `sector-12m-top3-ief40`, `sector-12m-top3-trend` |
| E6 momentum entre clases de activo | 9 | `class-top2-equal`, `class-top2-abs-equal`, `class-top2-abs-invvol`, `class-top3-equal`, `class-top3-abs-equal`, `class-top3-abs-invvol`, `class-top4-equal`, `class-top4-abs-equal`, `class-top4-abs-invvol` |
| E7 volatilidad objetivo sobre el 60/40 | 4 | `voltarget-6`, `voltarget-8`, `voltarget-10`, `voltarget-12` |
| E8 rebalanceo del 60/40 | 3 | `control-mensual`, `control-band-2`, `control-band-10` |
| E9 duración del bono (IEF/TLT) | 2 | `bondswitch-tlt100`, `bondswitch-tlt200` |
| E10 freno por caída sobre el 60/40 | 2 | `control-ddbrake-5-20`, `control-ddbrake-10-30` |

Definiciones exactas en `src/lab/catalog_etf.py` (commit de este preregistro). Referencias informativas: SPY y IEF
comprar y mantener. Fuera del alcance: la táctica ya descartada, el multi-mercado ya descartado, apalancamiento,
cortos, bonos individuales y activos sin ETF en el universo del bot.

## Dos tipos de familia, dos barras

- **Asignación (sin afirmar timing):** E1, E2, E8. Se juzgan con la barra de costo: mayoría de años, bootstrap de
  rendimiento, caída no peor por más de 2 puntos, estrés. El placebo no aplica (una mezcla fija desfasada en el tiempo
  es la misma mezcla).
- **Señal (afirman timing):** E3, E4, E5, E6, E7, E9, E10. Barra completa de señal.

## Compuerta de costos

Rotación anual medida en el backtest ≤ **20** (≈1% anual con 0.05%). Por encima, descartada por costos sin mirar el
rendimiento; cuenta como intento.

## Etapa 1 — barrido con corrección familiar

Sobre 2008–2026, para las que pasan la compuerta: `familywise_block_test` (bloques de 21 días de bolsa, 2000
remuestreos, semilla 17) contra el control. Avanza si: `p_adjusted` < **0.10**, Sharpe > control, caída máxima no
peor por más de **5 puntos**, y rendimiento anual con estrés > control con estrés.

## Etapa 2 — confirmación

Para cada variante que avanza (k = número de variantes que avanzan):
1. Años 2010–2026: mejor rendimiento neto que el control en al menos **9 de 17**.
2. Señal: placebo (`lab.research_multi.placebo`, 200 desfases, semilla 5, desde 2010-01-01) **p < 0.05**. Asignación: no aplica.
3. Bootstrap por bloques de 21 días contra el control (2000, semilla 11): señal `p_sharpe_better` ≥ **1 − 0.10/máx(3, k)**;
   asignación `p_return_better` ≥ el mismo umbral.
4. Sharpe deflactado con **todos los intentos** (`reports/intentos.csv`: 43 previos como `extra_trials`, los 113 con
   Sharpe diario, y las 53 de este catálogo): `dsr` ≥ **0.95**. Nota: los intentos previos son de cripto; se cuentan
   igual porque todos son búsquedas sobre el mismo proyecto.
5. Estrés: rendimiento anual con 0.075% > control con 0.075%.
6. Asignación además: caída máxima no peor por más de 2 puntos.

**Ganadora** = cumple todo. Si hay varias, la de mayor Sharpe con costo de estrés. Una ganadora **no entra al piloto**
por el backtest: se propone a Brandon un carril (carril-2) de 28 días contra el 60/40 y, si él aprueba y sobrevive, un
DEC para el bloque de ETFs. Si ninguna pasa, cada familia va a `descartadas` con su mejor cifra.

## Honestidad

- 2008–2026 incluye la crisis de 2008 (favorece a las reglas que salen a bonos) y 2022 (castiga al 60/40 y a TLT). El
  60/40 se eligió sobre este histórico el 25-sep. Es evidencia retrospectiva.
- Precios ajustados de Yahoo: sin contabilidad independiente de dividendos; costo constante por lado.
- Parámetros canónicos de la literatura (GEM de Antonacci, SMA 200, 12−1, paridad de riesgo), sin ajustar.
