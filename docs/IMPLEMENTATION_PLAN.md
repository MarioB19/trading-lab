# Trading Lab · Plan de implementación y conexión GCP

Responsable: Brandon. Cuenta que se usará **cuando se autorice conectar**: `brandonmuro.work@gmail.com`.
Presupuesto máximo indicado: **60 USD/mes**. Estrategia y dinero: **paper exclusivamente**.

## Qué se prepara ahora

GitHub conserva código y validación; Artifact Registry guarda imágenes y GCP hospeda un ejecutor, el estado transaccional, el panel privado y los respaldos. La infraestructura se describe en Terraform; no se crean recursos ni se autentica la cuenta durante la preparación.

La rama de trabajo es `codex/gcp-platform`. Las correcciones no activan nuevas señales de inversión. Las capacidades experimentales se registran y prueban por separado; los informes históricos no representan automáticamente el motor corregido.

| Etapa | Entregable verificable | Condición de cierre |
|---|---|---|
| Motor | Propiedad por bloque, diario de órdenes, conciliación y reintentos seguros | Pruebas de aceptación incierta, parciales, reinicio y salida fallida |
| Persistencia | SQLite WAL, transacciones, importación explícita y exportaciones derivadas | Estado y operaciones consistentes después de fallos simulados |
| Operación | Ejecutor único paper, salud, API/panel de lectura | Dos escritores excluidos; datos viejos/errores visibles |
| Recuperación | Backup consistente, manifiesto SHA256 y restore desactivado | Restauración conserva posiciones, efectivo e historial |
| GCP | Terraform, VM, disco, IAM, IAP, Artifact Registry, GCS y monitoreo | Validación local; plan real y pruebas remotas pendientes de conexión |
| Investigación | Walk-forward causal, p-values finitos, manifiestos y preregistro | Pruebas sintéticas; ninguna variante activada por rendimiento reciente |
| Migración | Importación congelada y cambio a un único runtime | GitHub deja de ejecutar antes de activar GCP |
| Paper sostenido | Operación observada de la versión estabilizada | Mínimo cuatro semanas e incidentes críticos resueltos |

## Cuando Brandon diga “conéctalo con mi cuenta de Google Cloud”

1. Leer este plan, `GCP_RUNBOOK.md`, `GCP_ARCHITECTURE.md`, las reglas y la evidencia de validación. Revisar cambios pendientes y conservarlos. No confundir código probado con despliegue.
2. Con autorización vigente, iniciar autenticación oficial para `brandonmuro.work@gmail.com`. Nunca pedir contraseñas o tokens por chat. Comprobar la cuenta activa: el correo no identifica un proyecto ni una cuenta de facturación.
3. Consultar proyectos y facturación accesibles. Elegir un proyecto dedicado existente o crear el acordado; registrar **project ID, billing account ID, región y zona**. Verificar alcance, saldo y vencimiento de créditos. Esos valores no se han inventado ni aprovisionado en esta preparación.
4. Cerrar una versión revisable: ejecutar pruebas, revisar diff y resolver autorización de commit/push si no existe. Publicar imagen por digest; no desplegar una etiqueta mutable `latest`.
5. Preparar backend Terraform y valores de proyecto. Revisar `terraform plan`, recursos, permisos y costo: una VM sin alta disponibilidad, disco de estado, IP de egreso, IAP, repositorio de imágenes, bucket privado, métricas y alertas. No añadir Cloud SQL/GKE ni servicios costosos sin justificar el presupuesto.
6. Aplicar infraestructura con ejecutor **desactivado**. Acceder al panel por IAP/SSH. `/healthz` debe responder; `/readyz` debe indicar que falta migración. Ese es el estado correcto inicial.
7. Mantener vacías las referencias de credenciales durante el primer corte del simulador interno. Si después se incorpora Alpaca paper, Brandon gestiona sus llaves manualmente y se realiza una migración independiente con identidad/propiedad explícitas. Añadir llaves no traslada posiciones ni permite adoptar inversiones existentes. Los cambios de capital en brokers externos también requieren una migración contable separada; el simulador interno conserva sus aportaciones/retiros.
8. Hacer el corte del runbook: apagar todos los disparadores anteriores, esperar procesos en curso, congelar/exportar estado, verificar checksums, importar y conciliar. Conservar una copia original recuperable.
9. Activar solo GCP. Verificar digest instalado, configuración paper, lock, velas, saldos, órdenes, fills, costos, heartbeat y logs. Leer el panel desde la instancia; que Terraform termine no basta.
10. Probar respaldo, descarga y restauración en destino aislado sin activarlo. Probar pausa, reinicio y rollback sin dos escritores. Confirmar recepción de alertas autorizadas y consumo medido.
11. Registrar inicio de paper estable, revisión semanal y revisión de cuatro semanas. Una estrategia nueva necesita su propia ventana. Conectar GCP no habilita dinero real.

## Evidencia que debe quedar al conectar

- Commit revisado → imagen/digest construido → digest instalado → estado observado.
- Proyecto, zona, nombres de recursos y versión Terraform, sin secretos.
- Plan aplicado y costo medido frente al límite de 60 USD.
- Corte horario del último escritor GitHub y primer ciclo GCP.
- Conteos importados, hashes de origen y conciliación de efectivo/posiciones.
- Una orden paper con intención, identificador, fill y asiento, o constancia de que no correspondía operar.
- Backup restaurado con checksum e integridad SQLite comprobados.
- Heartbeat fresco y alertas probadas; último error y pendientes visibles.
- Pendientes separados: broker paper externo, duración observada y experimentos.

## Algoritmos e investigación

Se mantiene la estrategia activa. La primera investigación debe replicar universo, horario, mínimos y costos operables. Después: rebalanceo por costos, Ledoit–Wolf y diversificación de baja frecuencia. `RESEARCH_PROTOCOL.md` documenta los gates. Un borrador no autoriza una corrida: el preregistro debe existir en un commit anterior y corresponder exactamente a los parámetros ejecutados.

## Estados distintos de entrega

“Implementado localmente”, “validado con pruebas”, “desplegado en GCP”, “conectado a broker paper” y “observado cuatro semanas” requieren evidencia diferente. No marcar los últimos como completos antes de tiempo. Se mantienen los candados de dinero real y la acción manual exclusiva de Brandon.

## Resultado local de esta implementación

136 pruebas Python aprobadas, replay 365 días con diferencia máxima 0.458%, Terraform validado y tres planes mock correctos. Importación/backup/restore conserva el estado histórico. Build Docker pendiente por ENOSPC; GCP y los brokers externos todavía no se verificaron. Detalle reproducible en [VALIDATION.md](VALIDATION.md). Sin commit/push ni conexión a la cuenta.
