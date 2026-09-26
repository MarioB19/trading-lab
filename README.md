# Trading Lab

Bot de inversión diario para criptomonedas y acciones/ETFs. Cada estrategia se prueba con datos reales antes de operar, y el control de riesgo decide cuánto se arriesga. Corre solo en GitHub Actions y se sigue desde un tablero web.

> No es asesoría financiera. Ningún algoritmo garantiza no perder dinero; este limita cuánto puedes perder y lo mide. Opera solo dinero que aceptes perder.

## Qué hace y cuándo

**Tablero:** https://claude.ai/artifact/YLtHeryBpEfs882YJafAGG (privado; lee `state/` con tu conector de GitHub en claude.ai). Para regenerar la versión incluida: `python -m lab.dashboard`.

**Cada hora** (a los :07), GitHub Actions corre la revisión en tiempo real (`python -m lab.realtime --once`): valúa las posiciones al precio de ese momento, mide la caída contra el máximo, calcula qué haría la señal si el día cerrara ahí y avisa si el bloque se acerca al kill switch. No opera (ver "¿Y en tiempo real?"). Antes llama a `python -m lab.bot --if-due`, así que si GitHub se salta la corrida diaria, la hora siguiente la pone al día.

**Una vez al día**, tras el cierre de las 00:00 UTC (18:00 en el centro de México), la corrida diaria (`python -m lab.bot`) opera:

1. Descarga los cierres del día: criptos de Kraken y ETFs de Yahoo Finance.
2. **Bloque cripto (táctico):** de 16 criptos con par en USD en Bitso, elige hasta 5 con tendencia y momentum positivos. Les da más peso a las menos volátiles (paridad de riesgo) y escala el bloque a una volatilidad anual de 40%. Si BTC no está en tendencia, no compra altcoins, y si el bloque cae más de 10% frena la exposición.
3. **Bloque acciones (pasivo por evidencia):** mantiene 60% SPY / 40% IEF y rebalancea cuando se desvía 5 puntos.
4. Revisa los candados. Luego opera: primero las ventas, después las compras.
5. Guarda el estado, las operaciones y la curva de capital en `state/` y hace commit al repositorio. El tablero lee de ahí.

Cada domingo, `investigacion-semanal` descarga datos nuevos y vuelve a correr toda la validación.

## Qué dice la evidencia

Resultados **fuera de muestra**, con comisiones y deslizamiento incluidos. Las reglas se declararon antes de ver los resultados. Detalle en `reports/multi_informe.md`.

**Criptomonedas, 2021 a hoy** (costo real de Bitso: 0.45% por operación = 0.36% de comisión contra USD + medio diferencial medido en su libro)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Portafolio táctico (lo que usa el bot) | 32.3% | 1.10 | −42% |
| Comprar y aguantar BTC | 20.5% | 0.61 | −77% |
| Pesos iguales en el top 15, rebalanceo mensual | 19.2% | 0.60 | −78% |
| Regla de tendencia solo en BTC | 17.0% | 0.62 | −56% |

- Ninguna de 200 versiones placebo (mismos pesos desfasados en el tiempo) igualó a la estrategia.
- El universo de prueba incluye monedas que se desplomaron (LUNA, FTT, EOS, NEO…) y se eligió con la capitalización de cada día.
- Tiene 66% de probabilidad de ganar más que BTC y 97% de caer menos (bootstrap). Tras corregir por las 39 variantes probadas (36 diarias y 3 de tiempo real), que gane *más* que BTC no es estadísticamente seguro. Que caiga mucho menos sí lo es.
- Los costos pesan mucho: con 0.30% por operación rendiría 37.9%; con 0.60%, 26.8%; con 1%, 14.7%. Por eso el bot opera en los mercados contra dólares de Bitso (0.36% de comisión) y no contra pesos (0.78%).

**Acciones y ETFs, 2010 a hoy** (costo 0.05%)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Rotación táctica entre 20 ETFs | 4.5% | 0.53 | −17% |
| **60/40 SPY/IEF (lo que usa el bot)** | 9.9% | 1.00 | −22% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% |

La misma lógica que funciona en cripto **no funcionó en acciones**: su timing no se distingue del azar (p = 0.34). Por eso el bloque de acciones queda en 60/40 pasivo. La táctica sigue disponible (`strategy: tactical`), pero no está recomendada.

