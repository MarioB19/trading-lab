---
fecha: 2026-10-03
tags: [trading-lab, investigación, rentabilidad, costos]
estado: activo
---

# Rentabilidad con US$1,000: evidencia y siguiente decisión

Investigación documental del 3-oct-2026, zona America/Mexico_City. Alcance confirmado por Brandon: **US$1,000 de capital total, US$500 cripto y US$500 ETFs**. No se ejecutó ningún backtest nuevo ni se modificó una estrategia, cuenta, saldo o modo. Las fuentes públicas se consultaron durante esta sesión; los cortes del bot son los archivos del 3-oct. Se añadió una consulta autenticada de sólo lectura a Railway para verificar uso y suscripción a las 18:58 CDMX.

**Conclusión:** la prioridad es medir el resultado económico completo, corregir la contabilidad y terminar la comparación ya registrada de menor rotación. Todavía no existe evidencia suficiente para afirmar que el bot dará ganancias reales. Con este capital, incluso US$5 mensuales de infraestructura requieren US$60 anuales de resultado de inversión sólo para recuperar ese gasto. Reducir comisiones mejora una cuenta, pero no demuestra por sí solo una ventaja de inversión.

## Base, resultado y evidencia que sí existe

`config.yaml` ya fija 500 + 500. Esto es capital aportado; el patrimonio cambia con las ganancias y pérdidas. Reponer la diferencia hasta mostrar US$1,000 sería una aportación, no una recuperación de la inversión. No reiniciar el historial ni cambiar capital para ocultar la pérdida.

El corte operativo del 3-oct documenta patrimonio US$987.60 y resultado −US$12.40, antes de infraestructura externa. FIFO suma −US$12.39 por redondeo y US$3.6462 de comisiones. Aun agregando esas comisiones al resultado, éste seguiría negativo. Esto descarta que las comisiones, por sí solas, expliquen toda la pérdida, pero no identifica un contrafactual de ejecución sin costos. Fuentes: [revisión del proyecto](../../01%20—%20Operación/🗓️%20Revisiones/🗓️%20Revisión%20—%202026-10-03.md), [métricas derivadas del corte](../../trading-lab-mejoras/reports/revision-2026-10-03/metrics.json).

La prueba registrada `rotation-v2` comparó margen de sustitución 0% frente a 15%, manteniendo top 5 y volatilidad objetivo 40%. En cripto 2021–26-sep-2026 reportó CAGR neto histórico 34.06%/39.37%, caída máxima 39.48%/37.82% y reducción de rotación 19.11%; su motor anterior marcó ocho criterios retrospectivos cumplidos. Estos resultados usan costos supuestos y un universo retrospectivo; no son una estimación de lo que ganarán los US$500 actuales. El histórico ya fue inspeccionado y faltan listados históricos Bitso y equivalencia completa de ejecución. [Resultado registrado](../../trading-lab-mejoras/reports/experiments/rotation-v2/rotation_v2_resultado.md), [protocolo y límites](RESEARCH_PROTOCOL.md).

La observación separada `rotation-paper-v1`, corte 3-oct 18:14 CDMX, tenía cinco fechas y **3.907 días completos**. Control US$997.13, candidata US$998.23: ambas pérdidas. La diferencia de US$1.10 favorece a la candidata, pero US$0.921238 corresponden a la diferencia entre costos modelados (US$2.782945 menos US$1.861707); no es evidencia de una señal superior. Requiere 28 días completos, continuidad y validación de ejecución; `ready_for_human_review=false` y `live_authorized=false`. La primera fecha posible para completar tiempo es 27-oct, 20:28 CDMX; no es fecha de aprobación. [Lectura conservada](../../trading-lab-mejoras/reports/revision-2026-10-03/rotation-paper-readback.json).

La misma serie histórica de la candidata tuvo sólo **43.48% de meses positivos**, peor mes **−17.44%** y **835 días consecutivos bajo su máximo**. Son campos del resultado original (`pct_months_up`, `worst_month`, `longest_dd_days`), no una nueva corrida. Ilustran por qué un CAGR alto no equivale a ingresos mensuales consistentes. [JSON original, `crypto.rotation_comparison.candidate`](../../trading-lab-mejoras/reports/experiments/rotation-v2/20260930T020623Z-3142e39c/multi_results.json).

