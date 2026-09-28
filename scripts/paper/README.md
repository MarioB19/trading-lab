# Programación experimental retirada

**`aggressive-v2` queda archivado por fallar los siete criterios preregistrados.**
Este paquete ya no es una vía de instalación o continuidad operativa. La ruta
actual corresponde al runtime baseline en modo paper, según el
[runbook operativo](../../docs/GCP_RUNBOOK.md).

`run.sh` termina incondicionalmente con código 2 antes de cargar `common.sh`,
consultar precios o invocar Docker. Una imagen válida, una marca manual antigua,
un timer instalado o argumentos adicionales no reactivan este script. La prueba
`tests/test_experiment_retirement.py` verifica esa denegación con release y marca
coherentes, y con Docker y preflight señuelo que no deben ejecutarse.

No instalar, iniciar ni habilitar los servicios o timers de este paquete. Si
existiera una instalación antigua, el operador debe detener y deshabilitar los
tres timers y los servicios experimentales, comprobar que no quede contenedor
escritor y retirar la marca `/etc/trading-lab-paper/aggressive-v2.enabled`.
Actualizar el script instalado a esta versión bloqueada. No borrar locks, bases
o respaldos. La ausencia de nuevas observaciones es esperada para un experimento
archivado; no mantener su timer de salud como si fuera una cartera activa.

Se conservan los scripts, units, plan, preregistros, código científico, resultados,
imagen y atestación anteriores para auditar el trabajo realizado. También se
conservan la única observación paper, su respaldo y el restore verificado. No
liquidar virtualmente las posiciones ni reiniciar contadores para cerrarlo: el
archivo de evidencia conserva lo que realmente se observó.

Para mantenimiento histórico, usar las rutas explícitas de `lab.paper_ops
inspect`, `verify-backup`, `backup` y `restore` descritas en
[PAPER_OPERATIONS.md](../../docs/PAPER_OPERATIONS.md). Restaurar sólo a un destino
vacío sin programación. Esto no autoriza ejecutar `run.sh` ni reanudar el
experimento. Los wrappers históricos `backup.sh` y `healthcheck.sh` se conservan
como código de referencia; no reinstalar su programación.

El bloqueo retira el flujo operativo preparado; no revoca por medios técnicos una
imagen histórica en manos de quien decida invocar manualmente su CLI. Esa imagen
es evidencia archivada, no una release operativa vigente. Una hipótesis nueva
requiere otro preregistro, evaluación completa y decisión explícita. Acumular 28
días ahora no revierte el rechazo de la candidata.

El control superó a esta candidata en esta comparación retrospectiva. Eso no lo
certifica como el mejor algoritmo ni como preparado para dinero real. Se mantiene
paper; conexión, conciliación y aceptación operativa siguen siendo comprobaciones
independientes.
