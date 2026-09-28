# Conexión del piloto BASE: una sola ruta

Esta es la secuencia vigente para preparar la conexión: **GCP con el simulador BASE → comprobar recuperación y operación → consultar cuentas por GET**. No autentica ni despliega por sí misma. No activa dinero real, no incorpora inversiones existentes y no reanuda la candidata agresiva rechazada.

El alcance BASE conserva la estrategia actual de `config.yaml`, `mode: paper` y observación intradía. Sin credenciales, acciones usa el simulador interno; cripto simula contra el libro público de Bitso, con fallback de deslizamiento supuesto cuando no puede consultar el libro. “Sin broker privado” no significa “sin Internet”: los precios y libros públicos necesitan acceso desde la región elegida. El ciclo de cinco minutos observa y comprueba el cierre diario; no cambia la frecuencia de la estrategia.

El alcance y la evidencia del release vigente están en [CONNECTION_READINESS.md](CONNECTION_READINESS.md); [DELIVERY_ACCEPTANCE.md](DELIVERY_ACCEPTANCE.md) conserva la entrega histórica. La guía de cuenta está en [REAL_ACCOUNT_RUNBOOK.md](REAL_ACCOUNT_RUNBOOK.md). Los comandos de infraestructura, importación y mantenimiento se mantienen en [GCP_RUNBOOK.md](GCP_RUNBOOK.md); esta lista fija el orden y las condiciones para utilizarlos, sin duplicarlos.

## Datos necesarios, sin secretos

Completar después de que Brandon autorice la conexión. Una cuenta de correo no identifica el proyecto ni habilita facturación.

| Dato | Valor a confirmar |
| --- | --- |
| Cuenta operadora prevista | `brandonmuro.work@gmail.com` |
| Proyecto GCP existente | Project ID y propietario responsable |
| Facturación | Billing account ID, proyecto vinculado y moneda |
| Créditos | Saldo, vencimiento y servicios cubiertos visibles en Billing |
| Presupuesto | Máximo solicitado US$60/mes; coste revisado y destinatario de alertas |
| Ubicación inicial | `us-central1` / `us-central1-a`, o cambio explícitamente revisado |
| Acceso y avisos | Operador IAP/OS Login y IDs de canales Monitoring existentes |
| Release BASE | SHA de código probado y URI de Artifact Registry por digest, cuando se publique |
| Estado a migrar | SHA del último estado operativo congelado y hashes de sus archivos |
| Consulta posterior | Bitso/Alpaca, entorno que se consulta y finalidad: sólo observar |

No pedir ni copiar claves API, secretos, tokens OAuth, archivos JSON de service accounts, contraseñas o códigos de segundo factor en este registro. Las credenciales se introducen únicamente por el flujo oficial del proveedor o el mecanismo interactivo local documentado. WIF y entrega por GitHub son opcionales; no hacen falta para validar primero el release BASE.

## A. Antes de conectar GCP

- [ ] Confirmar la instrucción de conexión, proyecto y facturación. Hasta entonces, no ejecutar login, plan autenticado, apply, publicación ni consultas privadas.
- [ ] Revisar créditos y coste total; no tratar los créditos como infraestructura gratuita permanente. Las alertas de presupuesto no son un tope automático.
- [ ] Elegir un único release del perfil `operational-paper`, target Docker `runtime`, con SHA, digest y pruebas propios. La imagen f6 queda archivada con la investigación; sus pruebas no acreditan la imagen nueva. Un HEAD posterior de documentación tampoco sustituye el SHA contenido en el release.
- [ ] Conservar informes, preregistros, comparación, backup y restore de `aggressive-v2` como evidencia archivada. No instalar sus timers, crear su marca de activación, migrarlo para reanudarlo ni ejecutar otro ciclo de esa candidata. Tampoco importar `comparison.sqlite3` en el runtime BASE.
- [ ] Mantener referencias de broker vacías: `paper_secret_versions = {}`. No añadir llaves “para probar la conexión” durante el corte.

**GO:** el release y su alcance BASE están identificados y los inputs anteriores están confirmados. **NO GO:** se propone modificar modo/estrategia para conectar, usar un tag mutable, iniciar la candidata rechazada o pedir secretos por chat.

## B. Aprovisionar sin ejecutar el worker

Seguir las secciones 2 y 3 de [GCP_RUNBOOK.md](GCP_RUNBOOK.md). La primera provisión usa `image_uri = ""`, `source_sha = ""`, referencias de broker vacías y alertas operativas deshabilitadas hasta tener señales verificadas. Revisar por separado el presupuesto y sus receptores; no confundirlo con las alertas del runtime.