**Multi-mercado (materias primas, divisas, bonos y bolsas en 19 ETFs), probado el 25-sep-2026:** perdió 1.4% anual de 2012 a hoy y falló los cinco criterios declarados antes de la prueba; la versión con rebalanceo mensual dio 3.1% anual y tampoco pasó. Queda apagado. Detalle en `reports/multi_market_informe.md`.

**Combinado 30% cripto / 70% ETFs (2021 a hoy):** 18.2% anual, caída máxima −27%, 24% de probabilidad de perder en un periodo de 12 meses. La racha más larga sin recuperar el máximo fue de 835 días.

## Qué tan real es el simulado

- **Criptos:** cada orden simulada se llena contra el libro de órdenes real de Bitso en ese momento: comisión real (0.36%), diferencial real y profundidad real. Si no hay suficiente oferta, se llena más cara o en parte. Solo el dinero es ficticio.
- **Acciones:** con llaves de Alpaca paper, las órdenes van a esa cuenta de práctica, que las ejecuta con precios reales del mercado. Sin llaves, se simulan al cierre con 0.05% de deslizamiento.
- **Cada operación registra su costo real** (`cost_bps` en `state/trades.csv`) y el tablero muestra el promedio contra lo que supone el backtest.

## ¿Y en tiempo real?

Se probó el 26-sep-2026 con velas de 1 hora de 2020 a hoy y cinco criterios declarados antes de correr la prueba (`reports/tiempo_real_preregistro.md`). Ninguna variante pasó; detalle en `reports/tiempo_real_informe.md`.

| Cada cuánto revisa y opera | Rend. anual* | Caída máxima* | Costo al año* |
|---|---:|---:|---:|
| **Una vez al día (lo que hace el bot)** | 21.6% | −50% | 12% |
| Cada 4 horas | 12.9% | −51% | 26% |
| Cada hora | −8.3% | −71% | 43% |
| Vigía: opera una vez al día; freno y kill switch cada hora | 22.5% | −50% | 12% |

\* Sin kill switch, para ver el efecto en todo el periodo. Con el kill switch de 45%, las cuatro lo tocan entre 2022 y 2023. El vigía no fue significativamente mejor que el diario (bootstrap 65%, placebo p = 0.22).

La señal es de días (promedios de 20 a 200), así que revisarla cada hora casi no cambia qué comprar. Lo que sí cambia es cuánto se opera, y cada operación en Bitso cuesta 0.45%. Por eso el bot **revisa** cada hora y **opera** una vez al día.

Otro hallazgo de esta prueba: con las criptos que Coinbase y Bitstamp tenían en cada fecha (SOL, ADA, DOGE y AVAX llegaron en 2021, NEAR en 2022), la misma regla habría caído 50% y el kill switch de 45% se habría activado en junio de 2023. La peor caída de la investigación principal (−42%) no es un piso.

## Riesgo, en números

Con $1,000 USD en cada bloque, simulando 12 meses a partir de pedazos del periodo 2021–2026:

| | Peor 5% de los casos | Mediana | P(terminar con pérdida) | P(caída >30% en el camino) |
|---|---:|---:|---:|---:|
| Cripto táctico | $719 | $1,227 | 28% | 20% |
| BTC comprar y aguantar | $450 | $1,145 | 41% | 81% |
| 60/40 | $945 | $1,104 | 13% | 0.1% |

## Candados de seguridad