## Hallazgos de la auditoría científica actual

- Los ocho checks de `rotation_checks` comparan las curvas de parámetros fijos en la ventana histórica. El optimizador walk-forward se calcula aparte y **no participa en esos ocho checks**. La etiqueta histórica `oos` no convierte datos previamente inspeccionados en un holdout nuevo. No describir “8/8” como validación walk-forward independiente de la decisión actual. [Motor conservado, `run_sleeve` y `rotation_checks`](../../trading-lab-mejoras/src/lab/research_multi.py).
- `_block_indices` en el motor que produjo el informe usa `rng.integers(0, n - block, ...)`, cuyo límite superior es exclusivo: omite el último inicio de bloque válido. Requiere corrección técnica y revisión de la validación en una nueva versión científica. Los porcentajes bootstrap de `rotation-v2` siguen siendo resultados del motor anterior; aquí no se recalculan ni se supone cuánto cambiarán. [Implementación conservada](../../trading-lab-mejoras/src/lab/validation.py).
- La selección con histéresis reconstruye incumbentes desde el inicio del panel, mientras el bot solicita un historial móvil de 720 días. Falta comprobar equivalencia cuando se desplaza ese inicio frente a un selector con estado persistente; no se demostró que esto haya provocado una operación incorrecta. Las pruebas de causalidad respecto al futuro y un replay aislado no sustituyen esta prueba. [Selector](../src/lab/portfolio.py), [carga de datos del bot](../src/lab/bot.py).

Estos hallazgos cambian la prioridad: terminar la observación sirve para conservar evidencia prospectiva, pero **no autoriza promover al día 28**. Antes de decidir hace falta una versión científica identificada, validación correcta y evidencia de equivalencia. Los resultados originales y el ensayo congelado deben preservarse con sus límites; corregir el código local no actualiza retroactivamente sus conclusiones.

## El costo fijo cambia la viabilidad de un capital pequeño

