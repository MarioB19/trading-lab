---
protocol_version: 1
status: approved
approved_by: Brandon
approved_at_utc: '2026-09-30T02:15:33.141052+00:00'
experiment_id: rotation-paper-v1
hypothesis: El margen fijo de sustitución 15% reduce rotación sin empeorar resultado
  neto o caída frente al control fijo de margen cero en observación prospectiva aislada.
evaluation_window: Desde primera observación futura de reloj real; al menos 28 días
  completos transcurridos, 28 fechas observadas y continuidad de cierres cripto. No
  contar históricos, rellenar días ni mover fechas.
config_sha256: 5a700b6113c049a50ee8ac9b45366391514c46ed43eb30ff3503f75c8e4cf0e3
variant_ids:
- crypto:2b12bfad2351b6e2494a
- crypto:29cdff1eb71e3ac7c4ba
criteria:
  walk_forward: Mismos parámetros que rotation-v2; no optimización adicional. Comparación
    prospectiva después de la elección retrospectiva explícita.
  placebo: Prueba histórica rotation-v2 fija p<0.05 verificada; no reestimar o retocar
    umbral durante paper.
  bootstrap: 'Rotation-v2: 2000 bloques de 30 días, superioridad retorno/Sharpe >=80%;
    artefactos fijos verificados.'
  cost_stress: 'Rotation-v2: no inferior con costo0.60%; paper constantes0.45% cripto
    y0.05% ETF. No se afirman fills reales del libro.'
  drawdown: Caída prospectiva candidata no peor por más de1pp; kill45% cripto/25%
    stocks sin relajación.
  paper: 28 días completos observados y transcurridos, sin huecos/incidencias; resultado
    neto no inferior, rotación <=85% control, libro/cola/ejecución operable deben
    validarse antes de promoción. Nunca activa dinero real.
---

# Preregistro — observación prospectiva de menor rotación

Etapa prevista en el plan autorizado por Brandon. La selección se basa en rotation-v2, retrospectivo ya inspeccionado, que superó sus ocho criterios; los hashes exactos de sus artefactos y los parámetros se congelan antes de observar el periodo futuro. No se declara un histórico nuevo ni se cambian los criterios del ensayo terminado.

Dos carteras exclusivamente virtuales de US$1,000, US$500 por bloque, independientes de Railway y de cualquier cuenta. Control y candidata conservan exactamente top5/vol40%, universo16, límites y SPY/IEF60/40. Único cambio rotation_buffer0.15. Usa lab.portfolio y lab.bot.run_sleeve compartidos, con SimBroker y entradas públicas comunes congeladas. No carga .env, llaves ni fábricas de broker. No modifica config.yaml o state/. Mantiene retirado aggressive-v2.

Cierres previos sólo calientan señales. Cada observación usa el reloj actual y cierre completo; reintentos son idempotentes y no aumentan días. Preservar originales, capturas, SQLite, logs y backups. No se reconstruyen retrospectivamente decisiones omitidas ni se simulan 28 días como si hubieran transcurrido.

Ejecutor local separado y paquete de código congelado con prueba de ancestro Git. Se observan disponibilidad/frescura de Kraken/Bitso y Yahoo actuales; eso no resuelve listados históricos ni cola maker. El costo sigue siendo supuesto, no una medición real de fills. El resultado máximo es evidencia para revisión humana: no modifica el bot operacional, nunca habilita live y requiere validación operable antes de promoción.

Al finalizar: conservar control si fallan criterios o continuidad. Si pasan, revisar evidencia completa y equivalencia de ejecución antes de cualquier decisión de promoción. No retocar parámetros, reiniciar cartera ni cambiar identidad de código para rescatar un resultado.
