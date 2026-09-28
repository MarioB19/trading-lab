# Operación y respaldo de la comparación paper

La comparación control/agresiva usa `comparison.sqlite3`, cuatro bloques con `SimBroker` y capturas comunes de precios. Es independiente del bot operativo, que usa `trading.sqlite3`. Los comandos de esta guía no conectan brokers privados ni autorizan dinero real. La programación GCP descrita requiere instalación posterior; no queda activada por crear un respaldo o restaurarlo.

## Directorios y versión fijada

Separar, por ejemplo:

| Contenido | Directorio del host |
| --- | --- |
| Bot operativo paper | `/var/lib/trading-lab` |
| Comparación v2 | `/var/lib/trading-experiments/aggressive-v2` |
| Bundles de respaldo | `/var/lib/trading-experiment-backups` |
| Prueba de restore | `/var/lib/trading-experiment-restores/ensayo-001` |

Nunca anidar la comparación o sus respaldos dentro del directorio operativo. `paper_ops` rechaza rutas protegidas, enlaces simbólicos, estado de cuentas externas, identidades mezcladas y versiones SQLite desconocidas. `lab.ops` no respalda la comparación: espera otra base y otro protocolo de despliegue.

Antes de iniciar el primer día prospectivo, fijar el SHA final probado. El manifiesto conserva ese código, el plan y la prueba de preregistro; cambiar de versión exige una decisión explícita y no debe reiniciar los contadores para simular continuidad. Un restore conserva íntegramente esa identidad, incluidas las pruebas de construcción si existen.

## Inspección y copia consistente

Comandos desde un checkout instalado, sin cargar `.env`:

```sh
.venv/bin/python -m lab.paper_ops inspect \
  --data-dir /var/lib/trading-experiments/aggressive-v2

.venv/bin/python -m lab.paper_ops backup \
  --data-dir /var/lib/trading-experiments/aggressive-v2 \
  --output /var/lib/trading-experiment-backups/aggressive-v2-20260929T003000Z

.venv/bin/python -m lab.paper_ops verify-backup \
  --backup /var/lib/trading-experiment-backups/aggressive-v2-20260929T003000Z
```

Elegir un nombre nuevo con fecha UTC para cada respaldo. El destino debe no existir. Estos comandos sólo leen la evidencia existente; no descargan precios ni calculan o ejecutan estrategias.

El respaldo toma el mismo `comparison.execution.lock` que el runner, usa la API de backup SQLite —incluye transacciones confirmadas aún en WAL— y copia todas las capturas congeladas de `inputs/`. Comprueba también las capturas de cierres anteriores referenciadas por el historial. No copiar solamente el archivo SQLite de una base abierta con `cp`.

El bundle contiene `comparison.sqlite3`, `inputs/` y `manifest.json`, con hashes SHA-256, identidad, conteos y salud. No necesita `comparison.json`/`.md`: son exportaciones; la base es la evidencia primaria. No incluye el código o imagen ejecutable: conservar por separado la imagen por digest, la atestación y el commit. Los hashes detectan cambios de bytes, no autentican a quien pueda sustituir el bundle completo.

Si el runner conserva el bloqueo, la operación falla sin producir un bundle final. Programar otro intento; no borrar el archivo de lock para forzar acceso. Una interrupción puede dejar un directorio temporal oculto, nunca un bundle final parcialmente publicado. Revisarlo antes de limpiar archivos temporales, conservando todo respaldo verificado.

## Restore sin activación

```sh
.venv/bin/python -m lab.paper_ops restore \
  --backup /var/lib/trading-experiment-backups/aggressive-v2-20260929T003000Z \
  --data-dir /var/lib/trading-experiment-restores/ensayo-001

.venv/bin/python -m lab.paper_ops inspect \
  --data-dir /var/lib/trading-experiment-restores/ensayo-001

.venv/bin/python -m lab.paper_comparison --status \
  --plan configs/experiments/aggressive_v2.yaml \
  --data-dir /var/lib/trading-experiment-restores/ensayo-001
```

El destino debe estar vacío y fuera de cualquier job configurado. Se verifican el original y la copia preparada antes de instalarla; la base se instala al final. `restore.json` registra el hash del manifiesto y `scheduled: false`. No crea timers, servicios ni marcas de activación. El archivo de lock permanece para conservar su identidad; no se elimina al terminar.

Si el proceso se interrumpe antes de instalar la base, queda un destino incompleto que el runner rechaza. Conservarlo para diagnóstico y repetir en otro destino vacío. Un restore fallido nunca justifica cambiar las fechas de observación, borrar huecos o retroceder el reloj.

Comparar identidad, conteos, número de observaciones, salud y capturas con el bundle original. La prueba de restore no debe ejecutar `--once`: verificar que una copia abre y conserva evidencia es distinto de simular otra jornada.

## Preparar una imagen para programación GCP

