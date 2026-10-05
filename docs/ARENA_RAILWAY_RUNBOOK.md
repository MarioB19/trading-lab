# Arena en Railway: traslado del 4-oct-2026

Brandon solicita publicar en Railway la arena aprobada. La autorización amplía
el alojamiento local a producción web, manteniendo exclusivamente dinero ficticio.
Servicio y volumen independientes del piloto; no se necesitan llaves de exchange.
Acceso con el usuario y contraseña del panel existente mediante referencias de
variables Railway. No se cambia ni se imprime su valor. Sin push a GitHub.

La implementación conserva exactamente las señales, costos y reglas del protocolo
`four-strategy-arena-v1`, con preregistro `61c6ac3`. La versión local de origen es
`7c3afe42cffaa87d2e19c8f0de48723ea3d8ab63`. Solo se añade alojamiento, autenticación,
comprobación de la imagen y migración de identidad del código. No se reinicia
capital, contadores, posiciones, fechas de inicio ni historial para este traslado.
El intervalo sin ejecución se registra; no se reconstruyen fills retrospectivos.

## Paquete y despliegue

`scripts/arena/package.py DESTINO_NUEVO` exige checkout limpio y genera un paquete
permitido de código, configuración, panel y prueba Git de contenido/ascendencia.
Excluye datos, `.git`, credenciales e informes ajenos. El contenedor verifica la
prueba contra el SHA fijado en su imagen antes del arranque y en cada ciclo.
La atestación verifica todos los archivos de `src`, el plan y preregistro originales.

Desplegar mediante Railway CLI a un servicio nuevo `trading-arena`, una réplica,
sin suspensión, volumen propio `/data`, salud `/healthz`, puerto 8080, overlap 0 y
draining 60 s. Mantener `ARENA_WORKER_ALLOWED=false` durante preparación/importación.
`TRADING_DASHBOARD_USER` y `TRADING_DASHBOARD_PASSWORD` referencian las variables
homónimas de `trading-lab`. HTTP/controles requieren autenticación; POST requiere
Origin HTTPS igual al dominio público. Healthz es solo señal de proceso; readyz
comprueba frescura y salud de simulación. No exponer el puerto interno directamente.

## Corte y migración

1. Mantener ejecutor remoto desactivado. Detener ambos procesos locales con el
   script de la versión original y verificar sus PID muertos.
2. Hacer backup consistente de la base local con `lab.arena backup`, auditar y
   archivar una lectura final; conservar esta copia para recuperación.
3. Subir la copia por el canal autenticado Railway a `/data/arena-imports/`.
   Restaurar con `lab.arena restore` a `/data/arena` vacío y desactivado, como UID10001.
4. Comparar filas/manifest/wallets con la copia local. Ejecutar
   `python -m lab.arena_hosted migrate --cutover-confirmed`: bloquea el escritor,
   audita, exige exactamente versión de origen y mismo protocolo; conserva prueba
   previa en un evento, registra migración y cancela las cotizaciones antiguas.
5. Verificar que efectivo, inventario, costos, fills, decisiones e historia sean
   idénticos. El manifiesto cambia solo en proof/hosting_migration y las carteras
   solo en cotizaciones canceladas.
6. Habilitar `ARENA_WORKER_ALLOWED=true`, redesplegar y, una vez sano,
   `python -m lab.arena_hosted activate --cutover-confirmed`. Ambos candados son
   necesarios. Comprobar un único worker, ciclo sano, contabilidad y HTTPS.
7. Descargar respaldo posterior y restaurar en copia local inactiva; comparar.
   Verificar que el piloto original conserva su deployment y estado.

## Operación

El supervisor funciona como UID10001, propaga SIGTERM, reinicia mediante Railway
si muere un proceso y exige volumen montado. SQLite usa transacciones y WAL;
un lock impide dos workers sobre la misma base. Backups al iniciar y cada 24h,
siete copias internas conservadas. El panel permite pausar cada estrategia;
pausar no liquida inventario. Para detener todo, quitar `/data/arena/arena.enabled`
con `lab.arena_hosted deactivate`; antes de restores también apagar la variable
externa. No volver a ejecutar la copia local que quedó archivada después del corte.

Los backups internos comparten volumen: la entrega incluye descarga comprobada,
pero copia externa automática sigue pendiente. Servicios y almacenamiento nuevos
consumen recursos del plan Railway existente; no se cambia el plan contratado.
No hay promoción a dinero real ni rentabilidad demostrada.
