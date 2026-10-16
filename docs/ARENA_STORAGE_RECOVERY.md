# Recuperación de almacenamiento — 15-oct-2026

Brandon autoriza restablecer la arena, retirar archivos necesarios y optimizarla
considerando el volumen existente de 5000 MB. No amplía el plan ni autoriza dinero
real, cambios de estrategia, capital, frenos, secretos o push. El piloto principal
permanece fuera del corte. Esta es una corrección operativa, no una candidata.

## Incidente y conservación

El backup del supervisor agotó el volumen y falló antes de iniciar el worker.
La retención anterior se ejecutaba después de copiar y cada reinicio volvía a
crear otra copia. Inventario detenido: base 837083136 bytes, 59297 capturas,
3300 inputs, 147 fills, 237188 valoraciones; copias históricas y una incompleta
ocupan casi todo el resto. No hay freelist recuperable: VACUUM no aporta espacio.

Antes de eliminar, exportar el volumen completo como tar.gz privado y verificar
SHA de transporte y de cada archivo contra inventario remoto estable. Conservar
la base y todo el historial. Borrar solo respaldos/importaciones enumerados y
exportados, verificando tamaño/hash otra vez antes de cada unlink; no seguir
symlinks. Conservar recibo de cada ruta, tamaño y hash. La copia local es necesaria
para esta recuperación y no equivale a backup externo automático independiente.

El intento inicial de redeploy de un snapshot anterior conservó su arranque y
repitió el fallo. No repetirlo: usar bundle nuevo con `railway up`. El acceso de
rescate se obtiene con una imagen mínima que solo sirve healthz y no contiene
la aplicación ni inicia worker. No restaurar una base vieja sobre la actual.

## Política nueva

`lab.arena_storage` toma una copia consistente mediante SQLite backup a un
directorio temporal efímero fuera del volumen. Verifica integrity_check, comprime
en streaming, verifica gzip contra SHA del SQLite original y publica mediante
rename de un directorio con copia + manifiesto. El presupuesto se aplica mientras
se escribe; fallos limpian su temporal y preservan la última copia verificada.
El lock exclusivo de respaldo impide rotación simultánea. Temporales propios
abandonados se limpian bajo ese lock, sin glob de bases históricas.

- Hasta dos copias comprimidas publicadas. Antes de crear la siguiente se puede
  retirar la más vieja, conservando siempre la más nueva verificada.
- Presupuesto total: menor entre 1 GiB y 20% de la capacidad del filesystem.
  Archivos ajenos también consumen presupuesto, pero no se borran automáticamente.
- Reserva de escritura: 20% de capacidad, mínimo 256 MiB y máximo 1 GiB. En este
  volumen equivale aproximadamente a 968 MB. Sin reserva se detiene/evita iniciar
  el worker, conservando el marcador y los frenos. No se liquidan posiciones.
- Programación de 24 h persiste desde el manifiesto verificado, no desde el último
  arranque del proceso. Fallo de backup se registra por tipo, reintento en una hora,
  sin tumbar el servidor ni crear copias crudas repetidas en el volumen.

La base sigue creciendo con el historial. No hay capacidad infinita ni purga de
evidencia automática: el límite requiere seguimiento. Healthz acredita proceso;
la frescura/readiness de trading debe comprobarse aparte. Una pausa por espacio
produce un hueco de observación y no acredita continuidad científica.

## Publicación y migración documentada

1. Suite completa, commit local limpio y `scripts/arena/package.py` al bundle
   nuevo. No publicar cambios ajenos. Cincuenta archivos src de la imagen anterior
   permanecen idénticos; el supervisor queda expresamente fuera de ese conjunto
   congelado. Nuevas utilidades son de almacenamiento/diagnóstico.
   `arena_storage_upgrade.FROZEN_SOURCES` fija los 50 hashes originales.
2. Mantener mantenimiento y verificar ausencia de writer. Después de exportar
   el volumen y validar la base, archivar el marcador arena.enabled como evidencia
   y dejarlo ausente durante la actualización. Retirar únicamente las rutas de
   respaldos/importaciones exportadas y verificadas.
3. Usar startCommand `python -m lab.arena_hosted run` y subir el bundle nuevo
   al mismo servicio/volumen, región y una réplica. Sin marcador no arranca worker;
   sí puede verificar y crear el nuevo respaldo comprimido.
4. Como UID10001 ejecutar `python -m lab.arena_hosted upgrade-storage
   --cutover-confirmed`. El comando exige writer detenido, lock, origen exacto
   `1a1d3b9e25cf376d33f49571545616972eac67e4`, mismo plan y tarifas. Verifica
   integridad completa de inputs/capturas, conciliación financiera y tarifas.
5. En transacción cambia solo las pruebas de código del manifiesto y de la
   política de tarifas, añade storage_recovery y evento de migración. Cancela
   cotizaciones pendientes sin inventar fills durante el hueco. Conserva demás
   campos de wallets, tablas históricas, capital, fechas iniciales y cortes de fees.
   Comparar hashes/filas antes y después; reintento debe ser idempotente.
6. Activar mediante el comando habitual `lab.arena_hosted activate
   --cutover-confirmed`, que vuelve a verificar identidad, tarifas e integridad.
   No editar SQLite ni reactivar con un SQL suelto. Esperar un ciclo natural,
   verificar una sola instancia, frescura, auth, conciliación y archivos instalados.
7. Verificar respaldo comprimido remoto y restauración local inactiva; después
   registrar un nuevo corte válido del controlador, conservando todos los bloqueos.

No reiniciar balances ni contar el intervalo caído como parte de 28 días continuos.
No fabricar operaciones para probar recuperación o atribuir rentabilidad a esta
corrección. Guardar código → paquete → despliegue → migración → lectura/restore.