El runner verifica el preregistro antes de leer datos. En un checkout usa Git limpio y un commit anterior. Una imagen sin `.git` necesita una atestación generada desde ese checkout final; no admite omitir el gate.

```sh
.venv/bin/python -m lab.research_attestation generate \
  --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --output /ruta-fuera-del-repo/aggressive-v2.json
```

Preparar el contexto de construcción a partir del mismo commit y copiar esa prueba a `reports/attestations/aggressive-v2.json` dentro del contexto, sin editar el checkout limpio. Construir con `SOURCE_SHA` igual al SHA completo atestado. La imagen define `TRADING_LAB_BUILD_ID` y `PYTHONDONTWRITEBYTECODE=1`; comprobar digest, UID 10001, plan y hash de prueba antes de instalar. La prueba se rechaza si existe `.git`, el build ID difiere o cambió un archivo cubierto.

Comando del contenedor dedicado, después de sustituir `IMAGEN_POR_DIGEST` por la imagen verificada:

```sh
docker run --rm --name trading-lab-comparison \
  --user 10001:10001 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  --mount type=bind,src=/var/lib/trading-experiments/aggressive-v2,dst=/comparison \
  --entrypoint python IMAGEN_POR_DIGEST \
  -m lab.paper_comparison --once \
  --plan /app/configs/experiments/aggressive_v2.yaml \
  --attestation /app/reports/attestations/aggressive-v2.json \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --data-dir /comparison --fetch
```

El host debe crear el directorio dedicado con escritura para UID/GID 10001. Este contenedor no monta el estado operativo ni archivos de credenciales. Descarga sólo datos públicos. Cada par usa la misma captura por mercado; una repetición del mismo cierre y hash no cuenta otro día ni vuelve a operar. Datos revisados, faltantes o antiguos producen error y requieren diagnóstico, no rellenar precios manualmente.

Plan concreto de instalación, todavía manual:

1. Comprobar reloj UTC/NTP, disco disponible, imagen fijada por digest y ausencia de otro escritor para ese directorio.
2. Crear un servicio systemd `Type=oneshot` cuyo `ExecStart` sea el comando anterior y cuyo arranque no dependa del worker operativo. Usar siempre el mismo directorio y nombre de contenedor; no habilitar reinicios ilimitados que oculten errores.
3. Asociar un timer con `OnCalendar=*-*-* *:15:00 UTC`, `Persistent=true`, `RandomizedDelaySec=0`. La consulta horaria permite reintentar publicación tardía de cierres; el runner decide si hay un par nuevo. `Persistent` no reconstruye días omitidos.
4. Lanzar una primera corrida únicamente cuando el código final y el preregistro estén fijados, leer `--status`, revisar la salud y comprobar que no cambió el bot operativo. Sólo después habilitar el timer manualmente.
5. Programar backup diario a un nombre UTC nuevo, seguido de `verify-backup`. Tratar el conflicto de lock como un reintento pendiente y alertar si no existe un respaldo verificado reciente; no declararlo éxito.
6. Copiar bundles completos a un prefijo GCS exclusivo de experimentos mediante la identidad del host con permisos mínimos de objetos. Comprobar por separado la copia remota; un backup local no demuestra que GCS la recibió. Descargar uno a otro directorio y repetir `verify-backup`/restore antes de dar por probada la recuperación externa.
7. Vigilar gasto y espacio: los respaldos incluyen capturas históricas, por lo que crecen con la observación. Definir retención en GCS sin borrar capturas referenciadas por la base activa. Las alertas de presupuesto no limitan por sí mismas el gasto.

La infraestructura actual del bot no instala por sí sola este timer, sus alertas ni la copia GCS experimental. Son pasos pendientes de despliegue, separados del respaldo ya disponible por CLI. No iniciar programación desde este documento sin la instrucción de instalación de Brandon.

## Panel y alertas

`lab.service` puede leer la comparación con `--comparison-dir` y la corrida histórica congelada con `--research-dir`. Su ruta `/api/comparison` y el panel diferencian histórico y paper prospectivo. El servicio no ejecuta estrategias. Para SQLite en WAL, el lector necesita un montaje que permita los sidecars según la configuración del host, pero su conexión sigue siendo `mode=ro` y `query_only`; nunca concederle credenciales de broker.

Alertar por salida no cero del servicio, `comparison_health.status: error`, última observación que no avance cuando debe existir un nuevo cierre, huecos persistentes, falta de respaldo local verificado y ausencia de copia GCS. Revisar por separado que el timer siga habilitado. Una API accesible o un HTTP 200 no acredita que el simulador esté observando días nuevos.

Conservar las incidencias y los huecos diarios. Contar 28 fechas es insuficiente si faltan decisiones entre ellas; el runner registra discontinuidades y no las borra al reintentar. Completar paper tampoco promociona la estrategia automáticamente, ni revoca un rechazo de la comparación histórica.
