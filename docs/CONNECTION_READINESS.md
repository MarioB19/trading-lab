# Preparación vigente para conectar Trading Lab

Fecha: 2026-09-27 CDMX / 2026-09-28 UTC. Solicitud de Brandon: conservar sólo lo que funciona, mejorar procedimientos y dejar preparado para conectar. Estado actual: entrega operacional construida y validada localmente, preparada para iniciar la conexión supervisada; GCP y cuentas privadas todavía sin conexión.

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

Código ejecutable congelado: `2a406f60e3d208eb4f116e3ccf1a84b6d79c7f17`, rama `codex/gcp-platform`, commit local sin push. Los commits documentales posteriores no cambian esa identidad.

| Comprobación | Resultado |
| --- | --- |
| Python 3.13, suite completa | 323 pruebas aprobadas, 30.23 s |
| Terraform 1.10.5 / provider Google 6.50.0 | fmt/init/validate; 4 planes mock y 4 renderizados aprobados |
| Discos e instalación | 9 escenarios de montaje y 36 casos de contrato/configuración/API/preflight aprobados |
| Preflight del SHA y árbol limpio | aprobado; sin autenticación ni consultas cloud |
| Backup descargado en dos archivos | checksum e integridad correctos, verificación en directorio sin escritura |
| Restore aislado | 17 operaciones, 6 registros diarios, 42 intradía, 0 órdenes y documentos contables iguales; worker desactivado |
| Panel base | navegador verificado; healthz 200, readyz 503, comparaciones no configuradas y ocultas |
| Configuración, estado y archivo científico | sin cambios en config/state; 56 archivos preservados |

Evidencia estructurada: [operational_readiness.json](../reports/delivery/operational_readiness.json) y [retirement_inventory.json](../reports/delivery/retirement_inventory.json). El backup ensayado procede de la copia local `runtime-data/delivery-20260928/operational-readonly`, sin nuevos ciclos ni llamadas a mercados. Se conserva en `runtime-data/connection-readiness-20260928/` junto con el restore desactivado. SHA256 del backup: `9e8cbe7c00b6ec7b5557ac07feb4d81c5e424367c14e1438f345a723b49209b8`.

Terraform se ejecutó desde `/tmp/trading-lab-terraform/terraform`; gcloud no está instalado en esta máquina. El preflight local informa esa ausencia y no la presenta como una conexión validada. Al conectar, preparar herramientas oficiales y repetir `--require-tools` con el checkout del SHA elegido. El worker todavía no tiene observación propia, por lo que el 503 del panel es intencional.

Imagen operacional nueva **construida y probada**, Linux AMD64, UID/GID `10001:10001`, perfil `operational-paper`. Digest del manifiesto: `sha256:462fb25fae7f749d99b6f4b867daa33c9e367842988337fea98050cb31644c3c`. Se verificaron los 13 blobs, arquitectura, SHA, comando y entorno. Archivo OCI: 119,261,696 bytes, SHA256 `d8db45b7db51ab0bee7ff3b1456cf7f4a4a5925b9d7e76911b033cc3e0476c7c`.

El smoke ejecutó el helper versionado `scripts/gcp/smoke_runtime.py` en una derivación del runtime exacto, sin red externa, con usuario 10001 y datos exclusivamente sintéticos. Pasaron configuración/importaciones, API/panel de lectura, importación, integridad SQLite, backup, verificación descargada en directorio de sólo lectura, restore desactivado y exclusión de planes/informes de investigación. Pico RSS del proceso: **115,448 KiB (112.74 MiB)**; no es una medición del worker diario completo. La evidencia f6 sólo acredita el release histórico.

OCI, contexto congelado, manifiesto de fuentes y logs se conservan en `/Volumes/KINGSTON/trading-lab-build-y3k2ua9j/artifacts/release-2a406f60e3d2/`. El resumen verificable está en [operational_release.json](../reports/delivery/operational_release.json). Construcción local no equivale a publicación: al subir a Artifact Registry, leer y verificar el digest remoto antes de instalar.

## Límites de aceptación

La preparación local no demuestra IAM, cuotas, conectividad a proveedores desde la región, entrega de avisos ni recuperación remota. Al conectar se ejecutan esas comprobaciones; no se activan todos los servicios para averiguar después si el corte fue correcto.

La regla vigente supera a una candidata específica; no prueba ser el mejor algoritmo ni garantiza rentabilidad. Se observará al menos cuatro semanas del piloto estabilizado. La variante rechazada no necesita ni obtiene aprobación por continuar otros 28 días. Las inversiones existentes siguen fuera del bot y la activación real permanece manual, fuera de esta entrega.
