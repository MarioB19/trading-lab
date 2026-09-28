# Entrega funcional: comparación, simulación y conexión de cuentas

Fecha de apertura: 2026-09-28 UTC / 2026-09-27 CDMX. Solicitud: cerrar la primera comparación correctamente, entregar el sistema funcional y documentar cómo conectar la cuenta/portafolio real. La cuenta GCP prevista es `brandonmuro.work@gmail.com`, con presupuesto de US$60 mensuales. La conexión GCP y la activación de dinero real se distinguen de la entrega local.

## Evidencia requerida

| Resultado | Prueba de aceptación | Estado |
|---|---|---|
| Histórico válido | Preregistro anterior, fuentes fijas, corrección AVAX auditable, todos los criterios y curvas | Completo; v2 rechaza la candidata, 27 artefactos y ledger verificados; v1 fallido conservado |
| Paper separado | Ciclo con datos públicos, mismo cierre para las dos carteras, reintento sin duplicados | Verificado: 1 observación, 12 fills simulados; reintento sin duplicados |
| Recuperación | Backup consistente y restore aislado de comparación; igualdad de saldos/operaciones | Verificado: seis tablas y dos capturas idénticas; restore desactivado |
| Panel | HTTP y navegador leen comparación verificada y estado paper | Verificado localmente; muestra histórico y primera observación, sin errores de consola |
| Imagen Linux AMD64 | SHA de código → imagen OCI → arranque y lectura; sin secretos | Construida y smoke offline aprobado; digest y artefactos registrados abajo |
| Cuenta real | Preflight GET sin órdenes; identidad estable; instrucciones para efectivo y posiciones existentes | Diagnóstico implementado y probado con dobles; comprobación offline correcta; conexión privada pendiente |
| GCP | Infraestructura y runbook preparados; digest, proyecto y lectura remota cuando se conecte | Sin autenticar ni desplegar |
| Promoción de estrategia | Gates cuantitativos y al menos 28 días futuros continuos, más decisión humana | No autorizada por el software; no se anticipan días |

La comparación terminada puede rechazar la candidata. Entregar el experimento funcional no requiere que gane: requiere datos trazables, cálculos honestos y un veredicto que conserve también los fallos. Un resultado retrospectivo no acredita rentabilidad futura.

## Registro de decisiones de esta entrega

- `aggressive-v2` cambia únicamente disponibilidad de AVAX anterior al mercado spot de referencia verificado el 2020-09-22. No cambia estrategia, costos, muestra restante ni umbrales.
- Preregistro propio: `1fe6c8c586b6a9899190b4f987807daf9134846c`; hash canónico del plan: `4fe0885b787d4ba341e4a8e606d4bd25aa0f2078427d1db99bba4194174381e1`.
- El plan mantiene capital virtual US$1,000 por cartera. No adopta saldos ni posiciones reales.
- Las llaves y la activación real siguen siendo acciones manuales de Brandon. La consulta de cuenta separada usa credenciales dedicadas y GET exclusivamente; no certifica permisos de solo lectura del proveedor si éste no los informa.
- La renovación de llaves no debe cambiar la identidad contable de una cuenta. Los ledgers antiguos de brokers privados requieren conciliación explícita; no se reasigna propiedad automáticamente.
- No se borra almacenamiento compartido ni se interrumpe otro proyecto para construir la imagen.

## Resultado de la comparación

[Informe completo](../reports/aggressive_v2_resultado.md) y [resultado con hashes](../reports/aggressive_v2_resultado.json). Corrida `20260928T023514Z-2b88ffec`, ejecutada en `0541232af0ae9db2d56227c0442f0e4e4aa06401`, una sola vez con el árbol limpio. El periodo 2021-01-01..2026-09-26 ya se había inspeccionado; no es un holdout inédito.

| Cripto después de costos | Control | Agresiva |
|---|---:|---:|
| Rentabilidad anualizada compuesta | 33.77% | 17.08% |
| Caída máxima | −39.48% | −45.13% |
| Sharpe | 1.129 | 0.753 |

Falla los siete criterios. El seguimiento futuro sirve para verificar el funcionamiento; completar 28 días no revoca este rechazo. La estrategia activa no cambia.

## Primer ciclo paper y recuperación

