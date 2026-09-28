# Preparación vigente para conectar Trading Lab

Fecha: 2026-09-27 CDMX / 2026-09-28 UTC. Solicitud de Brandon: conservar sólo lo que funciona, mejorar procedimientos y dejar preparado para conectar. Estado actual: validación local de la entrega simplificada; GCP y cuentas privadas todavía sin conexión.

## Alcance conservado

- Cripto táctica diaria, hasta 5 activos y volatilidad objetivo 40%; ETFs SPY/IEF 60/40. Configuración, capital, modo paper y estado original intactos.
- Runtime único, SQLite transaccional, conciliación, panel privado, backup/restauración y alertas preparadas.
- Consulta GET de cuentas separada, con identidad estable; no adopta inversiones ni permite operar por conectarla.
- Imagen operacional `runtime` con perfil `operational-paper`, sin planes ni informes de investigación. El instalador verifica identidad del release y deja el worker apagado.

La candidata agresiva se retira por sus siete criterios fallidos. Se conservan **56 archivos de evidencia sin cambios**: planes, preregistros, corridas v1/v2, base, capturas, backups, restore y atestación f6. Hash del inventario antes/después: `3f58d2acd13d104884c6d0aef2910ede0fb2892900095f5c63fe6d7a9e9af8cf`. Su entrada de programación termina antes de Docker; no se continúa su observación. La imagen f6 y [su entrega](DELIVERY_ACCEPTANCE.md) quedan como historial.

## Procedimiento único

Usar [CONNECT_CHECKLIST.md](CONNECT_CHECKLIST.md) para los inputs y las decisiones GO/NO GO; [GCP_RUNBOOK.md](GCP_RUNBOOK.md) contiene los comandos. Primero GCP con los simuladores existentes y sin llaves privadas. Después, en una fase independiente, [consulta de la cuenta](REAL_ACCOUNT_RUNBOOK.md). Alta de broker paper externo y administración real requieren migración y validación adicionales.

Se necesita confirmar proyecto GCP, facturación, créditos y canal de alertas al conectar. Correo previsto `brandonmuro.work@gmail.com`; presupuesto máximo US$60/mes. La base estimada vuelve a US$32.11/mes al excluir el disco experimental por defecto; objetivo de trabajo US$35–45 antes de impuestos/créditos. No se ha comprobado el saldo de créditos ni creado recursos.

El procedimiento exige un único escritor, copia final del estado GitHub, importación conciliada, restauración desde GCS, lectura del digest instalado, primer ciclo y ciclo posterior, alertas recibidas y medición de consumo. `/healthz` 200 sólo prueba servidor vivo; antes de migrar, `/readyz` 503 es correcto. No se interpreta una copia del piloto como saldo actual de un broker.

## Evidencia de la versión

La validación y la imagen nuevas se registran aquí al terminar. Los resultados del release anterior no se atribuyen automáticamente al código modificado.

## Límites de aceptación

La preparación local no demuestra IAM, cuotas, conectividad a proveedores desde la región, entrega de avisos ni recuperación remota. Al conectar se ejecutan esas comprobaciones; no se activan todos los servicios para averiguar después si el corte fue correcto.

La regla vigente supera a una candidata específica; no prueba ser el mejor algoritmo ni garantiza rentabilidad. Se observará al menos cuatro semanas del piloto estabilizado. La variante rechazada no necesita ni obtiene aprobación por continuar otros 28 días. Las inversiones existentes siguen fuera del bot y la activación real permanece manual, fuera de esta entrega.
