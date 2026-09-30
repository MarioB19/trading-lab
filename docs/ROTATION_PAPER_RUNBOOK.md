# Observación futura de menor rotación

La comparación rotation-v2 superó sus ocho criterios. Se elige margen de 15% para
observación prospectiva; el bot publicado conserva margen cero y ETFs 60/40.
El resultado histórico no autoriza promoción ni demuestra ganancia futura.

Plan fijo: configs/experiments/rotation_paper_v1.yaml. Dos carteras virtuales
independientes, US$1,000 cada una, US$500 por bloque. Sólo cambia el margen de
sustitución; señales y ejecutor son compartidos con el bot. Usa SimBroker,
entradas públicas comunes congeladas y costo constante. No carga .env ni llaves.

Se prepara un bundle dedicado desde un commit limpio, con prueba de ancestro Git
generada por lab.research_attestation, plan/preregistro y manifest/results históricos
verificados por hash. Código del observador queda fijo durante el periodo.
lab.rotation_observer verifica identidad/evidencia antes de descargar precios,
conserva SQLite y capturas, y respalda cada fecha nueva. Los reintentos son
idempotentes. lab.paper_ops verifica y restaura a un destino vacío desactivado.

El instalador scripts/research/install_rotation_observer.py registra un LaunchAgent
de usuario com.tradinglab.rotation-paper-v1, cada 15 minutos. Invoca exclusivamente
el bundle y la base experimental dedicados. Termina la recolección al completar
28 días observados y transcurridos; mantiene su evidencia para revisión. Se puede
consultar el reporte con lab.paper_comparison --status --plan RUTA_PLAN --data-dir
RUTA_PAPER. El agente es local: necesita sesión del usuario y Mac disponible. Paquete, Python, base y backups están en Library/Application Support/Trading Lab y no dependen de Kingston. Suspensión/desconexión puede omitir cierres; los huecos quedan
identificados y no se rellenan retrospectivamente. No es un servicio cloud.

La evaluación prospectiva compara retorno cripto neto, caída máxima (tolerancia
1 punto) y rotación medida por importe operado dividido entre el mismo capital
inicial de US$500; candidata <=85% del control. Esta medida difiere de la rotación
histórica por patrimonio corriente. También exige continuidad, 28 días completos
y cero incidencias. No activa al candidato ni live. La equivalencia de libro,
cola/minimos/latencia y ejecución operable sigue pendiente antes de promoción.

El antiguo aggressive-v2 permanece retirado; su entrypoint, timers e históricos
no se modifican para arrancar este ensayo. Railway no recibe otro worker, cambio
de configuración o despliegue por esta preparación.
