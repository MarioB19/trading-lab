# Operación y respaldo de la comparación paper

La comparación control/agresiva usa `comparison.sqlite3`, cuatro bloques con `SimBroker` y capturas comunes de precios. Es independiente del bot operativo, que usa `trading.sqlite3`. Los comandos de esta guía no conectan brokers privados ni autorizan dinero real. La programación GCP descrita requiere instalación posterior; no queda activada por crear un respaldo o restaurarlo.

## Directorios y versión fijada

Rutas del paquete GCP preparado:

| Contenido | Directorio del host |
| --- | --- |
| Bot operativo paper | `/var/lib/trading-lab` |
| Comparación v2 | `/var/lib/trading-experiments/aggressive-v2` |
| Bundles de respaldo | `/var/lib/trading-experiments/backups` |
| Prueba de restore | `/var/lib/trading-experiments/restores/ensayo-001` |

[Terraform](../infra/gcp/main.tf) define un disco experimental `pd-standard` de 10 GiB, separado del operativo. El [bootstrap](../infra/gcp/templates/startup.sh.tftpl) lo monta en `/var/lib/trading-experiments` y prepara `aggressive-v2` y `backups` con UID/GID `10001:10001` y permiso `0700`. No instala ni activa los servicios experimentales. La carpeta de ensayo de restore se crea cuando se solicita esa operación. Backups y restauraciones locales comparten este disco: no son una copia externa.

Nunca anidar la comparación o sus respaldos dentro del directorio operativo. `paper_ops` rechaza rutas protegidas, enlaces simbólicos, estado de cuentas externas, identidades mezcladas y versiones SQLite desconocidas. `lab.ops` no respalda la comparación: espera otra base y otro protocolo de despliegue.

Antes de iniciar el primer día prospectivo, fijar el SHA final probado. El manifiesto conserva ese código, el plan y la prueba de preregistro; cambiar de versión exige una decisión explícita y no debe reiniciar los contadores para simular continuidad. Un restore conserva íntegramente esa identidad, incluidas las pruebas de construcción si existen.

## Inspección y copia consistente

Comandos de mantenimiento desde un checkout instalado, sin cargar `.env`, con permisos del dueño de los datos y los timers detenidos. Para la operación programada en GCP usar el [servicio de respaldo preparado](../scripts/paper/trading-lab-comparison-backup.service). El nombre de bundle siguiente es ilustrativo; sustituirlo por uno nuevo o por el existente que se quiera verificar.

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

## Continuar en GCP la observación local existente

Ya existe un paper iniciado con prueba atestada en `runtime-data/delivery-20260928/aggressive-v2`: una observación, `run_id: d29350d13e8d4a9196ace417bbd5822a`, código `f6c19fdcac943978011b3e096280beb7d0528884`. Su respaldo inicial está en `runtime-data/delivery-20260928/backups/aggressive-v2-first` y su restore comprobado en `runtime-data/delivery-20260928/restored-aggressive-v2`. Son rutas locales de evidencia, no recursos desplegados en GCP.

Para continuar ese mismo experimento, transferir su evidencia; **no iniciar otra base vacía y reiniciar los contadores**:

1. Detener cualquier escritor local antes del corte. Si hubo nuevas observaciones después del respaldo inicial, crear y verificar un bundle nuevo con `lab.paper_ops backup`/`verify-backup`. Conservar el original local.
2. Preparar en GCP la misma imagen de código `f6c19fdcac943978011b3e096280beb7d0528884` y la misma atestación; su hash canónico registrado es `3012f6d1b2e78073948bb085b4105df238de25c501fd4418567bd0e523927186`. No regenerar una prueba diferente, cambiar el código o sustituir el manifiesto para que acepte la base. Fijar el digest de esa imagen verificada en `release.json`.
3. Mantener los tres timers detenidos y la marca manual ausente. Copiar el bundle completo mediante el canal de entrega autorizado a `/var/lib/trading-experiments/backups/aggressive-v2-cutover`, con lectura para UID 10001. Verificarlo después de copiarlo. El destino `/var/lib/trading-experiments/aggressive-v2` debe estar vacío; si contiene otra ejecución, conservarla y resolver la identidad antes de continuar, sin sobrescribirla.
4. Restaurar en ese destino operativo experimental. En el host, con `PAPER_IMAGE` establecido al digest verificado de la imagen f6, estos comandos usan únicamente esa imagen y el disco experimental, sin red ni Git:

```sh
paper_maintenance() {
  docker run --rm --pull never --network none --user 10001:10001 \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --memory 768m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m \
    --mount type=bind,src=/var/lib/trading-experiments,dst=/experiments \
    --entrypoint python "$PAPER_IMAGE" -m lab.paper_ops "$@"
}
paper_maintenance verify-backup --backup /experiments/backups/aggressive-v2-cutover
paper_maintenance restore --backup /experiments/backups/aggressive-v2-cutover \
  --data-dir /experiments/aggressive-v2
paper_maintenance inspect --data-dir /experiments/aggressive-v2
```

5. Comparar con la inspección local previa al corte: mismo `run_id`, plan, código, prueba, saldos, operaciones, capturas y observaciones. Si se usa el bundle inicial, debe conservar una observación. El restore no cambia `created_at`, la fecha de inicio ni los días pendientes, y no activa servicios.
6. Sólo después de esa validación, crear la marca manual del SHA f6 y continuar con una ejecución del [servicio existente](../scripts/paper/trading-lab-comparison.service). El mismo cierre y hash es un reintento sin operaciones duplicadas. Si hubo días sin observación durante la mudanza, conservar los huecos: no rellenarlos retrospectivamente. Validar respaldo y salud antes de habilitar timers. El original local queda conservado y sin escritor.

