# Trading Lab en Railway

Una instancia con API autenticada y ejecutor exclusivamente simulado. SQLite,
datos de mercado y backups viven en el volumen de 5 GB montado en `/data`.
La estrategia, los movimientos de capital y el historial se conservan.

## Recursos

- Proyecto: `24021d85-bbad-4f2c-850c-e1230822e7b0` (Trading Lab).
- Entorno: `4774e5bf-c72b-402d-ac72-f88e815e5976` (production).
- Servicio: `769ae901-e962-45e4-8666-11c3351f7249` (trading-lab).
- Volumen: `68434aac-230f-4552-bdb4-7faf184b55e2` (`/data`).
- Cuenta Railway verificada: `brandonmuro.contacto@gmail.com`. Es independiente
  de la cuenta GCP prevista en las guías anteriores. GCP permanece sin desplegar.

## Configuración

**Versión vigente:** `railway-fe50d0ea8a3e5a3d`, deployment `dd5e35e1-3a7c-4bd3-b41b-797d0d2559ca` (`SUCCESS`, 4-oct UTC / 3-oct CDMX). FIFO desde SQLite en lectura coherente, conciliación de cantidades/P&L, recuperación paper de efectivo negativo, flujo diario conservado en reintentos y escenarios económicos del panel. 508 pruebas, replay 0.458%; configuración idéntica, 42 archivos instalados verificables por SHA256. Primer ciclo sano 4-oct 01:02:47 UTC, un worker, paper/ready, cero órdenes pendientes/desconocidas. Backups antes/después restaurados con datos idénticos y worker desactivado. Base US$1,000 aplicada 500/500; déficit ETF −US$0.10 pendiente del próximo cierre fresco, sin operación forzada.

Origen HEAD `9190176` con cambios sin commit en rama `codex/rentabilidad-20261003`; identidad por manifiesto de contenido. Evidencia: `reports/operations/profitability-20261003.json` y `runtime-data/profitability-20261003/`. Investigación: `docs/PROFITABILITY_RESEARCH_20261003.md`. La corrección del bootstrap no vuelve a ejecutar ni altera ensayos congelados; ninguna candidata se promueve.

**Versión anterior (30-sep):** `railway-1ae90503c3b9007d`, deployment
`035ebf32-cf75-4eaa-8143-9b1730db4798` (`SUCCESS`, 30-sep 00:59 UTC).
Añade diagnóstico autenticado de costos/rotación y telemetría futura de ejecución;
mantiene configuración e historial. 454 pruebas y replay 0.458%; 40 archivos
instalados y assets HTTPS coinciden con el paquete. Primer ciclo sano del
30-sep 01:00:41 UTC: paper, ready=true, un único worker y cero órdenes
pendientes/desconocidas. Endpoint nuevo HTTPS 200 autenticado / 401 sin credencial.
Backups antes/después descargados/restaurados desactivados, 24 trades y 10 cierres
conservados. `rotation_buffer=0.15` sólo está preparado para investigación y
no puede activarse en el runtime. Plan en `docs/IMPROVEMENT_PLAN.md`; evidencia
en `runtime-data/improvements-20260929/`. HEAD `c1b226a` con cambios sin commit;
la identidad desplegada corresponde al hash del paquete, no a un commit nuevo.
Registro local posterior autorizado por Brandon: base `5d6f5ff`, preregistro
`af34687` y código posterior. La coincidencia entre código comprometido y paquete
publicado se comprueba por hashes; no se vuelve a desplegar por versionar el código.

**Versión anterior:** `railway-d22975cab19f4797`, deployment
`77ca3681-9e36-4c54-8395-9bc13d481a6b` (`SUCCESS`, 29-sep 05:24 UTC).
Añade balance diario en MXN/USD, capital neto y selección de fecha/bloque.
432 pruebas aprobadas; 39 archivos instalados comparados con su manifiesto.
Primer ciclo de esta versión: 05:26:01 UTC, paper, `ready=true`, cero órdenes
pendientes/desconocidas y backup verificado. API y assets comprobados desde el
servicio vía SSH oficial; sin credenciales responde 401. La gráfica se validó
visualmente sobre una copia local desactivada; la política del navegador
integrado impidió inspeccionar el panel remoto. Evidencia en
`runtime-data/railway/daily-balance-20260928/`.

