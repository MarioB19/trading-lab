# Auditoría del motor de investigación — 3 de octubre de 2026

Alcance: lectura del código y pruebas mecánicas con precios inventados. No se descargaron cotizaciones ni se ejecutó una investigación de rentabilidad. Los ejemplos numéricos de este documento son contraejemplos matemáticos, no resultados de mercado.

La comparación histórica y el observador futuro comparten las señales, pero no prueban todavía la equivalencia de las decisiones con estado ni de su ejecución. Antes de elegir otra estrategia conviene corregir esa base de medición. El control y `rotation_buffer=0.15` deben conservar su evidencia histórica bajo el motor con el que se produjeron; cualquier evaluación con el motor corregido necesita identidad y preregistro nuevos.

## 1. La histéresis depende del inicio de la ventana

**Hallazgo confirmado por lectura.** `target_weights()` inicializa `previous=[]` en cada llamada y reconstruye las selecciones desde la primera fila disponible (`src/lab/portfolio.py:151-163`). Esto hace que `last_only=True` coincida con el cálculo completo **del mismo panel**. No demuestra que dos paneles con distinta fecha de inicio produzcan el mismo último resultado.

El observador llama a `paper_comparison.run_once()`, que llama a `run_sleeve()`/`compute_targets()` con otra captura cada día (`src/lab/paper_comparison.py:183-205`, `442-449`). `fetch_prices()` solicita las últimas 720 velas cripto (`src/lab/bot.py:151-160`). El estado persistido conserva efectivo, posiciones y riesgo; no conserva la selección virtual anterior. Al avanzar el inicio de esa ventana, se vuelve a decidir quién era incumbente desde un punto diferente.

Contraejemplo determinista del selector, sin precios:

| Estado previo | Puntajes actuales A/B | Margen | Selección |
|---|---|---:|---|
| A | 1.00 / 1.10 | 15% | A |
| Vacío | 1.00 / 1.10 | 15% | B |

La diferencia puede persistir indefinidamente si la ventaja permanece debajo del 15%. No es un problema de mirar al futuro; es un problema distinto, de reiniciar una regla con memoria. Además, `ewm()` conserva dependencia del historial de calentamiento; la prueba del selector debe aislarse de ese efecto entregándole los mismos puntajes.

**Corrección propuesta, pendiente:** extraer una transición explícita que reutilice `select_ranked()`: puntajes + elegibilidad + selección anterior → selección nueva. Persistir selección virtual por identificadores de activo, vela de decisión, parámetros e identidad de datos. La reconstrucción debe partir de un ancla congelada y producir el mismo estado que el avance incremental. No reemplazar automáticamente los incumbentes virtuales por posiciones efectivamente compradas: eso sería una regla distinta, especialmente con mínimos o fills parciales, y debe declararse por separado.

**Pruebas sintéticas necesarias:** mismo sufijo de puntajes con estado anterior conocido; avance completo contra avance por bloques con serialización/restauración; recorte de datos anteriores al estado guardado; mismo día repetido sin transición adicional; pérdida de elegibilidad pese a histéresis; identidad estable al reordenar columnas con puntajes no empatados. Definir el desempate por identificador, ya que hoy se resuelve por posición de columna.

`tests/test_rotation_buffer.py` ya comprueba causalidad por prefijo, ausencia de influencia de precios futuros, salida por elegibilidad y equivalencia bot/investigación usando el mismo panel. Esas garantías se conservan, pero no cubren la ventana móvil ni restaurar el estado de selección.

## 2. La banda del simulador histórico puede crear exposición sin efectivo

**Hallazgo confirmado por la fórmula.** En `simulate_portfolio()`, se sustituye cada peso que supera la banda de forma independiente y se dejan intactos los demás (`src/lab/portfolio.py:276-295`). No existe cuenta de efectivo que financie la diferencia.

Ejemplo con precios constantes y banda de 3 puntos:

- Pesos existentes: `[0.34, 0.33, 0.33]`.
- Objetivos: `[0.39, 0.305, 0.305]`.
- La compra de 0.05 supera la banda; las dos ventas de 0.025 no la superan.
- Resultado de sustituir sólo el primer peso: `[0.39, 0.33, 0.33]`, exposición total **1.05**, aunque ambos vectores de entrada sumaban 1.

Esto afecta la capacidad del backtest de representar una cartera sin deuda. No demuestra que el defecto se haya activado en una corrida histórica determinada ni cuantifica cuánto modificó su rentabilidad. El bot limita compras por efectivo y `SimBroker._apply()` limita cantidad por efectivo neto de comisión (`src/lab/brokers.py:55-73`), por lo que compartir `target_weights()` no elimina esta diferencia.

