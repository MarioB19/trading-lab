# Auditoría diaria de la arena

Solicitada por Brandon el 4-oct-2026 para comparar día a día las cuatro carteras.
Es una vista de solo lectura; no cambia señales, reglas, tarifas, capital ni
órdenes. Reutiliza el historial SQLite completo, sin el muestreo de la gráfica
ni los límites de 250 operaciones / 100 decisiones del resumen general.

## Cálculo

- Días civiles en `America/Mexico_City`; el día actual se identifica en curso.
- Resultado neto: última valoración del día menos la última del día anterior.
  Primer día: US$1,000 por cartera. No hay aportaciones/retiros en esta arena.
- Comisiones según fecha de cada fill, ya incorporadas al patrimonio: no se
  descuentan otra vez. Resultado realizado: suma del campo realizado de ventas;
  cambio abierto: resultado neto diario menos resultado realizado diario.
- La última valoración tiene hora visible; no se presenta como precio exacto
  de medianoche. Un día sin observaciones devuelve resultado/desempeño nulos,
  no ceros. Si falta todo el día anterior, el siguiente no atribuye una ganancia
  de varios días a una sola fecha.
- Caída máxima del día desde el mayor patrimonio observado, incluyendo apertura
  conocida. Se usan todas las valoraciones disponibles; no es una cota de pérdidas.
- Cobertura de datos: fracción de la ventana con una captura no más vieja de 90s.
  La ventana inicial comienza en la primera observación del experimento, no a
  medianoche; se etiqueta inicio parcial. No equivale a uptime del proveedor.
- Reporta errores y eventos de cada fecha (últimos 100 eventos, últimos 5 visibles;
  totales sin recorte). No reconstruye precios, fills ni decisiones durante huecos.

## Acceso y verificación

`GET /api/daily-audit` devuelve resumen y comparación por día; cache 30s para no
releer todo el histórico por cada actualización visual. SQLite se abre mode=ro,
query_only y en una transacción consistente. `GET /api/daily-audit.csv` exporta
una fila por estrategia y día, incluyendo banderas de datos faltantes/parciales.
`GET /api/integrity` audita hashes de todas las capturas/velas y saldos contra fills;
un fallo contable/hash devuelve 409. Todos los endpoints requieren autenticación.

La conciliación diaria reconstruye efectivo, BTC y fees desde TODOS los fills y
comprueba identidad del resultado. El botón de integridad añade hashes; muestra
hora y tamaño del corte verificado. No demuestra ejecuciones reales ni rentabilidad.

## Actualización del runtime congelado

Origen autorizado: `4ac103b6f3c23e5b0244e6575539602ad9259fa5`. Se conserva intacto
cada archivo de ejecución y cálculo; `arena_reporting_upgrade` comprueba sus
hashes. Solo cambian API, panel, nuevos lectores y el comando de actualización.
La prueba Git de la nueva imagen mantiene el preregistro y plan originales.

1. Crear paquete limpio y probado. Respaldar la base viva y conservar lectura previa.
2. Desactivar con `lab.arena_hosted deactivate` y comprobar que no exista worker.
   Quitar el marcador también impide reactivación automática al instalar la imagen.
3. Subir nueva imagen al mismo servicio y volumen; mantener el marcador ausente.
4. `python -m lab.arena_hosted upgrade-reporting --cutover-confirmed`: exige lock
   disponible, origen exacto, protocolo igual y código de trading sin cambios.
   Conserva fecha de inicio, posiciones, capital e historial. Solo cambia proof,
   agrega evento con prueba anterior y cancela cotizaciones antiguas.
5. Conciliar filas/saldos antes y después; activar con el comando habitual.
6. Verificar ciclo sano, una sola instancia, HTTPS, auditoría y CSV. Descargar
   backup posterior y restaurar localmente inactivo; conservar evidencia.

No iniciar la copia local como worker, no reiniciar el periodo de observación,
no cambiar estrategia por este informe. Sin push ni llaves privadas de exchange.