Un servicio, una réplica, suspensión automática desactivada, salud `/healthz`,
timeout 120 segundos, overlap 0, draining 60 segundos y reinicio ON_FAILURE
(10 intentos). Dockerfile propio en `infra/railway/Dockerfile`.
Se configura mediante la API/CLI oficial: `railway.toml/json` está deprecado
para servicios nuevos. La prueba de salud de Railway sólo cubre el despliegue;
la salud operativa del bot se consulta en `/readyz` y en el panel.

Variables no secretas: `PORT=8080`, `TRADING_DASHBOARD_USER=brandon`,
`RAILWAY_DEPLOYMENT_OVERLAP_SECONDS=0`,
`RAILWAY_DEPLOYMENT_DRAINING_SECONDS=60` y `TRADING_WORKER_ALLOWED=true`
tras completar el corte. `TRADING_DASHBOARD_PASSWORD` quedó configurada en
Railway por solicitud explícita de Brandon; su valor no se guarda en el
repositorio ni en la documentación. Cualquier cambio requiere redeploy y
comprobación del acceso. Antes de una migración, mantener el worker en `false`.
Nunca subir credenciales de Bitso/Alpaca ni `.env`.

Sin credenciales del panel, todos sus recursos devuelven 503; sin autenticación
válida devuelven 401. `/healthz` sólo revela una señal genérica. La contraseña
se usa detrás de HTTPS de Railway. El panel no tiene operaciones de escritura.

El arranque prepara exclusivamente `/data/runtime`, `/data/backups` e
`/data/imports` y baja de root a UID/GID 10001 antes de abrir HTTP o ejecutar
el bot. El volumen es obligatorio. El supervisor necesita AMBOS candados:
`TRADING_WORKER_ALLOWED=true` y `worker.enabled`, creado únicamente con
`lab.ops activate --cutover-confirmed`.

## Entrega de código

```sh
.venv/bin/python -m pytest -q -W ignore
.venv/bin/python scripts/railway/package.py runtime-data/railway/RELEASE/bundle
railway up runtime-data/railway/RELEASE/bundle --path-as-root \
  --service trading-lab --environment production --detach
```

Usar un nombre nuevo para RELEASE. El paquete es una lista permitida de código,
configuración y tres assets del panel. No contiene estado, secretos, `.git`,
datasets o informes. `release.json` identifica cada archivo por SHA256, el HEAD
de origen y si existen cambios sin commit; su `build_id` corresponde al contenido
efectivamente subido. Una subida aceptada no equivale a deployment sano.

Revisar estado final, logs, UID, montaje, build_id y HTTP. Nunca activar
autodeploy desde `main` mientras esa rama no integre y valide esta entrega.

## Corte de GitHub a Railway

1. Verificar servicio desplegado, volumen y API; mantener ambos candados apagados.
2. Deshabilitar workflow `daily.yml` remoto y comprobar que no queden ejecuciones
   activas/en cola. Registrar `TRADING_RUNTIME=railway` como propietario.
   La versión antigua del workflow sólo reconoce `gcp`; deshabilitar el workflow
   es imprescindible hasta integrar la condición nueva del repositorio.
3. Descargar un único SHA final de `origin/main` y exportar los seis archivos
   legacy permitidos. Registrar SHA y hashes. No importar el estado local viejo.
4. Subir esa copia a `/data/imports/SHA/` por el canal autenticado de Railway.
   Ejecutar como UID10001 `python -m lab.ops import-legacy --source ...
   --data-dir /data/runtime`. No copiar SQLite/WAL abierto ni editar sus tablas.
5. Conciliar contadores, saldos, capital, órdenes y hashes; generar y verificar
   backup con `lab.ops`, descargar DB+manifiesto, restaurar localmente a destino
   vacío y desactivado, comprobar historial y saldos.
