# Evidencia local de integración GCP

Revisión: 2026-09-27, America/Mexico_City (las últimas pruebas terminaron el 28-sep UTC).
Rama: `codex/gcp-platform`. Base: `2be1139e2a55e0d61699ade8ae196e455718286f`.
Este informe conserva la cronología de validación. **El estado vigente es la entrega `f6c19fd` con 317 pruebas, comparación v2 cerrada y primer ciclo paper/restauración verificados**; consultar [DELIVERY_ACCEPTANCE.md](DELIVERY_ACCEPTANCE.md). Las secciones iniciales describen checkpoints anteriores, no bloqueos vigentes automáticamente.

Posteriormente a la validación inicial se registró la base técnica y el experimento agresivo en `c2758dd274e47c36f8c4c0012c7b07ba4a88e504`, tras el preregistro exclusivo `49c7dc42ec552c45e6dbd8e6bd8d03683e46d27a`. Pasaron 203 pruebas en ese checkpoint. La primera comparación agresiva quedó incompleta por datos, antes de calcular rendimientos: [evidencia](../reports/aggressive_v1_ejecucion.md). Sin push ni imagen publicada; las limitaciones cloud continúan vigentes.

## Verificado

| Comprobación | Resultado |
|---|---|
| Suite Python 3.13: `python -m pytest -q -W ignore` | **136 passed**, 52.30 s |
| Consistencia: `python -m lab.bot --replay 365 --sleeve crypto` | Diferencia máxima **0.458%**, criterio <2% |
| Terraform fmt, init sin backend y validate | Correctos; sin autenticación Google |
| Terraform mock provider | **3 pruebas**: defaults, digest mutable rechazado y alertas sin canales rechazadas |
| Shell y bootstrap | `bash -n` en scripts y ambas ramas del template renderizado: correcto |
| Límites de despliegue | Invariantes de imagen, UID, worker apagado, IAP y CI: correctos |
| Diff | `git diff --check`: limpio |
| Configuración y estado histórico | Sin diferencias en `config.yaml` ni `state/` |
| Panel local | Abre, presenta datos importados y ejecución desactivada; sin errores/warnings de consola en la inspección |

Las pruebas cubren propiedad de posiciones, aceptación incierta, fills parciales, conciliación repetida sin doble asiento, reinicio, kill switch persistente, compras limitadas por efectivo, ventas limitadas por propiedad, profundidad maker, transacciones, exclusión de escritores, frescura, modos incompatibles, integridad y concurrencia de respaldos/restauración. Las pruebas cuantitativas cubren causalidad y protocolo de preregistro; no son experimentos de rentabilidad.

## Ensayo con copia del estado existente

Se importaron **2 bloques, 11 operaciones, 5 filas de equity y 40 observaciones intradía** desde el estado del repositorio. Se compararon hashes de todos los archivos originales antes/después: idénticos.

- Se creó respaldo autónomo SQLite + manifiesto.
- `verify-backup` comprobó tamaño, SHA256, integridad y esquema v1 completo.
- Restauración en otra carpeta vacía, sin activar el worker.
- Estado, efectivo, posiciones, trades, equity y live_equity iguales entre origen importado y restaurado.
- SHA256 del backup de este ensayo: `4978697c439fbe9495b447d1ec0f6ecb1dd37d53a6d6f0eb4c610de89578fa75`.
- Evidencia temporal de la sesión: `/var/folders/f2/pj81kgbn0jd666nytnnzw7z80000gn/T/trading-gcp-final-doymeppq/evidence.json`. Es evidencia local temporal, no un respaldo operativo de producción.

## Pendientes del checkpoint inicial (actualizados en la entrega final)

1. **Imagen:** Docker resolvió la imagen base y los paquetes Linux ARM64, pero la instalación falló con `OSError: [Errno 28] No space left on device`. No se eliminaron imágenes/caches ajenas. Falta liberar/ampliar almacenamiento por un procedimiento autorizado y completar build y smoke **Linux AMD64**, objetivo de la VM. La imagen no se publicó.
2. **Cloud:** no se inició sesión, consultó facturación/créditos, ejecutó plan autenticado/aplicó Terraform ni creó recursos. Los mocks no prueban IAM, cuotas, red, provisión, alertas o reinicios reales.
3. **Operación:** no se apagó GitHub ni activó GCP. Falta corte, lectura de la instancia, backup remoto descargado/restaurado, recepción de alertas, recuperación ante fallo y costo medido.
4. **Brokers:** las pruebas usan dobles de broker; falta una prueba paper externa controlada. El paso del simulador interno a Alpaca exige migración independiente de propiedad. Los cambios de capital en brokers externos se rechazan para evitar una actualización parcial del ledger; el simulador interno mantiene los flows transaccionales.
5. **Investigación:** no se ejecutaron nuevas estrategias, no se recalcularon informes históricos ni se aprobó Ledoit–Wolf. Falta preregistrar y ejecutar la suite sobre el universo operable. El DSR global histórico sigue siendo una limitación.
6. **Promoción:** cuatro semanas paper desde la versión estabilizada y criterios cuantitativos antes de considerar cambios de estrategia. No hay autorización ni activación de dinero real.

La próxima sesión debe empezar por [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) y [GCP_RUNBOOK.md](GCP_RUNBOOK.md). No confundir estos resultados con evidencia de un despliegue.

## Verificación posterior: primera comparación cerrada y paper funcional

- V2 completada sobre `0541232`, preregistro `1fe6c8c`, 27 hashes y cadena del ledger verificados. La candidata falla siete criterios; [resultado](../reports/aggressive_v2_resultado.md). Esto resuelve la comparación solicitada, no la investigación futura del universo operable ni el DSR global.
- Release de software `f6c19fdcac943978011b3e096280beb7d0528884`: **317 pruebas Python aprobadas**. Terraform validado con tres planes mock, nueve casos de montaje y catorce comprobaciones sintéticas del paquete de servicios. Sin credenciales cloud.
- Primer paper con datos públicos en contexto congelado sin Git: **24.48 segundos**, máximo RSS **122.1 MiB en macOS ARM64**, 12 fills y una observación. Reintento conserva conteos y portafolios; no cuenta otra fecha.
- Backup SQLite consistente y dos capturas congeladas; verificación SHA256, restore desactivado y comparación de todas las filas de seis tablas: idénticas.
- Panel local leído en navegador: histórico, criterios fallidos y primer día visibles; sin errores/warnings de consola. `/healthz` y `/api/comparison` 200; `/readyz` 503 coherente con worker operativo apagado.
- Diagnóstico offline de Alpaca paper/real y Bitso real: `not_connected`, sin solicitudes privadas. La conexión GET y las limitaciones de adopción están en [REAL_ACCOUNT_RUNBOOK.md](REAL_ACCOUNT_RUNBOOK.md).
- Configuración y estado originales sin diferencias contra `12a54c296d41e960ccc35f311979fa7ddb3dc060`. Los artefactos de ensayo viven en `runtime-data/delivery-20260928/`, separados e ignorados por Git.

La imagen final `f6c19fd` se construyó y pasó el smoke Linux AMD64 sin red, incluida la prueba de preregistro válida/alterada. Digest `sha256:97c202f9cdfee3b9183a81f6675f769aac79e42d78a654844a38543ae910de33`; archivo OCI y logs en el expediente de entrega. El problema `ENOSPC` quedó resuelto para esta construcción mediante almacenamiento externo propio; no se limpiaron recursos compartidos. Respaldo local no equivale a copia GCS; servicios preparados no equivalen a timers instalados; una observación no equivale a 28 días completos.
