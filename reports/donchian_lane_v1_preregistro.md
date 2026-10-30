---
protocol_version: 1
status: approved
approved_by: Brandon («abre ese carril», 30-oct-2026 16:08 CDMX), ejecutado por Claude con la autonomía del 25-oct (DEC-030)
approved_at_utc: '2026-10-30T22:08:00+00:00'
experiment_id: donchian-lane-v1
hypothesis: La ruptura Donchian 55/20 con partes iguales y sin régimen BTC (mejor variante de la familia F4
  del catálogo 100, que NO superó la corrección por 101 comparaciones) obtiene hacia adelante, en los mismos
  días y con los mismos costos, un resultado neto no inferior al control vigente con no más rotación y una
  caída no peor por más de 2 puntos.
evaluation_window: Desde la primera observación futura de reloj real (nunca antes del commit de este
  preregistro); al menos 28 días completos transcurridos y 28 fechas observadas con continuidad de cierres.
  No se cuentan históricos, no se rellenan días ni se mueven fechas. El histórico 2019–2026 ya fue inspeccionado
  por 155 intentos y es solo la base de selección, no evidencia.
config_sha256: 7f1ec8f5cb54e35daf078640db82d47908f32d3d25e073059bac5def293365ba
variant_ids:
- crypto:2b12bfad2351b6e2494a
- crypto:99cc948cead2737e0f29
criteria:
  walk_forward: Parámetros canónicos fijos (55/20, partes iguales, volatilidad objetivo 40%, tope 40% salvo
    activo único, freno y kill switch del control); ninguna optimización durante el carril. Comparación
    prospectiva pareada tras una selección retrospectiva declarada como no significativa.
  placebo: No aplica al carril (no se reestima); el catálogo 100 registró p ajustada 0.69 y la hipótesis
    se mantiene como observacional. Tras 28 días se reporta el bootstrap pareado sin umbral de aprobación.
  bootstrap: 'Catálogo 100: p sin corregir 0.08, p ajustada 0.69, Sharpe 1.34 contra 1.19, 4 de 6 años.
    En el carril: bootstrap pareado por bloques de 7 días sobre los días observados, informativo.'
  cost_stress: Costo constante 0.42% por lado en ambas carteras (comisión 0.36% + deslizamiento 0.06%),
    el medido en el piloto; ETF 0.05%. Estrés 0.63% registrado en el catálogo (+48.8% contra +29.8%). No se
    afirman fills reales del libro de Bitso.
  drawdown: Caída prospectiva de la candidata no peor que la del control por más de 2 puntos; kill switch
    45% cripto / 25% ETF sin relajación.
  paper: 28 días completos observados y transcurridos sin huecos ni incidencias; resultado neto no inferior
    al control; rotación de la candidata ≤ la del control; cualquier promoción exige revisión humana
    (Brandon), un DEC y 4 semanas más en el piloto simulado. Nunca activa dinero real.
---

# Preregistro — carril prospectivo Donchian 55/20 (H10)

**Qué es.** La mejor variante de la familia «ruptura Donchian» del catálogo 100 (`donchian-55-20-equal`): se
compra un activo cuando su cierre supera el máximo de los 55 cierres previos y se vende cuando cae bajo el
mínimo de los 20 previos; se tienen todos los activos en ruptura a partes iguales, con tope del 40% por activo
(salvo cuando solo hay uno en ruptura, que puede llevar más antes del escalado por volatilidad), volatilidad
objetivo 40%, el mismo freno por caída y kill switch del control, y **sin** el filtro de régimen de BTC. Universo:
las 16 monedas con par USD en Bitso.

**Por qué un carril y no el piloto.** En 2019–2026 rindió +53.4% anual (Sharpe 1.34, caída −37.3%) contra
+38.3% del control (1.19, −34.3%) con la mitad de la rotación (16 contra 31 al año), pero esa ventaja está
concentrada en 2023 y **no sobrevive la corrección por las 101 comparaciones del catálogo** (p ajustada 0.69).
Un backtest así no autoriza cambiar el bot. Lo único honesto es observarla hacia adelante, en los mismos días
que el control, con los mismos costos, y decidir con eso. Brandon lo pidió explícitamente el 30-oct.

**Cómo corre.** `lab.paper_comparison` (dos carteras virtuales de US$1,000: US$500 cripto + US$500 ETF 60/40
idéntico en ambas; `SimBroker`, sin libro, sin credenciales, sin tocar `config.yaml` ni el piloto). El control
del plan se genera desde `config.yaml` (`scripts/lanes/donchian_lane_plan.py`) y el gate de ejecución comprueba
que `config.yaml` no cambió; si el piloto cambia, el carril se reabre con un plan nuevo. La candidata usa la
misma función `lab.portfolio.target_weights` que el bot (`signal: donchian`), con prueba de identidad contra la
variante del catálogo y prueba de «sin mirar al futuro» (`tests/test_portfolio.py`). El ejecutor es separado:
una tarea programada diaria en la Mac de Brandon escribe en `Trading Lab/carriles/carril-1/` (fuera del repo),
una observación por día (UTC) tras el cierre de la vela; los reintentos del mismo día son idempotentes.

**Qué puede salir de aquí.** A los 28 días: una tabla control contra candidata (resultado neto, caída, rotación,
costo) y el bootstrap pareado informativo. Si la candidata no es inferior en resultado, no rota más y su caída no
es peor por más de 2 puntos, se le propone a Brandon un DEC para reemplazar al control en el piloto simulado
durante 4 semanas más. Si no, se cierra el carril y la familia F4 queda descartada con el dato hacia adelante.
En ningún caso el carril activa dinero real.
