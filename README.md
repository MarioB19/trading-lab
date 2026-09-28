# Trading Lab

Bot de inversión diario para criptomonedas y acciones/ETFs. Cada estrategia se prueba con datos reales antes de operar, y el control de riesgo decide cuánto se arriesga. La operación existente sigue en GitHub Actions hasta realizar el corte documentado. La plataforma GCP está implementada localmente y pendiente de conexión y despliegue.

> Continúa en modo simulado. Los controles de riesgo no garantizan una pérdida máxima ni rentabilidad.

## Integración GCP preparada

- Un ejecutor paper con bloqueo de proceso, contabilidad SQLite WAL y diario durable de órdenes. Reconcilia fills parciales y resultados inciertos antes de volver a enviar.
- Panel privado de lectura con datos de SQLite, frescura del ciclo, órdenes pendientes y respaldos; GitHub deja de ser la base de datos después del corte.
- Terraform para Compute Engine, disco persistente, Artifact Registry, GCS, IAM, IAP, logs, alertas y presupuesto. Instalación por digest, sin activación automática.
- Importación explícita, backup con manifiesto SHA256, verificación y restauración a un destino vacío y desactivado.
- Walk-forward corregido, preregistro exigible, datasets/manifiestos y Ledoit–Wolf opcional para investigación. **La estrategia activa no cambió.**

Cuenta prevista para la conexión posterior: `brandonmuro.work@gmail.com`. No se ha autenticado ni creado ningún recurso. Presupuesto de diseño US$60/mes; objetivo estimado 35–45 antes de créditos. Es una instancia única, sin alta disponibilidad.

Empezar por [plan de conexión](docs/IMPLEMENTATION_PLAN.md), [runbook](docs/GCP_RUNBOOK.md), [arquitectura/costes](docs/GCP_ARCHITECTURE.md) y [evidencia local](docs/VALIDATION.md). El build Docker queda pendiente por falta de espacio del engine local; la validación Python/Terraform no sustituye esa prueba ni el despliegue.

## Qué hace y cuándo

**Tablero:** https://claude.ai/artifact/YLtHeryBpEfs882YJafAGG (privado; lee `state/` con tu conector de GitHub en claude.ai). Para regenerar la versión incluida: `python -m lab.dashboard`.

**Cada hora** (a los :07), GitHub Actions corre la revisión en tiempo real (`python -m lab.realtime --once`): valúa las posiciones al precio de ese momento, mide la caída contra el máximo, calcula qué haría la señal si el día cerrara ahí y avisa si el bloque se acerca al kill switch. No opera (ver "¿Y en tiempo real?"). Antes llama a `python -m lab.bot --if-due`, así que si GitHub se salta la corrida diaria, la hora siguiente la pone al día.

**Una vez al día**, tras el cierre de las 00:00 UTC (18:00 en el centro de México), la corrida diaria (`python -m lab.bot`) opera:

1. Descarga los cierres del día: criptos de Kraken y ETFs de Yahoo Finance.
2. **Bloque cripto (táctico):** de 16 criptos con par en USD en Bitso, elige hasta 5 con tendencia y momentum positivos. Les da más peso a las menos volátiles (paridad de riesgo) y escala el bloque a una volatilidad anual de 40%. Si BTC no está en tendencia, no compra altcoins, y si el bloque cae más de 10% frena la exposición.
3. **Bloque acciones (pasivo por evidencia):** mantiene 60% SPY / 40% IEF y rebalancea cuando se desvía 5 puntos.
4. Revisa los candados. Luego opera: primero las ventas, después las compras.
5. Guarda el estado, las operaciones y la curva de capital en `state/` y hace commit al repositorio. El tablero lee de ahí.

La nueva investigación se dispara manualmente con un preregistro aprobado en un commit anterior. Conserva artefactos separados; no modifica automáticamente los informes históricos ni promueve estrategias. Ver [protocolo](docs/RESEARCH_PROTOCOL.md).

## Qué dice la evidencia

Las tablas siguientes conservan los **informes históricos** de `reports/`; no se recalcularon con el motor corregido. La auditoría detectó parámetros no causales en la ruta optimizada walk-forward y un universo distinto del operable. No se deben interpretar como validación actual de la plataforma GCP ni como autorización de una estrategia. La candidata fija usa una ruta diferente. La primera nueva prueba requiere preregistro y el universo operable completo.

