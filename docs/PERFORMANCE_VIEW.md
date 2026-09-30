# Capital y ganancias en pesos

El panel operativo muestra MXN por defecto y permite cambiar a USD. La moneda de visualización no modifica posiciones, estrategia, capital ni órdenes.

## Capital de US$1,000

El objetivo de `config.yaml` es **US$500 en cripto y US$500 en ETF**. El panel distingue:

- **Capital objetivo:** la suma configurada de los bloques activos.
- **Capital aplicado:** las bases que el ejecutor ya registró.
- **Ajuste pendiente:** objetivo menos aplicado. No es una ganancia ni una pérdida.
- **Patrimonio:** efectivo más posiciones valuadas, incluyendo resultados acumulados.

En la captura histórica `2a78cf87f5d1bb3d86b491972c5531617430469b`, el capital aplicado todavía era US$1,200. El estado final `b4e9c3c` importado a Railway ya incluye el retiro simulado de US$200 de ETF y conserva US$1,000 de base aplicada. La aportación anterior a cripto y el retiro de ETF permanecen visibles en sus fechas; no se reinició la cartera ni se reescribió el historial.

## Gráfica de balance por día

La línea de saldo muestra efectivo más posiciones a los últimos cierres de cada
día UTC. La línea discontinua muestra el capital aportado neto: base inicial
inferida más los flujos registrados hasta ese día. Los círculos dorados marcan
aportes o retiros. El saldo se mueve con esos flujos; no representa por sí solo
una curva de rentabilidad. El detalle conserva la ganancia diaria neta de flujos.

El selector permite consultar cartera total, cripto o ETF; los últimos 30/90
días del historial o todas las fechas. Se puede seleccionar un punto con ratón
o toque y recorrer los días mediante el control deslizante y el teclado.
Cambiar USD/MXN conserva el día seleccionado. La observación intradía se muestra
en las tarjetas superiores, sin inventar otro cierre diario.

`daily` y `daily.by_sleeve` exponen `equity_mxn`, `capital_usd` y `capital_mxn`.
Cada bloque añade `equity_fx_rate` y `equity_fx_date`: la conversión usa su propia
tasa histórica. En fines de semana, ETF conserva la valoración y tasa del último
cierre, con fecha explícita. El total MXN suma los importes antes de redondearlos;
no multiplica todo por `daily.fx_rate` ni por el dólar actual. Las tasas distintas
hacen que cambios de saldo MXN también reflejen divisas.

Los valores ausentes dejan huecos en la gráfica, no ceros ni interpolaciones.
Si falta un cierre esperado, no se afirma una base de capital cierta después
del hueco. El eje vertical se adapta al rango visible y lo indica en pantalla.

## Ganancias diarias

Para cada bloque y cierre:

```text
resultado USD = patrimonio al cierre − patrimonio del cierre anterior − movimiento de capital
```

Por ejemplo, el 27 de septiembre cripto registra `506.98 − 306.72 − 200 = +0.26 USD`. Los US$200 aportados se muestran por separado. Las comisiones contabilizadas ya están dentro del patrimonio y no se restan dos veces.

El primer resultado usa la base inicial reconstruida a partir del capital aplicado y los movimientos del historial completo. El panel lo identifica; un historial incompleto o una base desconocida no debe interpretarse como una ganancia desde cero. Los días sin cierre y los intervalos con datos ausentes se distinguen de un resultado diario confirmado.

**Pesos por día:** el resultado USD se convierte con el `usd_mxn` registrado para ese cierre. Si falta esa tasa, el importe MXN queda sin dato; no se sustituye por el dólar de hoy. Es una conversión del resultado de trading, no el cambio total del patrimonio en pesos por variaciones cambiarias.

**Resultado acumulado actual:** patrimonio observado menos capital aplicado. Se convierte usando la tasa de la observación, con su fecha visible. Puede diferir de la suma de resultados históricos convertidos con tasas distintas. La variación desde los últimos cierres se muestra aparte; no es otro día cerrado ni debe sumarse nuevamente al resultado acumulado.

## Lectura y procedencia

`GET /api/performance` lee los documentos y todo el historial diario de SQLite en una transacción de lectura. El panel no tiene un botón para modificar capital ni enviar órdenes. `--config` permite indicar el YAML del que se lee el objetivo; por defecto usa `config.yaml` del proyecto, sin cargar `.env`.

La vista local se verifica con una importación independiente del estado publicado, conservando el original y sin activar un worker. Actualizar la página vuelve a consultar esa instancia; no sincroniza por sí mismo GitHub ni acredita una conexión a un broker.

La publicación vigente se identifica en [el procedimiento Railway](RAILWAY_RUNBOOK.md).
Cada actualización congela un paquete nuevo y verifica API, assets y ciclo paper.
La imagen GCP histórica `2a406f6` conserva su identidad y no incluye cambios posteriores.
