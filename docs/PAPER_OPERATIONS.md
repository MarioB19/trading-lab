# Consulta y respaldo del archivo experimental

La comparación control/agresiva usa `comparison.sqlite3`, cuatro bloques con `SimBroker` y capturas comunes de precios. Es independiente del bot operativo, que usa `trading.sqlite3`. Los comandos de esta guía no conectan brokers privados ni autorizan dinero real. La programación de esta comparación está retirada; crear un respaldo o restaurarlo nunca la activa.

## Directorios y versión fijada

Rutas del paquete GCP preparado:

| Contenido | Directorio del host |
| --- | --- |
| Bot operativo paper | `/var/lib/trading-lab` |
| Comparación v2 | `/var/lib/trading-experiments/aggressive-v2` |
| Bundles de respaldo | `/var/lib/trading-experiments/backups` |
| Prueba de restore | `/var/lib/trading-experiments/restores/ensayo-001` |

[Terraform](../infra/gcp/main.tf) permite un disco experimental opcional `pd-standard` de 10 GiB, separado del operativo y deshabilitado por defecto. El [bootstrap](../infra/gcp/templates/startup.sh.tftpl) lo monta en `/var/lib/trading-experiments` y prepara `aggressive-v2` y `backups` con UID/GID `10001:10001` y permiso `0700`. No instala ni activa los servicios experimentales. La carpeta de ensayo de restore se crea cuando se solicita esa operación. Backups y restauraciones locales comparten este disco: no son una copia externa.

Nunca anidar la comparación o sus respaldos dentro del directorio operativo. `paper_ops` rechaza rutas protegidas, enlaces simbólicos, estado de cuentas externas, identidades mezcladas y versiones SQLite desconocidas. `lab.ops` no respalda la comparación: espera otra base y otro protocolo de despliegue.

Antes de iniciar el primer día prospectivo, fijar el SHA final probado. El manifiesto conserva ese código, el plan y la prueba de preregistro; cambiar de versión exige una decisión explícita y no debe reiniciar los contadores para simular continuidad. Un restore conserva íntegramente esa identidad, incluidas las pruebas de construcción si existen.

## Inspección y copia consistente

Comandos de mantenimiento desde un checkout instalado, sin cargar `.env`, con permisos del dueño de los datos y los timers detenidos. No instalar los servicios históricos como parte de la conexión GCP vigente. El nombre de bundle siguiente es ilustrativo; sustituirlo por uno nuevo o por el existente que se quiera verificar.

```sh
.venv/bin/python -m lab.paper_ops inspect \
  --data-dir /var/lib/trading-experiments/aggressive-v2

.venv/bin/python -m lab.paper_ops backup \
  --data-dir /var/lib/trading-experiments/aggressive-v2 \
  --output /var/lib/trading-experiments/backups/20260929T003000Z-a1b2c3d4

.venv/bin/python -m lab.paper_ops verify-backup \
  --backup /var/lib/trading-experiments/backups/20260929T003000Z-a1b2c3d4
```

Elegir un nombre nuevo con fecha UTC para cada respaldo. El destino debe no existir. Estos comandos sólo leen la evidencia existente; no descargan precios ni calculan o ejecutan estrategias.

El respaldo toma el mismo `comparison.execution.lock` que el runner, usa la API de backup SQLite —incluye transacciones confirmadas aún en WAL— y copia todas las capturas congeladas de `inputs/`. Comprueba también las capturas de cierres anteriores referenciadas por el historial. No copiar solamente el archivo SQLite de una base abierta con `cp`.

El bundle contiene `comparison.sqlite3`, `inputs/` y `manifest.json`, con hashes SHA-256, identidad, conteos y salud. No necesita `comparison.json`/`.md`: son exportaciones; la base es la evidencia primaria. No incluye el código o imagen ejecutable: conservar por separado la imagen por digest, la atestación y el commit. Los hashes detectan cambios de bytes, no autentican a quien pueda sustituir el bundle completo.