- [ ] Revisar el plan concreto, sus recursos, roles, región y coste antes de aplicar. No conceder al worker lectura o borrado de backups para facilitar una restauración: la lectura corresponde al operador de recuperación.
- [ ] Publicar/cargar el release elegido mediante el procedimiento de registro aprobado. Leer el digest en Artifact Registry y contrastar la etiqueta de SHA; el hash del archivo OCI y el digest de su manifiesto son distintos.
- [ ] Instalarlo con `scripts/gcp/deploy.sh`. El instalador rechaza un worker activo/habilitado y un SHA distinto; deja API iniciada y worker desactivado.
- [ ] Comprobar bootstrap, UUID y montaje persistente de `/var/lib/trading-lab`, permisos de UID 10001 y espacio. Un disco montado o una VM encendida no acreditan estado importado.
- [ ] Abrir el panel únicamente por IAP y túnel a localhost. Antes del primer ciclo, `/healthz` puede responder 200 y `/readyz` debe responder 503.
- [ ] Confirmar `/etc/trading-lab/paper-secret-refs.json` vacío (`{}`), ausencia de credenciales de broker en la imagen y ausencia de `worker.enabled`. No incluir `.env` en staging, imagen o volúmenes.
- [ ] Mantener apagados todos los servicios experimentales, aunque el plan histórico de Terraform reserve almacenamiento adicional. No ampliar infraestructura sólo para sostener una candidata rechazada.

**GO:** API accesible por IAP, release y montajes comprobados, worker desactivado y sin credenciales de broker. **NO GO:** worker iniciado antes de importar, imagen no identificada, volumen incorrecto, datos en una carpeta que un montaje ocultaría o panel expuesto públicamente.

## C. Cambiar de escritor con respaldo recuperable

Seguir la sección 4 del runbook. No activar primero GCP para comprobar luego si GitHub dejó de escribir.

1. Deshabilitar `daily.yml` completo: sus disparadores horario, diario y manual comparten el writer. En la versión que lo incorpora, fijar también `TRADING_RUNTIME=gcp`. Comprobar que no quedan jobs activos ni en cola; no basta con cambiar la variable mientras un job sigue ejecutándose.
2. Congelar el `state/` definitivo con su SHA/hashes y conservar el original. La copia debe incluir estado, snapshot, live y sus CSV existentes; no usar una copia anterior de la entrega como si fuera el cierre más reciente.
3. Ensayar importación, inspección, backup y restore con una copia aislada. Si el estado refleja cuentas externas, propiedad no demostrada, otro modo o una identidad desconocida, detenerse: el importador no lo convierte en simulación interna.
4. Importar el estado conciliado al destino BASE vacío mediante `lab.ops import-legacy`. Comprobar bloques, efectivo, posiciones, máximos, kill switches, aportaciones, operaciones y últimas velas. No reinicializar capital para hacer desaparecer diferencias.
5. Crear backup con `lab.ops`, verificar archivo/manifiesto y comprobar la copia GCS. Descargar **sólo la pareja `.sqlite3` + `.sqlite3.manifest.json`** a un staging aislado y restaurar en otro directorio vacío y desactivado. No copiar una base abierta con `cp`, ni transportar sidecars de una conexión antigua como reparación.
6. Antes de activar, exigir integridad correcta y cero órdenes pendientes/desconocidas. `lab.ops activate --cutover-confirmed` valida parte de estas condiciones; el flag no verifica por sí mismo que GitHub esté detenido.

**Contrato del respaldo BASE:** `lab.ops backup` exporta una base autónoma con `journal_mode=DELETE`; la fuente operativa sigue en WAL. La pareja descargada debe verificar incluso en un directorio de sólo lectura, sin `-wal`/`-shm`. No abrir el backup con `SQLiteStore` para inspeccionarlo: esa clase prepara una base operativa y cambia el modo. Para restaurar, usar un staging aislado escribible por UID 10001 porque `restore` necesita crear su archivo de bloqueo junto al respaldo, y un destino vacío también escribible. La base restaurada vuelve a WAL y queda desactivada. La prueba local de este contrato no sustituye la descarga y restauración desde GCS durante la aceptación.

**GO:** un solo writer futuro, datos importados iguales a la copia final y restore del backup descargado comprobado. **NO GO:** fuente que aún cambia, diferencias sin explicación, respaldo sólo local, orden pendiente/desconocida o necesidad de editar SQLite a mano para continuar.

## D. Activar únicamente el piloto simulado