Railway publica Hobby a US$5/mes con US$5 de uso incluido. No se suman otros US$5 al uso: si éste es US$7, la factura ilustrativa es US$7, no US$12. [Railway, Pricing Plans](https://docs.railway.com/pricing/plans).

**Verificación de la cuenta, 3-oct 18:58 CDMX:** CLI oficial 5.63.1 y GraphQL autenticado confirman plan Hobby activo y factura pagada del 28-sep 21:31 CDMX, con renglón `priceDollars=5`, cantidad 1. El consumo acumulado atribuible al proyecto es **US$0.468679** en el ciclo 28-sep–28-oct, 21:31 CDMX: memoria US$0.40254, CPU US$0.05527, egreso US$0.00631 y volumen US$0.00456. Son recursos consumidos dentro del uso incluido, no US$0.47 adicionales a US$5. La suscripción es del workspace: atribuirla completa a Trading Lab es un criterio contable explícito, no una medición por servicio. [Evidencia saneada de consultas oficiales](../runtime-data/profitability-20261003/railway-costs.json).

El resumen de uso del CLI devolvió campos `currentBillDollars≈0.47` y `estimatedBillDollars≈0.93`; por sí solos no representan la factura total con suscripción. No se utilizan como costo mensual definitivo, ni se anualizan unos días de consumo. La factura final del ciclo abierto todavía no está determinada por esta lectura. El escenario US$5/mes tiene respaldo en la suscripción actual; si persiste doce meses, supone US$60, no una promesa de precio futuro.

Escenarios aritméticos de costo atribuible al proyecto durante 12 meses, sobre una base constante de US$1,000, sin aportaciones. No son rendimientos esperados ni proyecciones del mercado:

| Gasto mensual | Gasto anual | Resultado anual necesario sólo para pagarlo | Si se imputa sólo al bloque cripto de US$500 |
|---|---:|---:|---:|
| US$5 | US$60 | 6% del capital total | 12% del bloque |
| US$10 | US$120 | 12% del capital total | 24% del bloque |
| US$20 | US$240 | 24% del capital total | 48% del bloque |

Fórmula: `12 × gasto mensual / capital`. El resultado de inversión necesario debe ser **posterior a costos de trading y anterior a este gasto**, sin descontarlo dos veces. Son umbrales simples sobre capital inicial, no CAGR; retiros mensuales del propio portafolio cambian la trayectoria y el capital disponible.

Ejemplo puramente aritmético: US$100 de resultado anual de inversión menos US$60 de hosting dejan US$40 antes de otros gastos e impuestos. US$100 al mes de ingreso con US$1,000 exigirían US$1,200/año, un 120% simple antes de costos; no hay evidencia en este proyecto para presupuestarlo. Ningún CAGR histórico debe convertirse en promesa de ingreso mensual.

Acción prioritaria: mostrar por separado resultado de inversión, costo de ejecución, infraestructura atribuible y resultado económico después de infraestructura. Identificar el cargo de suscripción ya verificado, el consumo medido y la factura final todavía pendiente. Si parte de Railway sirve a otros proyectos, conservar tanto costo marginal como costo atribuible completo y explicar su distribución.

No se recomienda migrar de proveedor por precio nominal. Una alternativa sólo mejora el proyecto si su costo total verificado es menor y conserva un escritor, almacenamiento persistente, restauración, continuidad, autenticación y evidencia. Cambiar hosting ahorra gasto; no cambia la calidad de las señales. Reducir disponibilidad o perder datos para ahorrar puede invalidar la prueba actual.

## Fricción real de Bitso

La tabla pública de mercados contra dólares digitales USDC, identificados como USD, indica en el tramo inicial de volumen a 30 días menor que US$1,000: **maker 0.300% y taker 0.360% por lado**. Los tramos superiores reducen esas tasas; no se supone que todos los fills futuros usen el inicial. [Bitso, Trading fees](https://bitso.com/fees).

Ilustración manteniendo constantes esas tasas y un importe de US$500 en cada lado:

| Compra / venta | Suma de comisiones sobre notional | Comisiones aproximadas, US$500 por lado | Subida de precio que cubre sólo comisiones |
|---|---:|---:|---:|
| Maker / maker | 0.60% | US$3.00 | 0.602% |
| Maker / taker | 0.66% | US$3.30 | 0.662% |
| Taker / taker | 0.72% | US$3.60 | 0.723% |

La última columna calcula `(1 + comisión_compra) / (1 − comisión_venta) − 1`, para igual cantidad comprada/vendida y comisiones cobradas sobre cada importe. La columna de dólares fija el mismo notional a ambos lados, por lo que es una aproximación distinta. Si US$500 incluyen la comisión de entrada, se compra algo menos de US$500. Spread, movimiento durante espera, slippage, FX, redondeos y mínimos pueden añadir fricción. Cambiar de tramo de volumen requiere recalcular; comprar y vender sólo para alcanzar una tarifa menor no constituye una ventaja.

Una orden límite no garantiza comisión maker ni ejecución. Bitso distingue maker por agregar liquidez y taker por consumirla. En el proyecto, esperar como maker puede terminar en fallback taker. Hay que medir tasa de llenado, costo contra precio de decisión y demora; el simulador público no conoce prioridad real de cola. [Bitso, funcionamiento de comisiones y órdenes, modificado 21-sep-2026](https://support.bitso.com/hc/en-us/articles/23866773772308-How-do-fees-and-order-types-work-on-Bitso-Alpha), [validación existente](ROTATION_EXECUTION_VALIDATION.md).

La API documenta `GET /fees` para tarifas de cliente por libro; la consulta exige autenticación. `GET /available_books` describe mínimos, importes, incrementos y estructura por libro. La tabla pública permite escenarios, pero no acredita la tarifa personal. No se accedió a credenciales ni se consultó una cuenta privada en esta investigación. [Bitso, List Fees](https://docs.bitso.com/bitso-api/docs/list-fees), [List Available Books](https://docs.bitso.com/bitso-api/docs/list-available-books).

La banda cripto actual ya es 2 puntos porcentuales de peso: con patrimonio US$500, corresponde a US$10 de desviación antes de otras condiciones. No confundirla con un margen de ganancia de 2%. Tampoco confundir `rotation_buffer=0.15`, una diferencia relativa de puntuación, con una rentabilidad esperada de 15%. Las unidades del score no permiten compararlo directamente con dólares de comisiones.

## Qué significa validar el bloque ETF

Alpaca documenta compras fraccionadas desde US$1, con comprobación `fractionable=true` por activo. Esto hace técnicamente posible un reparto pequeño; no verifica que SPY/IEF estén habilitados en la cuenta de Brandon. Su oferta de comisión cero tiene condiciones y puede conservar cargos regulatorios. No se usa `fee: 0` como prueba de costo económico cero. [Fractional Trading](https://docs.alpaca.markets/us/docs/fractional-trading), [divulgación de comisiones](https://alpaca.markets/disclosures).

Alpaca advierte que paper no reproduce impacto, latencia, prioridad de cola, algunas mejoras de precio, cargos regulatorios ni dividendos. El proyecto además usa actualmente un simulador interno: ni siquiera una prueba interna exitosa acredita ejecución externa. Para ETFs, conciliar precios ajustados, splits y distribuciones sin sumar dividendos dos veces. El observador actual reconoce que usa precios ajustados sin contabilidad independiente de dividendos/splits. [Alpaca, Paper Trading](https://docs.alpaca.markets/us/v1.4.2/docs/paper-trading), [límites del observador conservado](../../trading-lab-mejoras/reports/revision-2026-10-03/rotation-paper-readback.json).

No se presume acceso real desde México: la página oficial de países, fechada febrero de 2026, remite a soporte para confirmar elegibilidad. Esto sigue como pendiente de la cuenta y no impide el trabajo simulado autorizado. No se contactó a soporte ni se abrió o fondeó una cuenta. [Alpaca, Countries available](https://alpaca.markets/support/countries-alpaca-is-available).

## Lo que la literatura apoya y lo que falta demostrar aquí

Moskowitz, Ooi y Pedersen (2012) documentan momentum temporal en 58 futuros/forwards diversificados, con señales de 12 meses. Es una base científica para investigar persistencia de retornos, pero sus instrumentos, diversificación, costos y diseño no validan este ranking de altcoins en Bitso ni permiten trasladar su rentabilidad. [Publicación original y resumen de los autores](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum).

Gârleanu y Pedersen (2013) estudian operaciones con retornos predecibles y costos: la política óptima de su modelo ajusta parcialmente hacia una cartera objetivo y considera cuánto dura la señal. Apoya estudiar rebalanceos menos agresivos; no determina una banda óptima de 2%, 4% o 15% para este bot. [Dynamic Trading with Predictable Returns and Transaction Costs](https://pages.stern.nyu.edu/~lpederse/papers/DynamicTrading.pdf).

Bailey y López de Prado (2014) muestran cómo selección entre muchas pruebas y retornos no normales inflan el Sharpe observado; proponen corregir esos efectos con el Sharpe deflactado. Aplicación: registrar todos los intentos, congelar criterios antes de correr y no elegir una ganadora después de inspeccionar resultados. La corrección parcial existente no elimina las limitaciones de datos ni transforma un histórico visto en datos nuevos. [The Deflated Sharpe Ratio](https://ssrn.com/abstract=2460551), [limitaciones del motor local](RESEARCH_PROTOCOL.md).

La ventaja buscada es un resultado ajustado por costos y riesgo que supere una alternativa simple con evidencia fuera de muestra. Ahorrar un dólar de comisión aumenta el resultado un dólar si todo lo demás permanece igual; no prueba que la señal prediga retornos ni que operar menos preserve las mismas posiciones rentables. Esa segunda parte exige comparación causal y prospectiva.

## Acciones prioritarias y prueba futura propuesta

1. **Cerrar la contabilidad actual.** Actualizar FIFO desde trades vigentes, tratar correctamente el efectivo ETF negativo heredado, conciliar patrimonio/flujos y presentar rentabilidad después de infraestructura sin modificar saldos históricos. Comisiones y slippage ya contenidos en P&L no se restan otra vez. Son correcciones técnicas, no pruebas de una estrategia nueva.
2. **Cerrar los hallazgos científicos y terminar `rotation-paper-v1` intacto.** Corregir y probar el muestreo de bloques en una versión nueva; especificar un criterio walk-forward independiente y probar la histéresis con ventana móvil. No recomputar silenciosamente los resultados antiguos ni modificar el ensayo congelado. Comparar las carteras con mismo capital y calendario; conservar continuidad e incidencias. Una pérdida menor en cuatro días no autoriza promoción. Verificar equivalencia de datos, órdenes, mínimos y ejecución, además del reloj.
3. **Mantener costo real atribuible.** La suscripción US$5 y el uso actual de Railway ya están verificados; falta conciliar cada factura final y fijar la distribución del costo compartido. Desglosar costos de trading observados frente a supuestos. Comparar contra referencias con mismos flujos/ventana y retorno total coherente; BTC para cripto, SPY como referencia descriptiva ETF y 60/40 pasivo idéntico como control del bloque.
4. **Sólo después, preregistrar una comparación pequeña de bandas.** Propuesta concreta para revisión: mantener control margen 0/banda 2pp; candidata ya existente margen 15%/banda 2pp; y una única candidata nueva margen 15%/banda 4pp. El 4pp es una hipótesis de duplicación fijada antes de probar, no un valor calibrado ni un óptimo conocido. Todas conservan universo, top 5, volatilidad, límites, ETFs, horario y salidas de riesgo; la banda nueva no debe bloquear ventas por inelegibilidad, régimen o kill switch. Requiere especificación de código y pruebas causales antes de uso.

El estudio de bandas debe comparar tanto resultado neto de trading como resultado después de hosting, al capital US$1,000 y 500/500. El hosting es común: restarlo por igual no cambia mágicamente qué señal es mejor, pero puede volver no viable la automatización. Se fijarán antes de correr calendario, universo disponible por fecha, datasets, benchmark, manejo de dividendos, modelo de costos, comisiones dinámicas o supuestos explícitos, ventana walk-forward y todos los criterios.

Como punto de partida para el preregistro futuro, conservar los mínimos del protocolo anterior —mejora CAGR neto ≥0.5pp, Sharpe no inferior, caída no peor en >1pp, rotación ≥15% menor, superioridad en ≥60% de años completos, placebo p<0.05, bootstrap emparejado de 2,000 bloques de 30 días con superioridad ≥80% en retorno y Sharpe, y resistencia a 0.60% por lado— y añadir resultado económico después de escenarios US$5/10/20 mensuales. Comparar la nueva candidata contra ambos controles y contar todos los intentos; no relajar criterios si falla. Esos umbrales necesitan revisión previa; este memo no constituye preregistro aprobado ni demuestra que todos puedan satisfacerse.

Antes de cualquier corrida, declarar la variante en el grid compartido, producir IDs/hash exactos, guardar preregistro aprobado en su propio commit anterior al código y ejecutar desde árbol limpio, conforme a [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md). Los años ya examinados sólo sirven de diagnóstico; las conclusiones de la nueva candidata necesitan datos futuros. Ninguna banda nueva puede heredar los días paper de otra configuración.

El resultado posible de una investigación correcta incluye **no operar la candidata** o concluir que el capital y los gastos no justifican el bot. Pasar las pruebas permite revisión humana y al menos cuatro semanas de simulación de esa versión; nunca activa dinero real. Brandon conserva la decisión y la acción manual de pasar a real.

## Trazabilidad

Fuentes internas: `config.yaml`, `AGENTS.md`, `docs/RESEARCH_PROTOCOL.md`, `docs/IMPROVEMENT_PLAN.md`, `docs/ROTATION_EXECUTION_VALIDATION.md`; resultado `rotation-v2` y capturas `reports/revision-2026-10-03` conservadas en el worktree `trading-lab-mejoras`. Los enlaces a esa carpeta reflejan su ubicación real, porque esos artefactos no forman parte del paquete operativo. No se copiaron ni recalcularon resultados.

Fuentes externas: documentación oficial Bitso, Alpaca y Railway y publicaciones de sus autores enlazadas junto a cada afirmación. Aritmética propia reproducible con las fórmulas indicadas; no contiene precios pronosticados, resultados nuevos de mercado ni estimaciones de impuestos. La rentabilidad después de impuestos requeriría datos personales y tratamiento aplicable que no se investigaron aquí.
