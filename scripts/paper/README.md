# Paquete de programación paper para GCP

Preparado para instalación manual futura; ningún archivo instala servicios, cambia IAM o habilita dinero real. No ejecutar estos pasos en la máquina local de trabajo. Consultar también [PAPER_OPERATIONS.md](../../docs/PAPER_OPERATIONS.md).

El paquete usa únicamente la imagen ya instalada por digest, datos públicos y el `SimBroker` de la comparación. No lee `.env`, Secret Manager, credenciales de broker ni configuración del runtime operativo. Rechaza imágenes con variables de credenciales, un build ID distinto, otro UID o escritura de bytecode habilitada. No descarga imágenes automáticamente.

Rutas fijas del host:

- Montaje persistente dedicado: `/var/lib/trading-experiments`.
- Comparación: `/var/lib/trading-experiments/aggressive-v2`.
- Backups locales: `/var/lib/trading-experiments/backups`.
- Configuración pública de release: `/etc/trading-lab-paper/release.json`.
- Marca de autorización manual: `/etc/trading-lab-paper/aggressive-v2.enabled`, cuyo único contenido es el SHA de código completo elegido.
- Scripts instalados: `/usr/local/lib/trading-lab-paper/{common,run,backup,healthcheck}.sh`.

Después de una instrucción de despliegue, el operador debe:

1. Montar almacenamiento persistente en la ruta indicada, comprobar espacio y crear los directorios `aggressive-v2` y `backups`, propiedad de UID/GID `10001:10001`, permiso `0700`. No reutilizar estado operativo. El primer arranque requiere un directorio de comparación vacío.
2. Instalar los cuatro scripts como archivos propiedad de root, sin escritura de grupo/otros y ejecutables. Instalar los seis archivos `.service`/`.timer` en `/etc/systemd/system/`. Esto se hace manualmente; no hay instalador ni integración automática en startup Terraform.
3. Preparar una imagen atestada desde el SHA final limpio, fijar su digest y cargarla en el Docker del host mediante el procedimiento de entrega existente. Copiar y completar `release.json.example` como `release.json` con sólo sus cuatro campos. El ejemplo incompleto falla cerrado. No añadir secretos ni rutas configurables.
4. Verificar la atestación dentro de la imagen con el comando de `PAPER_OPERATIONS.md`. Iniciar la primera observación **en la imagen atestada**: una base creada con prueba Git local no migra automáticamente al formato de prueba atestada.
5. Crear manualmente la marca de autorización con el SHA exacto y ejecutar `systemctl daemon-reload`. Iniciar una vez `trading-lab-comparison.service`, leer su salida con `journalctl -u trading-lab-comparison.service` y revisar estado/panel. Una consulta de precios fallida no cuenta como día observado.
6. Iniciar una vez `trading-lab-comparison-backup.service`; comprobar `backups/last-verified.json`, verificar el bundle y ensayar restore en un destino vacío usando `lab.paper_ops`. Comprobar `trading-lab-comparison-health.service`. Sólo después habilitar manualmente los tres timers con `systemctl enable --now trading-lab-comparison.timer trading-lab-comparison-backup.timer trading-lab-comparison-health.timer`.

Para detener la programación, deshabilitar los tres timers y retirar la marca manual. Si existe una ejecución en curso, detener el servicio y comprobar que el contenedor finalizó; retirar la marca por sí solo impide arranques posteriores. Nunca borrar locks ni sustituir una imagen para eludir un error de identidad.

`run.sh` usa un nombre fijo de contenedor y el runner adquiere además su lock. Un contenedor anterior o un respaldo concurrente no se sustituye ni se mata para abrir paso a otro. Los errores se registran como JSON con `severity: ERROR`, fase y código de salida en journald. No se instalan alertas nuevas mediante este paquete.

Los tres servicios comparten `/var/lib/trading-experiments/.services.lock`: sólo uno puede iniciar contenedores a la vez. Cada contenedor experimental tiene un límite de 768 MiB y una CPU para convivir con el runtime en la VM de 4 GiB. Si el lock está ocupado, el servicio termina con código 75 y registra `status: pending`, sin actualizar salud o respaldo ni afirmar éxito. Se requiere otro intento; no borrar el lock. El límite es una protección configurada, pendiente de medición en la carga real de la VM; un OOM debe quedar como fallo observable.

`backup.sh` copia SQLite con la API consistente, conserva capturas y verifica hashes sin red. Actualiza `last-verified.json` únicamente después de esa verificación. No elimina respaldos, no sube a GCS y declara `gcs_copy_verified: false`. La réplica externa, su retención, alertas de ausencia y restore desde GCS siguen siendo pasos de despliegue separados; la copia local comparte el disco con la comparación.

`healthcheck.sh` falla si el último intento tiene más de 2 horas, el último par exitoso más de 36 horas, existen huecos/incidencias o no hay respaldo local verificado en 26 horas. Sus fallos llegan a journald; configurar la alerta cloud y comprobar que el propio timer siga habilitado son tareas de instalación. No afirma que una copia esté en GCS.
