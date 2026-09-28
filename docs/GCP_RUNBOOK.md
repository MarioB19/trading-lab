# Preparar, conectar y migrar el piloto simulado

Esta guía deja una secuencia ejecutable para la conexión posterior de `brandonmuro.work@gmail.com`. El trabajo local no autentica esa cuenta, no crea infraestructura, no sube imágenes y no modifica secrets ni dinero real. `mode` permanece como está: paper. Los pasos cloud requieren la conexión y revisión explícitas del operador.

Empezar por la [lista única de conexión](CONNECT_CHECKLIST.md). La candidata agresiva está archivada y no forma parte de este despliegue. El [expediente vigente](CONNECTION_READINESS.md) identifica el código y la imagen que se deben instalar.

## 1. Validación local, sin cuenta

Desde la raíz del repositorio:

```bash
bash scripts/gcp/preflight.sh
python -m pytest -q -W ignore
bash scripts/gcp/validate.sh
docker build --target runtime --platform linux/amd64 --build-arg SOURCE_SHA="$(git rev-parse HEAD)" -t trading-lab:review .
docker run --rm --network none trading-lab:review python -m lab.runtime --help
docker run --rm --network none trading-lab:review python -m lab.ops --help
```

`validate.sh` descarga únicamente plugins Terraform y hace `fmt`, `validate`, planes con proveedor **mock** y comprobaciones locales. No hace `plan` autenticado ni `apply`. Puede recibir `TERRAFORM_BIN=/ruta/terraform`; requiere Terraform >=1.7. El lock de provider se versiona. `.terraform/`, tfstate, tfvars reales y planes están ignorados. Los tests runtime usan directorios temporales; nunca pasar `--data-dir state/` del repositorio.

Antes de una entrega, el árbol debe estar limpio y el SHA debe representar exactamente código probado. Las imágenes construidas durante desarrollo con cambios sin commit solo son evidencia local, no releases autorizadas. Para GCP construir `linux/amd64`; la imagen base está fijada mediante un manifest multiplataforma.

El target habitual es `runtime`, perfil OCI `operational-paper`: sólo aplicación, configuración operativa y panel; no incluye informes ni planes experimentales. El target separado `research` se conserva para auditoría y no se acepta en el instalador operativo. El workflow de publicación ya no pide el preregistro de la candidata rechazada.

La evidencia anterior f6 se conserva en [DELIVERY_ACCEPTANCE.md](DELIVERY_ACCEPTANCE.md). No usar esa imagen histórica para sustituir automáticamente la entrega vigente. Cada release registra SHA probado, digest, pruebas de arranque y respaldo/restauración en [CONNECTION_READINESS.md](CONNECTION_READINESS.md). Los cambios documentales posteriores no obligan a reemplazar un ejecutable ya fijado.

## 2. Conexión posterior y presupuesto

El operador conecta la cuenta prevista y proporciona proyecto existente, billing account y canales Monitoring. No crear un proyecto o cambiar cuenta activa por inferencia. Verificar **Billing → Credits**: saldo disponible, fecha final y servicios cubiertos; el coste de lista sigue existiendo tras acabar los créditos.

La propuesta usa e2-medium, boot 10 GiB, estado 30 GiB, IPv4 estática y backups GCS: base aproximada **32.11 USD/mes**, objetivo **35–45 USD** con consumo moderado. Son precios us-central1, 730 h/mes, antes de impuestos/FX/créditos; detalles en [GCP_ARCHITECTURE.md](GCP_ARCHITECTURE.md). Evitar Cloud SQL, NAT gateway y balanceador en esta fase. Investigar en un entorno separado para no consumir RAM del worker.

El disco experimental opcional (`enable_experimental_storage=false`) queda fuera de la primera instalación. No instalar ni activar los timers de la candidata rechazada. Si un proyecto anterior ya tiene ese disco, revisar el plan y conservar sus datos; no desactivar protecciones para destruirlo.

La configuración Terraform **no inicia sesión**. Cuando el operador haya conectado sus credenciales para Terraform y gcloud por su flujo habitual, preparar `infra/gcp/terraform.tfvars` a partir del ejemplo. Verificar moneda de billing si se habilita el presupuesto USD. Los budgets definidos son alertas al 50/80/100% de 60 USD, calculadas antes de créditos; no un freno automático.

```bash
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp plan -out=review.tfplan
terraform -chdir=infra/gcp show review.tfplan
```

Revisar servicios habilitados, roles IAM, región, IP, discos, eliminación protegida, canales y costes. La primera provisión lleva `image_uri=""`, `source_sha=""`, secrets vacíos y alertas operativas apagadas. Después de aprobar el plan concreto:

```bash
terraform -chdir=infra/gcp apply review.tfplan
```

Conservar y respaldar el tfstate como información sensible. Para trabajo desde más de una máquina, configurar posteriormente backend GCS en un bucket dedicado; este módulo no migra ni crea backend implícitamente. `prevent_destroy` y deletion protection requieren un procedimiento separado para retirada, jamás desactivarlos para resolver un plan inesperado.

## 3. Publicar e instalar imagen

Publicar e instalar exclusivamente el SHA y digest `operational-paper` del expediente vigente. El OCI local no equivale a publicación: tras subirlo, verificar el digest leído desde Artifact Registry. No mezclar imagen, configuración o estado de versiones distintas ni instalar la imagen experimental histórica f6. Si se reconstruye, repetir las pruebas y registrar el nuevo digest antes de instalar.

La ruta opcional CI usa `.github/workflows/gcp-image.yml`: solo dispatch manual en `main`, variable `GCP_DELIVERY_ENABLED=true` y environment `gcp-delivery`. Configurar protección/reviewers de ese environment y WIF mediante IDs numéricos verificados de owner/repo. Terraform genera provider y cuenta de entrega. Las variables no secretas son `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DELIVERY_SERVICE_ACCOUNT`. No introducir llaves JSON permanentes.

El workflow prueba y publica la imagen; muestra SHA y URI `@sha256:...`. No despliega ni activa. El runtime no confía en un tag mutable. Instalar desde una terminal conectada y después de revisar digest/SHA:

```bash
bash scripts/gcp/deploy.sh --execute PROJECT_ID us-central1-a trading-lab IMAGE_URI_WITH_DIGEST FULL_GIT_SHA
```

El script remoto rechaza un worker activo o habilitado, verifica la etiqueta SHA y paper en la imagen y deja API iniciada y worker apagado. Para actualizaciones, desactivar primero mediante el paso de mantenimiento. La instalación guarda `previous-release.conf`. El script usa el token temporal de la identidad VM para leer Artifact Registry; no inicia sesión con una persona.

Comprobar bootstrap por IAP: `sudo journalctl -u google-startup-scripts.service`, `sudo systemctl status trading-lab-api`. El script de arranque monta únicamente el disco dedicado, rechaza medios desconocidos no vacíos e instala Docker/Google CLI/Ops Agent desde fuentes oficiales. No expone el dashboard a Internet.

Acceso privado, después de conectar la cuenta:

```bash
gcloud compute ssh trading-lab --project PROJECT_ID --zone us-central1-a --tunnel-through-iap -- -N -L 8080:127.0.0.1:8080
```

Abrir `http://127.0.0.1:8080/`. `/healthz` confirma servidor vivo; `/readyz` debe permanecer 503 antes de importación y progreso del worker. Que el panel abra no demuestra operatividad.

## 4. Importación, ensayo y cutover

Antes del corte, probar con una copia del estado en una carpeta temporal independiente: importar, inspeccionar, backup, verify-backup y restore a otra carpeta vacía. Comparar efectivo, posiciones, operaciones, máximos, kill switches, aportaciones y última vela. Si existen órdenes externas pendientes, reconciliarlas antes de permitir ejecución. Nunca rellenar huecos de contabilidad inventando números.

Durante el corte definitivo:

1. Deshabilitar el workflow legacy `daily.yml` completo, que contiene **ambos triggers**, horario y diario; bloquear también dispatch manual mientras dure el corte. Si hay gate de suspensión en la versión del repositorio, activarlo adicionalmente. Verificar en GitHub que no quedan ejecuciones activas/pendientes. Apagar solo el cron horario no es suficiente.
2. Exportar el `state/` definitivo del último commit tras el fin del writer, junto con su SHA y hashes. Mantener la copia original intacta. En la VM staging debe estar fuera del volumen de destino, por ejemplo `/tmp/trading-legacy/state`, accesible al UID 10001. No copiar `.env` ni `.git`.
3. Importar al disco nuevo; el comando rechaza sobrescritura. Las líneas siguientes se ejecutan **en la VM**, después de instalar imagen y revisar la copia:

```bash
sudo -s
source /etc/trading-lab/release.conf
docker run --rm --network none --read-only \
  --mount type=bind,src=/tmp/trading-legacy/state,dst=/legacy,readonly \
  --mount type=bind,src=/var/lib/trading-lab,dst=/var/lib/trading-lab \
  "$TRADING_IMAGE" python -m lab.ops import-legacy --source /legacy --data-dir /var/lib/trading-lab
docker run --rm --network none --read-only \
  --mount type=bind,src=/var/lib/trading-lab,dst=/var/lib/trading-lab \
  "$TRADING_IMAGE" python -m lab.ops inspect --data-dir /var/lib/trading-lab
systemctl start trading-lab-backup.service
```