Una base vacía se usa para un experimento nuevo explícitamente aprobado; no reemplaza la continuidad de este paper ya iniciado.

## Preparar una imagen para programación GCP

El runner verifica el preregistro antes de leer datos. En un checkout usa Git limpio y un commit anterior. Una imagen sin `.git` necesita una atestación generada desde ese checkout final; no admite omitir el gate.

```sh
.venv/bin/python -m lab.research_attestation generate \
  --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --output /ruta-fuera-del-repo/aggressive-v2.json
```

Preparar el contexto de construcción a partir del mismo commit y copiar esa prueba a `reports/attestations/aggressive-v2.json` dentro del contexto, sin editar el checkout limpio. Construir con `SOURCE_SHA` igual al SHA completo atestado. La imagen define `TRADING_LAB_BUILD_ID` y `PYTHONDONTWRITEBYTECODE=1`; comprobar digest, UID 10001, plan y hash de prueba antes de instalar. La prueba se rechaza si existe `.git`, el build ID difiere o cambió un archivo cubierto.

Para el paper existente, conservar la imagen y prueba originales indicadas arriba. Para una nueva ejecución aprobada, fijar su identidad antes del primer día. Una vez instalado el [paquete concreto de scripts y units](../scripts/paper/README.md), completado `release.json` y creada manualmente la marca del SHA autorizado, iniciar el servicio preparado:

```sh
sudo systemctl start trading-lab-comparison.service
sudo journalctl -u trading-lab-comparison.service --no-pager -n 100
```

El [script de ejecución](../scripts/paper/run.sh) usa el directorio dedicado preparado por el bootstrap, con escritura para UID/GID 10001. No monta el estado operativo ni archivos de credenciales y descarga sólo datos públicos. El [preflight común](../scripts/paper/common.sh) limita cada contenedor a 768 MiB y una CPU, fija imagen por digest y serializa los tres servicios mediante un lock de host. Si está ocupado, termina con código 75 y estado `pending`. Cada par usa la misma captura por mercado; una repetición del mismo cierre y hash no cuenta otro día ni vuelve a operar. Datos revisados, faltantes o antiguos producen error y requieren diagnóstico, no rellenar precios manualmente.

Plan concreto de instalación, todavía manual:

1. Comprobar reloj UTC/NTP, disco disponible, imagen fijada por digest y ausencia de otro escritor para ese directorio.
2. Instalar los cuatro scripts y los seis archivos `.service`/`.timer` ya incluidos en [scripts/paper](../scripts/paper/README.md), siguiendo sus rutas y permisos. No recrear las units ni sustituir su `ExecStart` por un Docker directo que omita el preflight o el lock.
3. Restaurar la comparación existente y validar continuidad. El [timer de ejecución](../scripts/paper/trading-lab-comparison.timer) consulta cada hora al minuto 15; el runner decide si hay un par nuevo. `Persistent=true` no reconstruye días omitidos. Mantenerlo deshabilitado durante la restauración.
4. Ejecutar manualmente el [servicio de comparación](../scripts/paper/trading-lab-comparison.service), leer `--status`, revisar la salud y comprobar que no cambió el bot operativo.
5. Probar el [servicio de backup](../scripts/paper/trading-lab-comparison-backup.service), su [timer diario](../scripts/paper/trading-lab-comparison-backup.timer), el [servicio de salud](../scripts/paper/trading-lab-comparison-health.service) y su [timer cada 15 minutos](../scripts/paper/trading-lab-comparison-health.timer). El backup crea un bundle UTC nuevo, lo verifica y actualiza `backups/last-verified.json`; no sube a GCS. Sólo después habilitar manualmente los tres timers. Un lock ocupado es un reintento pendiente, sin marca de éxito.
6. Copiar bundles completos a un prefijo GCS exclusivo de experimentos mediante la identidad del host con permisos mínimos de objetos. Comprobar por separado la copia remota; un backup local no demuestra que GCS la recibió. Descargar uno a otro directorio y repetir `verify-backup`/restore antes de dar por probada la recuperación externa.
7. Vigilar gasto y espacio: los respaldos incluyen capturas históricas, por lo que crecen con la observación. Definir retención en GCS sin borrar capturas referenciadas por la base activa. Las alertas de presupuesto no limitan por sí mismas el gasto.

Terraform prepara el disco experimental y sus directorios; no instala por sí solo estos scripts/timers, sus alertas ni la copia GCS experimental. Esas instalaciones siguen pendientes, separadas del respaldo ya disponible por CLI. No iniciar programación desde este documento sin la instrucción de instalación de Brandon.

## Panel y alertas

`lab.service` puede leer la comparación con `--comparison-dir` y la corrida histórica congelada con `--research-dir`. Su ruta `/api/comparison` y el panel diferencian histórico y paper prospectivo. El servicio no ejecuta estrategias. Para SQLite en WAL, el lector necesita un montaje que permita los sidecars según la configuración del host, pero su conexión sigue siendo `mode=ro` y `query_only`; nunca concederle credenciales de broker.

Alertar por salida no cero del servicio, `comparison_health.status: error`, última observación que no avance cuando debe existir un nuevo cierre, huecos persistentes, falta de respaldo local verificado y ausencia de copia GCS. Revisar por separado que el timer siga habilitado. Una API accesible o un HTTP 200 no acredita que el simulador esté observando días nuevos.

Conservar las incidencias y los huecos diarios. Contar 28 fechas es insuficiente si faltan decisiones entre ellas; el runner registra discontinuidades y no las borra al reintentar. Completar paper tampoco promociona la estrategia automáticamente, ni revoca un rechazo de la comparación histórica.
