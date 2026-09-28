# Entrega funcional: comparación, simulación y conexión de cuentas

Fecha de apertura: 2026-09-28 UTC / 2026-09-27 CDMX. Solicitud: cerrar la primera comparación correctamente, entregar el sistema funcional y documentar cómo conectar la cuenta/portafolio real. La cuenta GCP prevista es `brandonmuro.work@gmail.com`, con presupuesto de US$60 mensuales. La conexión GCP y la activación de dinero real se distinguen de la entrega local.

## Evidencia requerida

| Resultado | Prueba de aceptación | Estado |
|---|---|---|
| Histórico válido | Preregistro anterior, fuentes fijas, corrección AVAX auditable, todos los criterios y curvas | En preparación v2; v1 falló antes de rendimientos y se conserva |
| Paper separado | Ciclo con datos públicos, mismo cierre para las dos carteras, reintento sin duplicados | Pendiente de ejecución |
| Recuperación | Backup consistente y restore aislado de comparación; igualdad de saldos/operaciones | Pendiente |
| Panel | HTTP y navegador leen comparación verificada y estado paper | Implementado, pendiente de lectura de resultados reales |
| Imagen Linux AMD64 | SHA de código → imagen OCI → arranque y lectura; sin secretos | Construcción aislada en curso |
| Cuenta real | Preflight GET sin órdenes; identidad estable; instrucciones para efectivo y posiciones existentes | Implementación y documentación en revisión |
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

Los resultados finales y comandos exactos se incorporarán a este expediente al verificarse, junto con las limitaciones pendientes.
