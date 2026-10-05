# Tarifas por volumen — arena v2

Corrección solicitada el 5-oct-2026. Declaración previa: `reports/arena_fees_v2_preregistro.md`, commit `d26ee0b693bafb607ff030cb709dd25b41887259`.

El costo nuevo usa la tabla pública Bitso USD congelada el 5-oct; calcula volumen de 30 días por cartera (cuentas simuladas independientes). No valida el nivel privado de una cuenta. El nivel baja si caduca el volumen. Umbrales estrictos; el fill actual solo afecta el próximo. Maker mantiene la condición de trade público posterior; las órdenes taker no se reclasifican. El ancho de cotización MM original se conserva. El simulador sigue sin importar llaves privadas ni enviar órdenes.

`arena_fees` centraliza tarifas, causalidad, reporte y auditoría. El presupuesto de compra usa la misma tarifa que se registra. Cada nuevo fill guarda `fee_context`: modelo, hash, tarifa, volumen previo, umbral, último ID previo y tiempo de reconocimiento. La hora del trade público maker sigue en `ts`; reconocimiento es la captura en que el simulador lo contabilizó. Los fills previos aportan volumen según su captura, sin cambiar importe ni comisión histórica. La integridad verifica las tarifas y saldos con el ledger previo; cualquier discrepancia bloquea activación y hace fallar el informe.

## Publicación y corte

1. Suite completa y commit local limpio. `scripts/arena/package.py` genera dos pruebas Git de preregistros anteriores al código. La imagen valida ambos antes de arrancar. Sin push.
2. Backup vivo; `python -m lab.arena_hosted deactivate`; verificar ausencia de `lab.arena`, backup detenido y lectura de todas las tablas. Mantener marcador ausente.
3. Subir bundle con `railway up` al servicio arena existente, conservando volumen y secretos. No usar `redeploy` del manifiesto anterior.
4. Ejecutar `python -m lab.arena_hosted upgrade-fees --cutover-confirmed` como UID10001. Solo admite origen `7e35212032ab604f1aabdc66d370a706af0685c9`, plan original y señales/fuente con hashes intactos. Lock de escritor obligatorio, corte posterior a última captura. Transacción única, reintento idempotente.
5. Conciliar hashes de tablas históricas y carteras (única diferencia: cotizaciones canceladas); activar con comando habitual. No reiniciar balances, costos, inventario, picos o frenos. El manifiesto conserva fecha inicial y añade corte/patrimonio inicial del tramo corregido y ambas pruebas.
6. Verificar versión instalada contra release, una instancia/un escritor, ciclo fresco, `/api/fees`, CSV, auditoría diaria y `/api/integrity` autenticados; acceso sin credenciales devuelve401. Respaldar después y restaurar a destino vacío inactivo, conciliar tablas.

La antigua actualización `upgrade-reporting` debe rechazar esta imagen porque ya cambia el motor de costos. No rebajar ese candado. Si falla antes de migrar, dejar marcador ausente y conservar backup; una reversión de imagen debe conservar la prueba que corresponda a la base. No restaurar backups sobre una base activa ni perder fills posteriores al corte.

## Interpretación del panel

- Costos anteriores y desde el corte separados. El patrimonio acumulado conserva ambos periodos; el contador de observación del nuevo modelo comienza en el corte. Cumplir28 días no valida rentabilidad.
- Comparación desde el corte: tarifa realmente aplicada vs tarifa fija anterior, y todo maker/taker a los escalones disponibles en cada ejecución. Solo cambia la comisión en ese cálculo; no simula nuevas cantidades, señales, financiación o probabilidades de ejecución. No presentar diferencia como rendimiento de una estrategia alternativa.
- `/api/fees` y `/api/fees.csv` son lecturas de una transacción SQLite consistente. Recogen todos los fills; no los250 del resumen. La auditoría secuencial de tarifas usa una ventana acumulada para evitar comparar cada operación contra todo el pasado.
- No fabricar una operación para demostrar el descuento. Si todavía no hubo fills posteriores al corte, mostrar cero y explicación. Validación del motor con datos artificiales y primer fill natural posterior en cuanto exista.

Fuente: https://bitso.com/fees?l=en y https://docs.bitso.com/bitso-api/docs/list-fees. Los gráficos continúan mostrando todo el historial y señalan el inicio del tramo corregido.