- [ ] Activar con `lab.ops` y arrancar `trading-lab-worker`, usando los comandos del runbook. No añadir credenciales Alpaca/Bitso ni modificar capital durante este paso.
- [ ] Revisar el primer ciclo completo. La salud debe indicar `status: ok`, `build_id` del release, observación nueva en ambos bloques y ninguna incidencia de almacenamiento. El precio público debe tener la frescura exigida; si la región no permite consultar los proveedores, detenerse y resolver la fuente, sin fabricar precios.
- [ ] Comprobar `/readyz` 200 y leer en el panel patrimonio, broker **simulado**, última observación y estado del worker. Un HTTP 200 de `/healthz` o datos heredados en pantalla no son aceptación.
- [ ] Repetir la comprobación después del siguiente ciclo y verificar que una vela ya procesada no duplica operaciones. No ejecutar un replay o una nueva búsqueda de estrategia para declarar sana la conexión.
- [ ] Confirmar backup completo, subida, recepción de alertas de heartbeat y de ausencia de backup, y recuperación del aviso. Habilitar `enable_operational_alerts` sólo con canales probados; no dejar la ausencia sin monitoreo después del ensayo.
- [ ] Documentar SHA → digest publicado → instalación → lectura remota, además del backup descargado/restaurado y costes observados.

**GO para dejarlo programado:** primer ciclo y ciclo posterior correctos, un único writer, recuperación probada y avisos recibidos. **NO GO:** credenciales externas presentes, identidad distinta, precios/heartbeat vencidos, cuentas o cifras interpretadas como reales, o backup/alertas no verificados. Si sólo falta una aceptación operativa, mantenerlo pausado o bajo el ensayo supervisado acordado; no declarar producción continua.

Esta aceptación acredita infraestructura y simulación BASE. No demuestra rentabilidad, no cumple por anticipado cuatro semanas y no permite rescatar la candidata agresiva rechazada.

## E. Consultar las cuentas, en una fase separada

Usar [REAL_ACCOUNT_RUNBOOK.md](REAL_ACCOUNT_RUNBOOK.md) y `lab.account_readiness`, inicialmente offline. Cuando Brandon decida la consulta privada, usar sus variables exclusivas `TRADING_AUDIT_*` en un proceso local temporal; no introducirlas en Terraform, el contenedor operativo, GitHub Secrets ni `.env`.

**GO de consulta:** los dos endpoints GET validan identidad estable y saldos/posiciones, `read_only_connection_ready: true`, y Brandon reconoce proveedor/entorno. `ready_for_trading` y `live_authorized` deben seguir falsos. El resultado no se guarda en el ledger del bot.

**NO GO:** identidad ausente, entorno equivocado, respuesta parcial, error HTTP, necesidad de aumentar permisos automáticamente o propuesta de vender/adoptar inversiones existentes. La conexión puede leer una cuenta bloqueada para trading: revisar los bloqueos sin tratar la lectura como autorización.

Agregar `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY` al worker cambiaría la selección del broker de acciones: dejaría de usar el simulador interno e intentaría una cuenta Alpaca paper externa. No es un paso de diagnóstico. El estado interno existente requiere una alta/migración de propiedad explícita, todavía fuera de esta ruta. La administración de inversiones reales también permanece pendiente; no existe aquí una activación operativa real.

## Pausa, recuperación y rollback

| Situación | Acción y comprobación |
| --- | --- |
| Parar el piloto | `lab.ops deactivate` antes de parar el servicio, según el runbook. Quitar la marca impide el siguiente ciclo; no prueba que el ciclo actual haya terminado. Comprobar servicio/contenedor, lock y estado antes de otro writer. |
| Fallo o cierre forzado | Conservar logs y base. Inspeccionar ejecución pendiente e integridad; no arrancar otra copia mientras el proceso anterior conserve el lock. |
| Actualizar/volver a una imagen | Worker desactivado y detenido; backup previo; esquema compatible e imagen por digest verificada. `previous-release.conf` identifica la imagen anterior, no deshace datos ni ejecuciones. |
| Recuperar una base | Descargar backup y manifiesto, verificar y restaurar con `lab.ops` en destino vacío/desactivado. Preservar el disco anterior. Reconciliar antes de seleccionar el nuevo volumen o ruta. |
| Volver a GitHub | Primero detener y desactivar GCP. Sólo reanudar con exportación compatible, conciliada y probada; reactivar el cron sobre un commit viejo pierde el estado nuevo. Si falta esa exportación, seguir pausado y recuperar GCP. |
| Fallo de conexión GET | Terminar el diagnóstico y corregir acceso/entorno sin tocar el runtime. No convertir el fallo en una cartera vacía ni asignarle efectivo. |

No habilitar un segundo writer como mecanismo de recuperación. No resolver un fallo de backup modificando checksums, borrando identidades o desactivando las protecciones del importador. No activar real como alternativa a un paper que no arranca.
