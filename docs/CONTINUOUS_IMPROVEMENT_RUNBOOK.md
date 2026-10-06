# Mejora continua diaria

Controlador implementado en `lab.continuous_improvement`; protocolo
`reports/continuous_improvement_v1_preregistro.md`, commit previo
`e0a3d3e74d318c098e2c80b61d759e4e9e203cf2`. El objetivo es mejorar el resultado
neto mediante evidencia de ejecución, problemas corregibles y experimentos
separados. No promete ganancias ni modifica diariamente los parámetros del bot.

## Ciclo y memoria

1. Recoger piloto y arena por Railway SSH oficial. GET autenticado y SQLite
   `mode=ro`; la credencial permanece en Railway y no se imprime ni descarga.
2. Validar modo paper, frescura, identidad instalada, salud, conciliación y
   cercanía temporal. Si falla una fuente, el diagnóstico se bloquea; no inventa
   valores ni continúa una investigación usando datos incompletos.
   Un ciclo `running` es normal si ready=true y no hay errores. Ante un bloqueo,
   `collect-run` hace una segunda lectura como máximo y conserva ambos cortes.
3. Atribuir ciclos completos de la arena: resultado por precios, fees y neto.
   Un ciclo abierto no es una victoria; patrimonio neto no vuelve a restar fees.
   Leer todos los fills del corte por su conteo transaccional; el límite de 250
   movimientos del panel no se usa para reconstruir inventario ni ciclos.
4. Priorizar integridad/calidad, inversión de ganancias brutas por costos,
   falta de ejecuciones maker y cobertura de evidencia. Usar siete días para
   ciclos y contar persistencia por fechas únicas, no por número de reintentos.
5. Conservar snapshot, reporte y cadena de hashes. Los reintentos idénticos no
   duplican eventos; cortes nuevos del mismo día quedan como revisiones y no
   aumentan el número de días observados.

El signo del resultado diario no cambia la prioridad por sí solo. El aprendizaje
del controlador es una memoria de problemas y evidencia, no un modelo que
predice precios o decide capital. Una tarea puede quedar en observación; no es
obligatorio generar otra variante o editar código cada día.

## Ejecutar

Desde este checkout:

```bash
bash scripts/research/run_continuous_improvement.sh
```

Archivos privados, fuera de Git y del runtime operativo:

```text
runtime-data/continuous-improvement-v1/
  ledger.jsonl
  snapshots/<hash>.json
  reviews/<hash>.json
  latest.json
  latest.md
  candidates/<hash>.json
  decisions/<hash>.json
```

La cadena detecta alteraciones; no es firma criptográfica ni reemplaza un backup.
Un hash de artefacto confirma su integridad, no la verdad de sus afirmaciones.
La copia externa automática de estos datos y los runtimes sigue pendiente.

## Candidatas y evaluación

El registro necesita un JSON con `experiment_id`, `mode: paper`,
`live_authorized: false`, `variants` (ID, sleeve y params exactamente presentes
en el grid `SLEEVES`) y `evaluation` (holdout_start, holdout_end,
final_evaluation_at con zonas horarias). Su preregistro propio debe estar aprobado,
comprometido antes del código y fijar ese JSON mediante config_sha256. La fecha
reservada debe ser futura, con al menos 28 días. El árbol debe estar limpio.

```bash
bash scripts/research/run_continuous_improvement.sh register \
  --config configs/experiments/CANDIDATA.json \
  --preregistration reports/CANDIDATA_preregistro.md \
  --preregistration-commit SHA_COMPLETO
```

Máximo dos candidatas activas; al menos siete días entre nuevos ensayos. Los IDs
no se reutilizan y todos los intentos cuentan. Registrar no ejecuta el ensayo.
La corrida se hace mediante el motor científico propio y su protocolo; el
controlador no inventa un backtest ni usa como candidata un diagnóstico de fees.

Antes de final_evaluation_at devuelve `collecting_until_declared_evaluation`
sin leer los artefactos de significancia. Después acepta un manifiesto en
`reports/experiments/<candidate_id>/` con candidate_id, artifacts (rutas relativas
y hashes SHA256), validation y paper (nombres incluidos en artifacts).

```bash
bash scripts/research/run_continuous_improvement.sh review \
  --candidate-id CANDIDATA \
  --manifest reports/experiments/CANDIDATA/evidence_manifest.json
```

Validación: config/code/run exactos, periodo reservado, fecha de evaluación final
y `evaluation_count: 1`, corrección por intentos, checks de walk_forward, placebo,
bootstrap, cost_stress, drawdown, causality, multiple_testing,
execution_equivalence y unseen_holdout. Paper: 28 días completos y observados,
continuous=true, sin observation_gaps, incidencias resueltas y mismas identidades.
El manifiesto conserva las métricas y provenance que justifican cada check; los
booleans sin sustento no constituyen evidencia científica.

El veredicto final se registra una sola vez. La salida máxima es
`ready_for_human_review`; nunca despliega, cambia config.yaml, reinicia capital,
desactiva frenos ni opera dinero real. La revisión diaria no realiza evaluaciones
estadísticas repetidas hasta encontrar un resultado favorable.

## Seguimiento diario con Codex

Se programa esta conversación a las 08:30 CDMX. Ejecutar el comando, revisar la
mayor prioridad y completar una acción respaldada por evidencia: verificar datos,
mejorar una medición, corregir un fallo técnico reproducible en la rama aislada,
o redactar un protocolo de candidata. Las modificaciones de código requieren
pruebas, trazabilidad y commit local; el controlador conserva su preregistro.

Mantener separados propuesta, implementación, pruebas, ejecución y despliegue.
No generar cambios para cumplir una cuota. Avisar solo de una mejora comprobada,
un bloqueo nuevo o una candidata lista para revisión. No enviar mensajes externos.

Es una automatización local: necesita Mac encendida, Codex abierto y KINGSTON
disponible. Railway sigue operando y recogiendo datos independientemente; el
trabajo de investigación de Codex no se ejecuta si el entorno local falta.

Fuente: [documentación oficial de automatizaciones](https://learn.chatgpt.com/docs/automations?surface=app).