6. Habilitar `TRADING_WORKER_ALLOWED=true` y confirmar que el marker sigue ausente.
   Después ejecutar `lab.ops activate --data-dir /data/runtime --cutover-confirmed`.
   El supervisor lo detecta sin otro redeploy. No ejecutar `lab.bot` manualmente.
7. Verificar primer ciclo completo, ausencia de órdenes inciertas, `readyz=200`,
   respaldo y una segunda lectura/observación sin duplicados. Esto no acredita
   cuatro semanas de estabilidad ni autoriza dinero real.

## Respaldo, pausa y recuperación

El supervisor crea un backup SQLite consistente al encontrar una importación,
tras reiniciar y cada 24 horas; verifica esquema, tamaño y SHA256. Conserva siete
copias válidas propias. Los fallos se registran y se reintentan a los cinco
minutos. Los backups dentro del mismo volumen no protegen por sí solos frente
a pérdida del volumen. **Hobby no permite crear ni programar backups nativos**,
confirmado en la pestaña Backups del servicio; la API devuelve `Not Authorized`.
La entrega conserva una descarga comprobada fuera del proveedor. Una copia
externa automática queda pendiente de Pro o de almacenamiento externo; no se
contrató otro plan ni se afirma que esa protección ya esté activa.

Pausa: cambiar primero `TRADING_WORKER_ALLOWED=false`, esperar redeploy y
verificar que no exista worker; quitar el marker mediante `lab.ops deactivate`.
Para cualquier restore de volumen de Railway, apagar primero el candado externo:
el snapshot podría contener un marker antiguo. Después restaurar una copia
consistente con `lab.ops restore` a directorio vacío/desactivado, conciliar y
repetir corte/activación. Nunca volver a habilitar GitHub con Railway activo.

Railway conserva datos en el volumen durante redeploys, pero cambiar la imagen
no revierte el libro contable. No hacer rollback de datos para revertir código.
El supervisor propaga SIGTERM a todos sus subprocesos y termina los persistentes
dentro de la gracia de Railway; las intenciones inciertas requieren conciliación.

## Fuentes verificadas

- [Volúmenes](https://docs.railway.com/volumes/reference)
- [Apagado de deployments](https://docs.railway.com/deployments/deployment-teardown)
- [Backups](https://docs.railway.com/volumes/backups)
- [Subida desde CLI](https://docs.railway.com/cli/up)
- [Infraestructura como código](https://docs.railway.com/infrastructure-as-code)

El estado realmente alcanzado y la evidencia de esta instalación se guardan
en `runtime-data/railway/` y en la nota del proyecto. No interpretar este
procedimiento como prueba de que todas las etapas ya ocurrieron.

## Publicación verificada — 28-sep-2026 CDMX

- Panel: https://trading-lab-production-a56b.up.railway.app/; usuario `brandon`.
- Deployment `306083d7-78af-4eac-ad98-92a20f3d4d42`: `SUCCESS`, mismo paquete
  `railway-e71008c27911078c`, sin cambios de estrategia ni modo.
- Lectura HTTPS externa del 29-sep 04:08 UTC: sin autenticación o con contraseña
  incorrecta, 401; con la credencial autorizada, panel, JS/CSS, `/api/status`,
  `/api/performance` y `/readyz` responden 200. TLS validado.
- Ciclo posterior al reinicio completado 04:07:44 UTC, `ready=true`, paper,
  sin errores ni órdenes pendientes/desconocidas. Backup posterior verificado.
- Una réplica en `sfo`, un único `lab.runtime` y UID/GID10001. GitHub desactivado;
  42 corridas completadas y ninguna activa. Capital base US$1,000, 22 trades y
  cinco fechas de resultados diarios disponibles; el historial persiste.
- Evidencia: `runtime-data/railway/20260928/authenticated-readback.json`,
  `auth-deployments.json` y `verification.json`. El navegador integrado bloqueó
  la apertura del panel; la autenticación se verificó mediante HTTP externo y
  el estado de publicación también en la interfaz de Railway.
- La copia externa automática sigue pendiente; no se amplió el plan Hobby.
