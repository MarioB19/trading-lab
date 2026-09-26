# Trading Lab

Bot de inversión diario para criptomonedas y acciones/ETFs. Cada estrategia se prueba con datos reales antes de operar, y el control de riesgo decide cuánto se arriesga. Corre solo en GitHub Actions y se sigue desde un tablero web.

> No es asesoría financiera. Ningún algoritmo garantiza no perder dinero; este limita cuánto puedes perder y lo mide. Opera solo dinero que aceptes perder.

## Qué hace cada día

**Tablero:** https://claude.ai/artifact/YLtHeryBpEfs882YJafAGG (privado; lee `state/` con tu conector de GitHub en claude.ai). Para regenerar la versión incluida: `python -m lab.dashboard`.

A las **18:20 hora del centro de México** (00:20 UTC), GitHub Actions corre `python -m lab.bot`:

1. Descarga los cierres del día: criptos de Kraken y ETFs de Yahoo Finance.
2. **Bloque cripto (táctico):** de 16 criptos con par en USD en Bitso, elige hasta 5 con tendencia y momentum positivos. Les da más peso a las menos volátiles (paridad de riesgo) y escala el bloque a una volatilidad anual de 40%. Si BTC no está en tendencia, no compra altcoins, y si el bloque cae más de 10% frena la exposición.
3. **Bloque acciones (pasivo por evidencia):** mantiene 60% SPY / 40% IEF y rebalancea cuando se desvía 5 puntos.
4. Revisa los candados. Luego opera: primero las ventas, después las compras.
5. Guarda el estado, las operaciones y la curva de capital en `state/` y hace commit al repositorio. El tablero lee de ahí.

Cada domingo, `investigacion-semanal` descarga datos nuevos y vuelve a correr toda la validación.

## Qué dice la evidencia

Resultados **fuera de muestra**, con comisiones y deslizamiento incluidos. Las reglas se declararon antes de ver los resultados. Detalle en `reports/multi_informe.md`.

**Criptomonedas, 2021 a hoy** (costo 0.3% por operación)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Portafolio táctico (lo que usa el bot) | 37.9% | 1.23 | −38% |
| Comprar y aguantar BTC | 20.5% | 0.61 | −77% |
| Pesos iguales en el top 15, rebalanceo mensual | 19.5% | 0.60 | −78% |
| Regla de tendencia solo en BTC | 20.8% | 0.70 | −53% |

- Ninguna de 200 versiones placebo (mismos pesos desfasados en el tiempo) igualó a la estrategia.
- El universo de prueba incluye monedas que se desplomaron (LUNA, FTT, EOS, NEO…) y se eligió con la capitalización de cada día.
- Tiene 73% de probabilidad de ganar más que BTC y 98% de caer menos (bootstrap). Tras corregir por las 36 variantes probadas, que gane *más* que BTC no es estadísticamente seguro. Que caiga mucho menos sí lo es.
- Con costos de 1% por operación el rendimiento baja a 14.7%: hay que operar por API, no desde la app.

**Acciones y ETFs, 2010 a hoy** (costo 0.05%)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Rotación táctica entre 20 ETFs | 4.5% | 0.53 | −17% |
| **60/40 SPY/IEF (lo que usa el bot)** | 9.9% | 1.00 | −22% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% |

La misma lógica que funciona en cripto **no funcionó en acciones**: su timing no se distingue del azar (p = 0.34). Por eso el bloque de acciones queda en 60/40 pasivo. La táctica sigue disponible (`strategy: tactical`), pero no está recomendada.

**Multi-mercado (materias primas, divisas, bonos y bolsas en 19 ETFs), probado el 25-sep-2026:** perdió 1.4% anual de 2012 a hoy y falló los cinco criterios declarados antes de la prueba; queda apagado. Detalle en `reports/multi_market_informe.md`.

**Combinado 30% cripto / 70% ETFs (2021 a hoy):** 21.3% anual, caída máxima −26%, 22% de probabilidad de perder en un periodo de 12 meses. La racha más larga sin recuperar el máximo fue de 824 días.

## Riesgo, en números

Con $1,000 USD en cada bloque, simulando 12 meses a partir de pedazos del periodo 2021–2026:

| | Peor 5% de los casos | Mediana | P(terminar con pérdida) | P(caída >30% en el camino) |
|---|---:|---:|---:|---:|
| Cripto táctico | $746 | $1,278 | 25% | 17% |
| BTC comprar y aguantar | $450 | $1,145 | 41% | 81% |
| 60/40 | $945 | $1,104 | 13% | 0.1% |