Evidencia legible por máquina: [paper_acceptance.json](../reports/delivery/paper_acceptance.json). Código ejecutable fijado: `f6c19fdcac943978011b3e096280beb7d0528884`. Prueba de preregistro canónica: `3012f6d1b2e78073948bb085b4105df238de25c501fd4418567bd0e523927186`; SHA256 del archivo de prueba: `2c65e3ce4842a4aa84800d2b1f5741d153c0d1b0b52eb77bcf057f4133c34d15`.

- Inicio real de observación: **2026-09-28 02:59:25 UTC / 27-sep 20:59:25 CDMX**. Cierres: cripto 27-sep; ETFs 25-sep. Run ID `d29350d13e8d4a9196ace417bbd5822a`.
- Se descargaron datos públicos, sin credenciales privadas: 719 cierres cripto y captura de ETFs ajustados. Las dos carteras usan exactamente las mismas capturas por mercado. El proveedor efectivo de cada activo no queda identificado individualmente; la procedencia registra proveedores configurados.
- Primer ciclo: 24.48 segundos, RSS máximo 128,024,576 bytes (122.1 MiB), medido en macOS ARM64. No sustituye la medición de carga en la VM Linux; el paquete configura 768 MiB por contenedor experimental.
- Una observación, 12 fills internos, cuatro filas de equity y cero órdenes externas. Capital virtual después de costos de entrada: control US$998.15 y agresiva US$997.81. Todavía no hay un día completo de rendimiento observado.
- Reintento a las 03:00:15 UTC: mismos conteos, carteras, capturas y fecha de inicio. No suma días ni vuelve a comprar.
- `paper_ops backup`, `verify-backup`, `restore` e `inspect` terminaron correctamente. Igualdad completa de `documents`, `equity`, `events`, `live_equity`, `orders` y `trades`, más las dos capturas SHA256. Ningún servicio se activa al restaurar.
- API local: `/healthz` 200, `/api/comparison` 200 y `/readyz` 503 porque el worker operativo está desactivado. El panel muestra los siete fallos y una observación paper. La cartera operativa que presenta es una copia importada del piloto, no saldo de un broker conectado.

Ubicaciones locales desde la raíz del repositorio:

| Contenido | Ruta |
|---|---|
| Comparación vigente | `runtime-data/delivery-20260928/aggressive-v2` |
| Backup completo verificado | `runtime-data/delivery-20260928/backups/aggressive-v2-first` |
| Restauración de ensayo desactivada | `runtime-data/delivery-20260928/restored-aggressive-v2` |
| Logs y comprobaciones | `runtime-data/delivery-20260928/` |

Estos datos están ignorados por Git y conservados en disco; no son una copia remota. Respaldar el bundle completo antes de limpiar el equipo. No modificar ni borrar capturas, manifiestos, preregistros o commits científicos ya utilizados. No hacer rebase de esos commits para presentar una historia más corta.

## Uso local de la versión fijada

El contexto congelado está en `/Volumes/KINGSTON/trading-lab-build-y3k2ua9j/artifacts/release-f6c19fdcac94/context`. No contiene `.git`, `.env`, estado ni bytecode. Usar esta misma versión y atestación para continuar la observación; ejecutar desde un checkout Git produciría una identidad de prueba diferente y se rechaza.

Desde la raíz del repositorio, este comando ejecuta como máximo un par nuevo:

```sh
TRADING_CONTEXT=/Volumes/KINGSTON/trading-lab-build-y3k2ua9j/artifacts/release-f6c19fdcac94/context
env PYTHONPATH="$TRADING_CONTEXT/src" PYTHONDONTWRITEBYTECODE=1 \
  TRADING_LAB_BUILD_ID=f6c19fdcac943978011b3e096280beb7d0528884 \
  .venv/bin/python -m lab.paper_comparison --once --fetch \
  --plan "$TRADING_CONTEXT/configs/experiments/aggressive_v2.yaml" \
  --attestation "$TRADING_CONTEXT/reports/attestations/aggressive-v2.json" \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --data-dir runtime-data/delivery-20260928/aggressive-v2
```

Para abrir el panel si no sigue iniciado:

```sh
.venv/bin/python -m lab.service \
  --data-dir runtime-data/delivery-20260928/operational-readonly \
  --comparison-dir runtime-data/delivery-20260928/aggressive-v2 \
  --research-dir reports/experiments/aggressive-v2/20260928T023514Z-2b88ffec \
  --port 8847
```