Si el runner conserva el bloqueo, la operación falla sin producir un bundle final. Programar otro intento; no borrar el archivo de lock para forzar acceso. Una interrupción puede dejar un directorio temporal oculto, nunca un bundle final parcialmente publicado. Revisarlo antes de limpiar archivos temporales, conservando todo respaldo verificado.

## Restore sin activación

```sh
.venv/bin/python -m lab.paper_ops restore \
  --backup /var/lib/trading-experiments/backups/20260929T003000Z-a1b2c3d4 \
  --data-dir /var/lib/trading-experiments/restores/ensayo-001

.venv/bin/python -m lab.paper_ops inspect \
  --data-dir /var/lib/trading-experiments/restores/ensayo-001

.venv/bin/python -m lab.paper_comparison --status \
  --plan configs/experiments/aggressive_v2.yaml \
  --data-dir /var/lib/trading-experiments/restores/ensayo-001
```

El destino debe estar vacío y fuera de cualquier job configurado. Se verifican el original y la copia preparada antes de instalarla; la base se instala al final. `restore.json` registra el hash del manifiesto y `scheduled: false`. No crea timers, servicios ni marcas de activación. El archivo de lock permanece para conservar su identidad; no se elimina al terminar.

Si el proceso se interrumpe antes de instalar la base, queda un destino incompleto que el runner rechaza. Conservarlo para diagnóstico y repetir en otro destino vacío. Un restore fallido nunca justifica cambiar las fechas de observación, borrar huecos o retroceder el reloj.

Comparar identidad, conteos, número de observaciones, salud y capturas con el bundle original. La prueba de restore no debe ejecutar `--once`: verificar que una copia abre y conserva evidencia es distinto de simular otra jornada.

## Experimento retirado de la programación

La candidata v2 falló los siete criterios y Brandon pidió conservar sólo lo que funciona. **No migrar este ensayo a un servicio activo ni habilitar sus timers.** `scripts/paper/run.sh` rechaza toda ejecución antes de cargar configuración o invocar Docker, incluso si se conserva una marca antigua de habilitación.

La única observación local permanece en `runtime-data/delivery-20260928/aggressive-v2`, con `run_id: d29350d13e8d4a9196ace417bbd5822a` y código `f6c19fdcac943978011b3e096280beb7d0528884`. Backup verificado: `runtime-data/delivery-20260928/backups/aggressive-v2-first`. Restore de ensayo: `runtime-data/delivery-20260928/restored-aggressive-v2`. Mantener los datos y la imagen histórica; no reinicializar contadores ni convertirlos en estado operativo.

Los comandos anteriores sirven para **inspección, conservación y recuperación offline**. Un restore histórico permanece sin servicios y sin marca de activación. No se requieren disco experimental, atestación de investigación o timer de comparación para conectar el piloto operativo a GCP. Su almacenamiento opcional queda deshabilitado por defecto. Si alguna instalación anterior lo tuviera, conservarlo y revisar el plan antes de cualquier cambio; retirar una función no autoriza destruir su evidencia.

La imagen histórica f6 y la CLI científica conservadas pueden reproducir código antiguo; el bloqueo del paquete actual no las revoca. No utilizarlas como atajo para reactivar un ensayo retirado. Cualquier hipótesis nueva necesita otro preregistro, revisión y procedimiento propio.

## Panel histórico

`lab.service` puede leer explícitamente el archivo con `--comparison-dir` y la corrida histórica con `--research-dir`. El panel muestra entonces historial de investigación; no recomienda continuarlo ni exige frescura a una observación archivada. El panel operativo habitual omite ambos argumentos y no presenta la candidata.

El servicio no ejecuta estrategias. SQLite en WAL puede necesitar sidecars; el lector abre `mode=ro` y `query_only`. No montar credenciales ni activar un writer para consultar el archivo. Los huecos y las fechas conservados no se borran: forman parte de la evidencia original.