## Candados de seguridad

- **Simulado por defecto.** El dinero real exige tres cosas a la vez: `mode: live` en `config.yaml`, la variable `CONFIRMO_DINERO_REAL=si` y las llaves del broker.
- **Capital máximo por bloque** (`capital`). El bot nunca maneja más que eso, aunque tengas más en la cuenta.
- **Freno por caída:** la exposición baja de forma gradual si el bloque cae más de 10% desde su máximo de 6 meses (solo en el bloque táctico).
- **Kill switch:** si el bloque cae 45% (cripto) o 25% (acciones) desde su máximo, vende todo y se apaga hasta que lo rearmes a mano. La peor caída histórica de la estrategia cripto fue 38%.
- **Datos:** no opera con datos viejos. Un precio que salta más de 40% en un día solo permite reducir ese activo. Un activo sin precio bloquea el día en vez de valuarse en cero.
- **No opera dos veces la misma vela.** Si quedan órdenes pendientes en Alpaca, espera.
- **Tope por compra;** las ventas que reducen riesgo nunca se frenan.
- En Bitso usa órdenes límite con tope de precio y cancela lo que no se llene en 20 s.
- Sin apalancamiento, sin cortos y sin retiros: las llaves de API deben crearse **sin permiso de retiro**.

## Puesta en marcha

El repositorio ya corre solo en modo simulado. Para ir subiendo de nivel:

**1. Simulado interno (ya activo).** No hace falta nada. Revisa el tablero cada semana.

**2. Acciones en Alpaca paper (gratis, sin dinero real).** Crea una cuenta en alpaca.markets y activa la autenticación en dos pasos. Genera llaves de *Paper Trading* y agrégalas en GitHub → Settings → Secrets and variables → Actions → *New repository secret*: `ALPACA_KEY_ID` y `ALPACA_SECRET_KEY`. Desde la siguiente corrida, las órdenes del bloque de acciones van a tu cuenta paper.

**3. Dinero real (después de 4 a 8 semanas en simulado).**
- *Cripto (Bitso):* convierte MXN a USD dentro de Bitso. Crea una llave de API con permisos de **ver saldo y operar**, sin retiros, y agrega los secrets `BITSO_API_KEY` y `BITSO_API_SECRET`.
- *Acciones:* Alpaca acepta cuentas reales de muchos países, pero no publica si México está incluido; confírmalo con su soporte. Si no, la alternativa es Interactive Brokers (requiere agregar un conector).
- Ajusta `capital` en `config.yaml` a lo que aceptes perder. Cambia `mode: live` y crea la *variable* (no secret) `CONFIRMO_DINERO_REAL` con valor `si`.
- Para volver a simulado basta con borrar esa variable.

## Uso local

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q -W ignore                         # 33 pruebas
python -m lab.research_multi --refresh                # investigación completa (~2 min)
python -m lab.bot                                     # corrida del día, simulada
python -m lab.bot --replay 365                        # el bot re-juega un año y se compara con el backtest
python -m lab.bot --status
python -m lab.bot --reset-kill-switch crypto
```

## Estructura

| Archivo | Qué hace |
|---|---|
| `src/lab/portfolio.py` | Estrategia de portafolio: tendencia, momentum, paridad de riesgo, volatilidad objetivo, freno y simulación |
| `src/lab/research_multi.py` | Validación: walk-forward, placebo, bootstrap, Sharpe deflactado, costos, Monte Carlo |
| `src/lab/bot.py` | Bot diario por bloques, candados y archivos para el tablero |
| `src/lab/brokers.py` | Simulado interno, Alpaca (paper/real) y Bitso |
| `src/lab/data.py` | CoinMetrics, Yahoo Finance y exchanges vía ccxt |
| `src/lab/research.py`, `btc_bot.py` | El estudio original de BTC solo (`reports/informe.md`) |
| `state/` | Estado del bot, operaciones (`trades.csv`), capital diario (`equity.csv`) y foto para el tablero (`snapshot.json`) |
| `config.yaml` | Todo lo ajustable |

## Limitaciones

- El pasado no garantiza el futuro. Los años 2021–2026 incluyen un mercado alcista fuerte en cripto.
- La lista inicial de criptos se hizo en 2026. Incluye monedas que se desplomaron, pero queda algo de sesgo de supervivencia.
- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.
- No modela impuestos (lleva registro para el SAT y consulta a un contador), tipo de cambio MXN/USD ni la quiebra de un exchange.
- GitHub Actions puede retrasar la corrida programada varios minutos. La estrategia es diaria, así que no importa.