**Implementado, exclusivamente opt-in:** `simulate_funded_portfolio()` en `portfolio.py`. Usa capital en dólares, inventario y efectivo; vende antes de comprar; financia compras proporcionales con el efectivo disponible neto del costo; aplica mínimo por orden; conserva el kill switch; usa señal y precio proxy de t−1 para el retorno t. El simulador legacy y el runtime operativo no se modifican.

El contraejemplo anterior ahora termina con exposición financiada ≤1, sin compra adicional. Las pruebas comprueban también conservación de efectivo y que, con precios planos, capital final = capital inicial − costos efectivamente cargados.

## 3. Los costos porcentuales no capturan los mínimos de una cuenta de US$500

`simulate_portfolio()` usa un retorno proporcional y `turnover * cost`; no recibe capital ni mínimos por orden. El bot combina banda, valor mínimo, efectivo, máximo por orden y disponibilidad del activo (`src/lab/bot.py:430-503`). La comparación paper usa `SimBroker` con capital500 y mínimo5 en cripto; la operación habitual usa un simulador del libro público que también aplica precisión, profundidad y mínimo del mercado (`src/lab/brokers.py:203-263`).

En el bloque cripto, una banda de 2 puntos sobre US$500 equivale inicialmente a US$10. Las salidas a objetivo cero evitan la banda, pero siguen sujetas al mínimo5. Por tanto, un backtest proporcional puede liquidar una posición de US$4 que la implementación deja como inventario. También puede reemplazar una compra no financiable por un peso objetivo instantáneo.

El nuevo simulador modela mínimo en dólares y costos por lado, sin prometer equivalencia con el libro. `cost=.0045` significa que una compra de notional N consume `N * 1.0045`; una venta recibe `N * .9955`. No se carga además otro slippage. Las órdenes menores que el mínimo se omiten; una compra que cae debajo del mínimo después de escalar por efectivo también se omite y deja ese efectivo libre.

**Límites que siguen explícitos:** el precio de t−1 es un proxy, no una ejecución posterior verificable; no hay lotes, precisión por mercado, profundidad, colas maker, fills parciales ni máximo por orden. Las compras proporcionales difieren del orden secuencial del bot. El observador ya publica `operational_execution_equivalence_verified=False` (`src/lab/rotation_observer.py:40-43`); completar 28 días no cambia ese valor.

**Pruebas siguientes para equivalencia:** un planificador compartido de órdenes, fixtures de libro y restricciones por activo; comparar órdenes, costos, efectivo, inventario y estados pendientes del bot contra el evaluador. Un máximo de 2% de diferencia entre curvas no reemplaza estas igualdades contables.

## 4. La política de huecos necesita una sola aplicación y una máscara de antigüedad

`clean()` rellena cinco filas hacia delante (`src/lab/portfolio.py:70-80`). `target_weights()` la llama y después llama a `signals()`, que la vuelve a aplicar. En una serie `[100, NaN × 10]`, la primera llamada rellena cinco ausencias y la segunda extiende ese relleno otras cinco. No es idempotente. La elegibilidad calculada sobre precios originales limita las compras, pero las medias y la volatilidad pueden recibir más imputación de la anunciada.

Además, el motor histórico transforma rendimientos indefinidos en cero (`src/lab/portfolio.py:231`). Con una posición abierta y un hueco prolongado, eso no equivale a una valoración verificada. El observador paper rechaza huecos internos después del primer precio (`src/lab/paper_comparison.py:129-134`), por lo que ambos caminos tampoco comparten la misma política de datos.

**Implementado en el simulador opt-in:** una sola aplicación de ffill limitado a cinco filas; la máscara de precios crudos determina si se puede operar. Si existe inventario y deja de haber un precio de valoración dentro de ese límite, se lanza error. Las ausencias anteriores al listado son admisibles mientras no exista inventario.

**Pendiente en las señales:** conservar datos crudos y máscara de antigüedad; sanear una vez; impedir que otra capa amplíe el límite. Pruebas de huecos de 5/6/10 filas, causalidad por prefijo y mismo resultado ante capas adicionales que sólo consumen datos ya validados. No parchear las señales de una observación congelada en curso.

## 5. ETF: precio ajustado no sustituye un libro de dividendos y splits

`yahoo_daily()` solicita eventos de dividendos/splits y elige `adjclose`, pero devuelve únicamente una serie de precios (`src/lab/data.py:93-122`). `yahoo_last()` devuelve precio de mercado. El simulador de inventario sólo modifica cantidades y efectivo por fills; no registra esos eventos corporativos.

Los rendimientos de una serie ajustada y la evolución de cantidades fijas obtenidas en capturas de distintas fechas son contratos diferentes. Un split 2:1 requiere duplicar cantidad cuando el precio nominal se reduce a la mitad. Un dividendo requiere acreditar efectivo o una política explícita de reinversión. Volver a descargar la historia ajustada no modifica por sí solo el inventario persistido.