Abrir `http://127.0.0.1:8847/`. Es un servicio local de lectura; mantenerlo abierto no ejecuta estrategias. No se instaló programación continua local ni cloud. Los [servicios y timers preparados](../scripts/paper/README.md) se instalan al conectar GCP; el [procedimiento de continuidad](PAPER_OPERATIONS.md) conserva esta observación mediante restore, sin reiniciar su identidad. Si se omiten días, el sistema los registra: no se reconstruyen como observaciones futuras.

## Imagen conservada y pruebas de software

[Verificación OCI](../reports/delivery/oci_image.json) y [evidencia completa del smoke](../reports/delivery/image_acceptance.json): código `f6c19fdcac943978011b3e096280beb7d0528884`, plataforma `linux/amd64`, UID/GID `10001:10001`. La construcción exige `REQUIRE_RESEARCH_ATTESTATION=true` y verificó el código/preregistro dentro de la imagen.

- Digest de manifiesto OCI: `sha256:97c202f9cdfee3b9183a81f6675f769aac79e42d78a654844a38543ae910de33`.
- Archivo: `/Volumes/KINGSTON/trading-lab-build-y3k2ua9j/artifacts/release-f6c19fdcac94/trading-lab-linux-amd64.oci.tar` (119,414,272 bytes).
- SHA256 del archivo tar: `63354bfd35afb098da3a6a42694973c06d819b3a143b28e10dd505e3f7f0f6d2`. Es distinto del digest del manifiesto; ambos están verificados.
- Contexto, atestación, inventario de archivos, `build.log` y `smoke.log` se conservan en la misma carpeta del release. No contienen credenciales. El archivo OCI todavía no se publicó en Artifact Registry.
- Smoke offline final aprobado en Linux x86_64, UID 10001: imports, configuración paper, API/panel, importación sintética, integridad SQLite, checksum de backup y restore desactivado. La atestación válida pasa y una alterada se rechaza. Pico RSS 115,656 KiB (113 MiB) del smoke sintético; no equivale a un ciclo público completo en GCP. El ensayo añade scripts temporales sobre las mismas capas verificadas, sin modificar el OCI entregado.
- Suite final: **317 passed en 82.13 segundos**. Replay de 365 días: diferencia máxima **0.458%**, menor al 2%. Terraform: tres planes mock; nueve casos de montaje y catorce comprobaciones de scripts. No certifican una VM remota.

Los cambios posteriores a `f6c19fd` documentan resultados y procedimientos. No cambian el código ejecutado, el contexto congelado ni la identidad de la comparación. Para continuar el paper no usar automáticamente el HEAD documental como nuevo release.

El builder temporal quedó detenido y su loop de almacenamiento desconectado; OCI, contexto, prueba, logs y caché propio se conservan. No se reinició ni limpió Docker compartido. El SHA256 de la evidencia completa es `5134fd39bddaec98eab06bee350e303032458c87cf5a281e2af8cbf6203db708`.

## Conexión posterior y límites de esta entrega

La [guía de cuenta real](REAL_ACCOUNT_RUNBOOK.md) describe cómo preparar credenciales de consulta e inspeccionar la cartera sin enviar órdenes. La prueba offline está en [account_readiness_offline.json](../reports/delivery/account_readiness_offline.json). No se han consultado cuentas privadas, adoptado inversiones existentes ni habilitado una ruta de operación real.

El [plan GCP](IMPLEMENTATION_PLAN.md) y [runbook](GCP_RUNBOOK.md) dejan la secuencia para conectar `brandonmuro.work@gmail.com`, verificar créditos/facturación y desplegar paper. Cuenta prevista y presupuesto de US$60 no identifican por sí solos un proyecto ni garantizan créditos. Faltan autenticación, plan cloud revisado, publicación de imagen, instalación, corte del escritor GitHub, readback remoto, backup descargado de GCS, alertas comprobadas y costo medido.

No hay cuatro semanas observadas. La cartera agresiva está rechazada. La conexión de consulta está preparada; administrar inversiones reales requiere las migraciones, conciliación y validación externa detalladas en la guía, además de la activación manual exclusiva de Brandon.