**Criptomonedas, 2021 a hoy** (costo real de Bitso: 0.45% por operación = 0.36% de comisión contra USD + medio diferencial medido en su libro)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Portafolio táctico (lo que usa el bot) | 33.2% | 1.12 | −42% |
| Comprar y aguantar BTC | 20.4% | 0.61 | −77% |
| Pesos iguales en el top 15, rebalanceo mensual | 20.0% | 0.61 | −78% |
| Regla de tendencia solo en BTC | 17.0% | 0.61 | −56% |

- Ninguna de 200 versiones placebo (mismos pesos desfasados en el tiempo) igualó a la estrategia.
- El universo de prueba incluye monedas que se desplomaron (LUNA, FTT, EOS, NEO…) y se eligió con la capitalización de cada día.
- Tiene 67% de probabilidad de ganar más que BTC y 98% de caer menos (bootstrap). Tras corregir por las 43 variantes probadas (36 diarias, 3 de tiempo real y 4 de corto plazo), que gane *más* que BTC no es estadísticamente seguro. Que caiga mucho menos sí lo es.
- Los costos pesan mucho: con 0.30% por operación rendiría 38.9%; con 0.60%, 27.7%; con 1%, 15.4%. Por eso el bot opera en los mercados contra dólares de Bitso (0.36% de comisión) y no contra pesos (0.78%).

**Acciones y ETFs, 2010 a hoy** (costo 0.05%)

| | Rend. anual | Sharpe | Caída máxima |
|---|---:|---:|---:|
| Rotación táctica entre 20 ETFs | 4.5% | 0.53 | −17% |
| **60/40 SPY/IEF (lo que usa el bot)** | 9.9% | 1.00 | −22% |
| Comprar y aguantar SPY | 14.3% | 0.87 | −34% |

La misma lógica que funciona en cripto **no funcionó en acciones**: su timing no se distingue del azar (p = 0.34). Por eso el bloque de acciones queda en 60/40 pasivo. La táctica sigue disponible (`strategy: tactical`), pero no está recomendada.

**Multi-mercado (materias primas, divisas, bonos y bolsas en 19 ETFs), probado el 25-sep-2026:** perdió 1.4% anual de 2012 a hoy y falló los cinco criterios declarados antes de la prueba; la versión con rebalanceo mensual dio 3.1% anual y tampoco pasó. Queda apagado. Detalle en `reports/multi_market_informe.md`.

**Combinado 50% cripto / 50% ETFs, el reparto del bot desde el 27-sep-2026 (2021 a hoy):** 23.7% anual, caída máxima −32%, 26% de probabilidad de perder en un periodo de 12 meses. La racha más larga sin recuperar el máximo fue de 835 días. Con el reparto anterior (30/70) era 18.2% anual, −27% y 24%.

**Estrategias de corto plazo, probadas el 27-sep-2026:** comprar las criptos que más cayeron en 24 horas (reversión) o las que rompen su máximo de 24 o 72 horas (ruptura), con velas por hora. Antes de comisiones, tres de ellas ganaban (de 54% a 128% anual, aunque parte de eso es un rebote entre precio de compra y de venta que no se puede capturar), pero operan cientos de veces al año y con 0.45% por operación todas pierden casi todo. Las dos mejores solo serían rentables con costos por debajo de 0.15–0.18% por operación; Bitso cobra como mínimo 0.30%. Ninguna pasó los criterios. Detalle en `reports/corto_plazo_informe.md`.

## Dólares, pesos e interés compuesto

- **Todo se opera en dólares (USD):** las criptos en los mercados contra dólar de Bitso y las acciones en Alpaca.
- **Tipo de cambio:** cada corrida guarda el USD/MXN del libro de Bitso (donde se cambiarían los pesos), en `state/equity.csv` (`usd_mxn`, cierre de cada día) y en `state/live.json` (el del momento). El tablero muestra el valor en pesos y separa el resultado en pesos en dos: lo que ganó el bot y lo que se movió el dólar.
- **Aportaciones y retiros:** para meter o sacar dinero de un bloque basta con cambiar su `capital` en `config.yaml`. En la siguiente corrida del bloque, el bot lo registra como aportación o retiro (columna `flow` en `equity.csv`), vende o compra lo necesario, y reescala el máximo, el freno y la gráfica para que no cuente como ganancia ni como pérdida. Solo mueve la contabilidad del bot: los depósitos y traspasos reales entre cuentas los haces tú.
- **Interés compuesto (`compound: true`):** cada día el bot reparte el capital completo del bloque, con lo ganado incluido. En el simulado interno la cuenta es el bloque. En una cuenta externa, SQLite conserva una asignación propia por identidad de cuenta, modo y bloque: contabiliza solo fills confirmados y bloquea discrepancias con el broker. No adopta posiciones preexistentes. Las exportaciones JSON son derivadas del ledger. Con `compound: false`, lo que el bloque gane por encima de `capital` se queda en efectivo.