**Corrección propuesta, pendiente:** separar `signal_prices` de `execution_prices`/`valuation_prices`; identificar ambos en la captura. Para ETF, introducir eventos corporativos idempotentes o limitar el resultado a una serie de retorno total abstracta que no se presente como ledger de acciones. Fixtures: split2:1 conserva patrimonio sin una operación; dividendo1 reduce precio1 y aumenta efectivo por cantidad; repetir la captura no duplica el abono.

No se determinó en esta revisión si hubo un evento corporativo concreto durante la operación observada ni qué efecto monetario tuvo.

## 6. Identidad de datos y validez histórica del universo

`load_crypto_panel()` combina CoinMetrics y Yahoo y puede reconstruir precios anteriores al primero disponible a partir de capitalización escalada (`src/lab/data.py:221-235`). `BITSO_TRADABLE` es una lista de septiembre de 2026, usada también para seleccionar columnas históricas (`src/lab/research_multi.py:30-32`, `149-154`). Una observación en el proveedor no prueba que ese mercado estuviera operable en Bitso en esa fecha ni con qué costos.

Para el siguiente contrato de datos: etiquetar fuente por activo/intervalo, separar precios observados de proxies, congelar disponibilidad histórica y registrar explícitamente cualquier universo estático condicionado a sobrevivientes. La corrección AVAX ya tiene evidencia y pruebas propias; no convertirla en un permiso implícito para reparar otras series sin evidencia. No se modificaron datasets.

## Evaluador de candidatas: alcance viable

La base reutilizable existe: `PortfolioParams`, `signals`, `select_ranked`, `target_weights` y `drawdown_multiplier`. El evaluador opt-in puede consumir exactamente esos pesos calientes y un ledger nuevo de US$500 al primer retorno de evaluación. El costo inicial debe contabilizarse; no se hereda un portafolio construido durante el calentamiento ni un máximo de patrimonio de ese período.

Contrato mínimo por evaluación:

1. Datos congelados, calendario, universo disponible, señal y precio de ejecución diferenciados.
2. Parámetros completos de señal, política de estado y ejecución incluidos en la identidad de variante y motor. `band`, mínimos y tamaño de cuenta hoy están fuera de `PortfolioParams`; agregarlos sólo a un YAML sin incluirlos en esa identidad no basta.
3. Misma secuencia de decisiones para control y candidata; capital500 cripto +500 ETF; ledger y costos separados por bloque.
4. Métricas netas, flujo de efectivo, rotación de notional, exposición, posiciones no liquidables y fallos de datos. Las observaciones inválidas no se convierten en retornos cero ni se excluyen silenciosamente.
5. Referencias sometidas a las mismas fricciones. El código ya tiene BTC buy-and-hold y SPY/IEF60/40; evitar comparar una referencia ideal sin costo inicial contra una candidata financiada.

Candidatas acotadas para un preregistro posterior, **sin resultados ni selección actual**:

| Variante | Cambio único | Hipótesis verificable |
|---|---|---|
| Control corregido | Misma estrategia con ledger financiado | Medir la regla bajo restricciones de US$500, sin atribuir una corrección contable a alpha. |
| Menor rotación existente | Buffer0.15 frente a0, con semántica de estado definida | Reducir reemplazos sin deteriorar rentabilidad neta y riesgo fuera de muestra. |
| Banda fija alternativa | Banda cripto0.04 frente a0.02, buffer0 | Menos ajustes pequeños compensan la mayor deriva de asignación después de costos y mínimos. |

El perfil `cost-aware-v1` registra banda0.04 y buffers0/0.15 como familia de cuatro configuraciones, más dos referencias. Su preregistro continúa en borrador; no se ejecutó con precios de mercado. No ampliar simultáneamente top_k, activos, volatilidad y frecuencia: impediría atribuir la diferencia a una causa y aumentaría la selección retrospectiva.

## Entrega y pruebas realizadas

- Función opt-in `simulate_funded_portfolio()` y archivo `tests/test_funded_portfolio.py`.
- Pruebas sintéticas: contraejemplo de exposición105%; ventas antes de compras; costos conservados; efectivo distribuido proporcionalmente; mínimos y residuos; kill persistente; desfase de una fila; ausencia de influencia de datos futuros; inicioflat500 con señal calentada; precios prelisting; cotización cruda ausente; error por inventario sin valoración; freno compartido; parámetros inválidos.
- Sin modificaciones a `target_weights()`, `simulate_portfolio()` legacy, reglas operativas, estado SQLite, planes congelados o observador instalado.
- Pendientes: estado de histéresis, saneamiento de señales, eventos corporativos y equivalencia de ejecución. El nuevo ledger mejora la fidelidad contable; no demuestra rentabilidad ni preparación para dinero real.