4. Verificar que backup+manifiesto llegaron a GCS. Descargar una copia como operador con permiso de lectura y restaurarla en **otra carpeta vacía**, verificar hashes/contenido. La identidad del worker solo puede crear backups; deliberadamente no puede leer ni borrarlos.
5. Solo tras corte e importación conciliada, activar el paper worker:

```bash
docker run --rm --network none --read-only \
  --mount type=bind,src=/var/lib/trading-lab,dst=/var/lib/trading-lab \
  "$TRADING_IMAGE" python -m lab.ops activate --data-dir /var/lib/trading-lab --cutover-confirmed
systemctl start trading-lab-worker
```

6. Revisar primer ciclo, cuentas paper internas, frescura, `/readyz`, cero duplicados y backup. No activar brokers paper externos mediante nuevas llaves durante el mismo corte. Las referencias Secret Manager quedan vacías hasta un cambio separado y explícito; nunca copiar credenciales reales.
7. Tras primer heartbeat válido y primer backup verificado/subido, habilitar `enable_operational_alerts` con IDs de canales verificados y aplicar un plan revisado. Simular ausencia/fallo y comprobar recepción: una política creada sin notificación comprobada no equivale a monitoreo operativo. Verificar aparte la alerta de backup: en una ventana de ensayo supervisada, con copia restaurada y validada, parar temporalmente `trading-lab-backup.timer`; comprobar aviso tras dos horas sin éxito (más latencia de Monitoring), reiniciar el timer, ejecutar un backup y comprobar recuperación. Nunca dejar el timer detenido al terminar. Un heartbeat sano no sustituye esta prueba.

La aplicación usa la estrategia existente diaria; el ciclo de cinco minutos observa y comprueba si venció una vela, no aprueba una estrategia de mayor frecuencia. Mantener observación simulada cuatro semanas y medir costes de ejecución. Esta plataforma nueva no tiene una ruta autorizada a dinero real.

## 5. Mantenimiento, restauración y rollback

Deshabilitar el flag antes de parar: evita que un restart automático reactive el worker. En la VM:

```bash
source /etc/trading-lab/release.conf
docker run --rm --network none --read-only \
  --mount type=bind,src=/var/lib/trading-lab,dst=/var/lib/trading-lab \
  "$TRADING_IMAGE" python -m lab.ops deactivate --data-dir /var/lib/trading-lab
systemctl stop trading-lab-worker
systemctl start trading-lab-backup.service
```

Esperar apagado limpio y revisar cualquier orden pendiente. Instalar nuevo digest con `deploy.sh`; contrastar compatibilidad del schema antes de reactivar. Un rollback de imagen no hace rollback de operaciones ni permite restaurar estado viejo sobre posiciones posteriores.

Para recuperar desde backup: detener worker/API; descargar archivo y manifiesto a staging; `lab.ops verify-backup --source archivo.sqlite3`; `lab.ops restore --source archivo.sqlite3 --data-dir carpeta-nueva`. El destino debe estar vacío y el worker queda deshabilitado. Validar balances y reconciliar antes de decidir el cambio de volumen/ruta. Conservar intacto el disco anterior para investigación. Las restauraciones ante pérdida de VM deben usar un disco nuevo; no formatear ni sobreescribir el original.

Si falla un respaldo, consultar `journalctl -u trading-lab-backup.service` y el evento JSON `backup/failed`, que indica fase (`setup`, `create`, `verify`, `upload` o `retention`) y código de salida sin incluir credenciales. Revisar disco y permisos, corregir la causa y repetir el servicio; comprobar el evento `backup/ok`, ambos objetos remotos y una restauración en destino vacío. La alerta de ausencia a dos horas también cubre fallos que impidan escribir el log o ejecutar el script.

Para volver al escritor GitHub, primero parar y desactivar GCP, exportar estado compatible con su versión y verificar ausencia de órdenes sin conciliar. No reactivar simplemente el cron sobre el commit anterior: perdería las operaciones del nuevo runtime. Si no existe exportación compatible probada, permanecer pausado hasta implementarla. Es preferible recuperar la VM/imagen anterior sobre la misma base transaccional conciliada.

Los cambios a metadatos startup se aplican en el próximo arranque; no reiniciar durante órdenes activas. Los backups, alertas, recuperación IAP y comportamiento tras reboot solo podrán declararse probados después de verificarlos en GCP. La validación local no certifica permisos, cuotas, saldo de créditos ni acceso a los exchanges desde esa región.