## Qué tan real es el simulado

- **Criptos:** cada orden simulada se llena contra el libro de órdenes real de Bitso en ese momento: comisión real, diferencial real y profundidad real. Si no hay suficiente oferta, se llena más cara o en parte. Solo el dinero es ficticio.
- **Órdenes límite (desde el 27-sep-2026, solo simulado):** cada orden se pone primero al mejor precio del libro como "maker" (0.30% de comisión, sin pagar el diferencial) y espera hasta 2 minutos. Solo cuenta como llenado lo que el mercado negocia atravesando ese precio. Lo que no se llene se opera a mercado (0.36% más el diferencial). La nota de cada operación dice qué parte fue maker, y `cost_bps` mide el costo total, incluido lo que se movió el precio mientras esperaba. Si en 4 semanas el costo medido baja de forma consistente, se considera para dinero real.
- **Acciones:** sin llaves, se simulan al cierre con 0.05% de deslizamiento. Alpaca paper requiere SQLite y una migración separada de identidad y propiedad. Agregar llaves a un estado del simulador interno bloquea el cambio automático. La integración corregida aún necesita una prueba externa controlada.
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
| Cripto táctico | $731 | $1,224 | 28% | 20% |
| BTC comprar y aguantar | $448 | $1,166 | 40% | 81% |
| 60/40 | $945 | $1,104 | 13% | 0.1% |

## Candados de seguridad

- **Simulado por defecto.** El dinero real exige tres cosas a la vez: `mode: live` en `config.yaml`, la variable `CONFIRMO_DINERO_REAL=si` y las llaves del broker.
- **Capital por bloque** (`capital`). El bloque arranca con eso y solo crece o se achica con sus propias ganancias y pérdidas (interés compuesto). Aunque tengas más dinero en la cuenta, el bot no lo toca.
- **Freno por caída:** la exposición baja de forma gradual si el bloque cae más de 10% desde su máximo de 6 meses (solo en el bloque táctico).
- **Kill switch:** si el bloque cae 45% (cripto) o 25% (acciones) desde su máximo, vende todo y se apaga hasta que lo rearmes a mano. La peor caída histórica de la estrategia cripto, con costos reales, fue 42%, y con otro universo de monedas llegó a 50%: es probable que algún día se active. La revisión de cada hora avisa en el tablero cuando faltan 5 puntos.
- **Datos:** no opera con datos viejos. Un precio que salta más de 40% en un día solo permite reducir ese activo. Un activo sin precio bloquea el día en vez de valuarse en cero.
- **No opera dos veces la misma vela.** Si quedan órdenes pendientes en Alpaca, espera.
- **Tope por compra;** las ventas que reducen riesgo nunca se frenan.
- En Bitso usa órdenes límite con tope de precio y cancela lo que no se llene en 20 s.
- Sin apalancamiento, sin cortos y sin retiros: las llaves de API deben crearse **sin permiso de retiro**.

## Puesta en marcha

El piloto existente permanece simulado. La nueva plataforma GCP queda desactivada hasta conectar la cuenta, revisar recursos y ejecutar el corte del [runbook](docs/GCP_RUNBOOK.md).

No agregar llaves de Alpaca durante el traslado del simulador interno: es una migración diferente y requiere evidencia de propiedad. No hay una ruta de activación real autorizada en esta integración; Brandon conserva la decisión y ejecución manual, después de las validaciones técnicas y cuatro semanas de observación de la versión estabilizada.

## Uso local