- **Simulado por defecto.** El dinero real exige tres cosas a la vez: `mode: live` en `config.yaml`, la variable `CONFIRMO_DINERO_REAL=si` y las llaves del broker.
- **Capital máximo por bloque** (`capital`). El bot nunca maneja más que eso, aunque tengas más en la cuenta.
- **Freno por caída:** la exposición baja de forma gradual si el bloque cae más de 10% desde su máximo de 6 meses (solo en el bloque táctico).
- **Kill switch:** si el bloque cae 45% (cripto) o 25% (acciones) desde su máximo, vende todo y se apaga hasta que lo rearmes a mano. La peor caída histórica de la estrategia cripto, con costos reales, fue 42%, y con otro universo de monedas llegó a 50%: es probable que algún día se active. La revisión de cada hora avisa en el tablero cuando faltan 5 puntos.
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
- *Cripto (Bitso):* convierte MXN a USD dentro de Bitso (ese cambio es un mercado contra pesos: paga 0.78% de comisión una vez). Crea una llave de API con permisos de **ver saldo y operar**, sin retiros, y agrega los secrets `BITSO_API_KEY` y `BITSO_API_SECRET`.
- *Acciones:* Alpaca acepta cuentas reales de muchos países, pero no publica si México está incluido; confírmalo con su soporte. Si no, la alternativa es Interactive Brokers (requiere agregar un conector).
- Ajusta `capital` en `config.yaml` a lo que aceptes perder. Cambia `mode: live` y crea la *variable* (no secret) `CONFIRMO_DINERO_REAL` con valor `si`.
- Para volver a simulado basta con borrar esa variable.

## Uso local

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q -W ignore                         # 54 pruebas
python -m lab.research_multi --refresh                # investigación completa (~2 min)
python -m lab.bot                                     # corrida del día, simulada
python -m lab.bot --replay 365                        # el bot re-juega un año y se compara con el backtest
python -m lab.bot --status
python -m lab.bot --reset-kill-switch crypto
python -m lab.realtime --once                         # revisión en tiempo real (valúa y avisa)
python -m lab.research_rt                             # prueba de operar cada hora / 4 horas / vigía (~20 min la primera vez)
```

## Tiempo real 24/7 en un servidor (opcional)

GitHub revisa cada hora, que alcanza para una estrategia diaria. Si quieres revisiones cada 5 minutos, necesitas una máquina siempre prendida (un servidor pequeño cuesta unos US$5 al mes):

```bash
git clone https://github.com/MarioB19/trading-lab && cd trading-lab
docker build -t trading-lab .
docker run -d --restart=always -v "$PWD:/app" trading-lab \
  python -m lab.realtime --loop --every 300 --git-push
```

`--git-push` sube `state/` al repositorio después de cada revisión para que el tablero lo vea; el servidor necesita permiso de escritura en el repositorio. Si usas el servidor, quita la línea `- cron: "7 * * * *"` de `.github/workflows/daily.yml` para que no escriban los dos a la vez. Aun así, con `action: observe` el servidor solo vigila: las compras y ventas siguen siendo una vez al día.

## Estructura

| Archivo | Qué hace |
|---|---|
| `src/lab/portfolio.py` | Estrategia de portafolio: tendencia, momentum, paridad de riesgo, volatilidad objetivo, freno y simulación |
| `src/lab/research_multi.py` | Validación: walk-forward, placebo, bootstrap, Sharpe deflactado, costos, Monte Carlo |
| `src/lab/bot.py` | Bot diario por bloques, candados y archivos para el tablero |
| `src/lab/realtime.py` | Revisión en tiempo real: valuación a precio de mercado, caída, señal provisional y avisos |
| `src/lab/research_rt.py` | Prueba pre-registrada de operar cada hora, cada 4 horas o con vigía (velas por hora) |
| `src/lab/brokers.py` | Simulado interno, Alpaca (paper/real) y Bitso |
| `src/lab/data.py` | CoinMetrics, Yahoo Finance y exchanges vía ccxt |
| `src/lab/research.py`, `btc_bot.py` | El estudio original de BTC solo (`reports/informe.md`) |
| `state/` | Estado del bot, operaciones (`trades.csv`), capital diario (`equity.csv`), foto diaria (`snapshot.json`) y foto de cada hora (`live.json`, `live_equity.csv`) |
| `config.yaml` | Todo lo ajustable |

## Limitaciones

- El pasado no garantiza el futuro. Los años 2021–2026 incluyen un mercado alcista fuerte en cripto.
- La lista inicial de criptos se hizo en 2026. Incluye monedas que se desplomaron, pero queda algo de sesgo de supervivencia.
- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.
- No modela impuestos (lleva registro para el SAT y consulta a un contador), tipo de cambio MXN/USD ni la quiebra de un exchange.
- GitHub Actions puede retrasar o saltarse corridas programadas. La revisión de cada hora pone al día la corrida diaria, y la estrategia es diaria, así que unas horas de retraso no cambian nada.
