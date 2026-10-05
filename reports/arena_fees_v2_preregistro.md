---
protocol_version: 1
status: approved
experiment_id: arena-fees-v2
hypothesis: Corregir el modelo de costos según la tabla pública de Bitso, sin seleccionar señales por sus resultados recientes ni afirmar rentabilidad.
evaluation_window: Solo ejecuciones futuras desde el corte registrado; el tramo corregido inicia su propio contador de 28 días y conserva íntegro el historial anterior.
config_sha256: 5e8a4cf98081dcbbfb39e51a37588f93c45941c9e01de08b830275f4df365b47
variant_ids: [scalping-v1, swing-v1, mean-reversion-v1, market-making-v1]
criteria:
  walk_forward: No se ejecuta ni se afirma una validación de rentabilidad. Cualquier promoción requiere un protocolo independiente y walk-forward fuera de muestra.
  placebo: Pendiente de protocolo y muestra suficiente; ningún diagnóstico de tarifas satisface este criterio.
  bootstrap: Pendiente de muestra prospectiva independiente y corrección familiar; no se reinterpreta el pasado como fuera de muestra.
  cost_stress: Comparar tarifas sobre las mismas ejecuciones registradas, sin reconstruir señales ni asumir fills maker factibles. No equivale a otro portafolio ni a rendimiento alternativo.
  drawdown: Se mantienen frenos, picos, contadores, capital y posiciones existentes; no se reinician riesgos ni pérdidas.
---

# Enmienda de costos — Arena Bitso USD

Brandon solicita «ayudame a implementar eso» el 5-oct-2026, referido al modelo de escalones de 30 días y comparación maker/taker conservando el historial. Esta enmienda declara el alcance antes de ejecutarlo. No registra una señal nueva ni una optimización de estrategia; corrige la contabilidad prospectiva del simulador. No se ejecutan backtests ni se promueve ninguna variante. Permanecen los cuatro intentos originales registrados en SLEEVES.

- Tabla pública congelada en `configs/arena/bitso_fees_v2.json`, hash `5e8a4cf98081dcbbfb39e51a37588f93c45941c9e01de08b830275f4df365b47`. No se consulta ninguna cuenta privada. Son tarifas modeladas, no una certificación de la comisión personal de Brandon. Mercado BTC/USD, dólares digitales.
- Ámbito por estrategia: cada cartera simula una cuenta independiente, sin mezclar efectivo, liquidez ni descuentos. Solo cuentan importes ejecutados (compras y ventas), nunca capital, cotizaciones o intentos. Volumen ajeno previo a la arena se supone cero.
- Ventana móvil `(momento de decisión de ejecución − 30 días, momento]`. Antes de cada fill se suma únicamente volumen ya registrado; el fill actual puede reducir la tarifa del siguiente, nunca la propia. El tiempo de reconocimiento es la captura donde se simula el fill; la hora del trade público se conserva separada. Empates se resuelven por ID contable previo. Se excluyen registros futuros. Los fills anteriores al corte aportan volumen histórico sin reescribir su comisión.
- Límites estrictos `>` como la tabla pública; exactamente en el umbral se conserva la tarifa anterior. La página no especifica todos los detalles del motor privado: esta convención es explícita y conservadora.
- Maker/taker mantienen su clasificación y condiciones actuales. Se cambia exclusivamente la tarifa cobrada y el presupuesto financiable de cada ejecución. La separación mínima de cotizaciones sigue anclada al parámetro original 0.30% + margen; no se estrecha el spread para forzar fills. Señales, tamaños objetivo, cadencias, salidas y frenos conservan sus reglas.
- Cada fill nuevo guarda modelo, hash, tarifa, volumen previo, escalón y momento usado. La auditoría reproduce el cálculo con el ledger previo y detecta discrepancias. El cambio puede afectar saldos y decisiones posteriores por sus costos; no se afirma continuidad científica con el tramo de tarifa fija.
- Migración única desde `7e35212032ab604f1aabdc66d370a706af0685c9`: detener escritor, backup, corte verificable, añadir política al manifiesto y evento, cancelar cotizaciones previas, conciliar y reactivar. No reescribir fills, equity, capital, fecha de inicio, picos ni contadores. Guardar patrimonio al corte y fecha de inicio del tramo corregido.
- Informe: tarifas actuales, volumen 30 días, próximo umbral y desglose de comisiones cobradas. Comparación posterior al corte: costo registrado, costo a tarifa fija original, maker y taker al escalón efectivamente disponible, siempre mismas cantidades y precios. Diferencia de costos no es ganancia garantizada ni backtest de ejecución maker. Antes del corte se muestran costos históricos separados; no se presentan ahorros retroactivos.
- Pruebas artificiales obligatorias: límites, caducidad, causalidad, independencia de carteras, financiación, reinicio/reintento, metadatos por fill, migración con conservación de datos y verificación de tarifas. Suite completa antes de los commits. Paquete limpio con dos pruebas de preregistro previo; datos persistentes y restauración verificadas.

Fuentes: [tabla pública](https://bitso.com/fees?l=en), [tarifas de cuenta autenticada](https://docs.bitso.com/bitso-api/docs/list-fees). Las tarifas reales personalizadas requerirían una consulta privada autorizada por separado.