Python 3.13; dependencias fijadas en los archivos `requirements-*.txt`.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock.txt
pip install --no-deps -e .
python -m pytest -q -W ignore
python -m lab.bot --replay 365 --sleeve crypto
python -m lab.bot --status
python -m lab.research_multi --describe
bash scripts/gcp/preflight.sh
bash scripts/gcp/validate.sh
```

Para ensayar la migración sin operar, importar una **copia congelada** a una carpeta nueva fuera de `state/`, inspeccionarla y abrir el panel:

```bash
python -m lab.ops import-legacy --source state --data-dir /tmp/trading-lab-preview
python -m lab.ops inspect --data-dir /tmp/trading-lab-preview
python -m lab.service --data-dir /tmp/trading-lab-preview --port 8080
```

El panel abre en `http://127.0.0.1:8080/`; el worker permanece apagado. No lanzar un bot local mientras GitHub siga siendo escritor. En GCP, systemd usa `lab.runtime`, que observa cada cinco minutos y opera únicamente cuando corresponde a la regla diaria. No usar `--git-push` ni montar el repositorio como volumen del contenedor. La migración detiene **ambos triggers** legacy, espera corridas en curso e importa el estado definitivo antes de activar un único escritor.

## Cartera experimental agresiva

Se preparó una comparación aislada entre la regla actual y una variante con hasta tres criptos y volatilidad objetivo del 60%. Ambas empiezan con US$1,000 ficticios, mantienen SPY/IEF y conservan frenos y kill switches. La configuración activa no cambia.

El [protocolo y guía](docs/AGGRESSIVE_EXPERIMENT.md) fijan costos, caída máxima y criterios antes de ejecutar. La comparación histórica y el seguimiento diario usan los mismos precios para las dos carteras. **La primera corrida quedó incompleta**: el control detectó 69 cierres ausentes de AVAX en el calentamiento y se detuvo antes de evaluar las carteras. [Resultado y evidencia](reports/aggressive_v1_ejecucion.md). El preregistro y el código ya tienen commits locales; las 203 pruebas sintéticas verifican funcionamiento, no rentabilidad. El paper prospectivo no ha comenzado.

```bash
python -m lab.aggressive_research --describe
python -m lab.paper_comparison --describe
```

## Estructura

| Archivo | Qué hace |
|---|---|
| `src/lab/portfolio.py` | Estrategia de portafolio: tendencia, momentum, paridad de riesgo, volatilidad objetivo, freno y simulación |
| `src/lab/research_multi.py` | Validación: walk-forward, placebo, bootstrap, Sharpe deflactado, costos, Monte Carlo |
| `src/lab/bot.py` | Bot diario por bloques, candados y contabilidad de fills |
| `src/lab/storage.py`, `journal.py` | SQLite transaccional, intenciones y conciliación de órdenes |
| `src/lab/runtime.py`, `ops.py`, `service.py` | Ejecutor paper, importación/backup/restore, API y panel de lectura |
| `infra/gcp/`, `scripts/gcp/` | Infraestructura declarativa, bootstrap, validación y despliegue posterior |
| `src/lab/experiments.py` | Preregistro, procedencia, ledger de experimentos y gates |
| `configs/experiments/aggressive_v1.yaml`, `src/lab/aggressive_plan.py` | Plan fijo, comparación contra la configuración vigente y separación del estado operativo |
| `src/lab/aggressive_research.py`, `paper_comparison.py` | Comparación retrospectiva y seguimiento paper de las dos carteras |
| `src/lab/realtime.py` | Revisión en tiempo real: valuación a precio de mercado, caída, señal provisional y avisos |
| `src/lab/research_rt.py` | Prueba pre-registrada de operar cada hora, cada 4 horas o con vigía (velas por hora) |
| `src/lab/research_short.py` | Prueba pre-registrada de estrategias de corto plazo: reversión y ruptura (velas por hora) |
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
- GitHub Actions puede retrasar o saltarse corridas programadas; esos retrasos pueden cambiar precios y ejecución. La migración a GCP evita depender del scheduler de GitHub, pero una sola VM también requiere monitoreo y recuperación.
- Las correcciones del motor están probadas con escenarios sintéticos. La nueva versión todavía necesita build de imagen, despliegue, prueba de fallos en GCP y observación paper sostenida.
- La simulación maker usa profundidad y transacciones observadas; no conoce prioridad real en la cola. Ningún backtest reproduce íntegramente una ejecución real.
- El Sharpe deflactado global de todos los experimentos históricos aún tiene limitaciones; el registro nuevo mejora trazabilidad futura, no corrige retrospectivamente toda selección anterior.
