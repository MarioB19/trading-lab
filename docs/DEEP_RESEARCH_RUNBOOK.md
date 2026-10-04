# Investigación profunda con US$1,000

Estado de preparación al 4-oct-2026: protocolo `cost-aware-v1` aprobado por Brandon y registrado en su propio commit; código listo para la ejecución autorizada. No hay resultados nuevos de mercado ni una estrategia ganadora validada. Capital: US$500 cripto + US$500 ETFs. El runtime operativo y el ensayo `rotation-paper-v1` conservan sus reglas.

Verificación local: **589 pruebas pasan**, incluidas 81 nuevas y tres ejecuciones completas con datos artificiales. [Evidencia de preparación](../reports/operations/deep_research_preparation_20261003.json). No hay corrida nueva de mercado.

## Qué pregunta responde

¿Reducir sustituciones y rebalanceos mejora el resultado de una cartera pequeña después de trading y gastos? Se comparan el control reconstruido y tres alternativas: margen0/banda4pp, margen15%/banda2pp y margen15%/banda4pp. También se calculan BTC pasivo + SPY/IEF 60/40 y efectivo sin interés.

La investigación consta de cuatro piezas:

1. [Ocho fuentes primarias y su aplicación crítica](DEEP_RESEARCH_SOURCES_20261003.md), incluida evidencia que cuestiona las conclusiones favorables.
2. [Auditoría contable y de equivalencia](DEEP_RESEARCH_ENGINE_AUDIT_20261003.md): efectivo financiado, mínimos, precios faltantes, ventanas móviles y eventos corporativos pendientes.
3. [Protocolo aprobado](../reports/cost_aware_v1_preregistro.md) y [plan exacto](../reports/cost_aware_v1_plan.json): umbrales, seis identidades, archivos SHA256, costos y semillas previos a la ejecución.
4. Evaluador registrado: curvas de capital, gastos de 0/5/10/20 USD al mes, años completos, bootstrap emparejado, corrección de las tres comparaciones, placebo incremental y estrés de fricción.

El histórico 2021–septiembre de 2026 ya fue inspeccionado. Este estudio puede descartar una alternativa o justificar investigación adicional; no convierte esos datos en una prueba nueva fuera de muestra. La corrección estadística cubre la familia declarada y el DSR incorpora sólo una reconstrucción parcial de intentos previos.

## Ejecución reproducible

Desde este checkout, con el entorno Python ya existente:

```bash
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.research_multi \
  --deep-profile cost-aware-v1 --describe
```

Ese comando describe parámetros e identidades sin leer precios. Para calcular rendimientos, aplicar primero el [protocolo del repositorio](RESEARCH_PROTOCOL.md): aprobación humana, preregistro aprobado en su propio commit, implementación en un commit posterior y árbol limpio. El SHA debe ser completo y ancestro estricto de HEAD.

```bash
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.research_multi \
  --deep-profile cost-aware-v1 \
  --experiment-id cost-aware-v1 \
  --preregistration reports/cost_aware_v1_preregistro.md \
  --preregistration-commit 55a8fc8fa4fd30c022da5bc9149cd132cf58c10b \
  --input-dir ../trading-lab-mejoras/reports/experiments/rotation-v2/20260930T020623Z-3142e39c/inputs
```

El perfil rechaza opciones de descarga y combinaciones con grids heredados. Cada entrada debe coincidir con el hash declarado. Un cambio de parámetros o de datos exige otro protocolo; no se modifica un umbral después de ver el resultado.

Identidad aprobada: preregistro `55a8fc8fa4fd30c022da5bc9149cd132cf58c10b`, plan `f2e42cd223c0f39c316b2cd709c577dd3ba3d7f49bba7289aa6d2a765c4bc545`. Los resultados y su estado se consultan en el manifiesto de cada corrida; esta guía no sustituye esa evidencia.

## Artefactos y lectura de resultados

La ejecución crea un directorio nuevo en `reports/experiments/cost-aware-v1/<run-id>/`, con manifiesto, copias de entradas, CSV por variante/escenario, placebos individuales, `deep_results.json` y `deep_report.md`. El ledger común conserva intentos iniciados, completados y fallidos.

En el JSON, `retrospective_checks` muestra cada criterio por separado. `shortlisted_for_research_review=true` sólo significa que esa comparación retrospectiva supera los umbrales. `eligible_for_new_forward_validation`, `promoted` y `live_authorized` permanecen falsos porque faltan evidencia de datos y equivalencia. Ningún comando modifica la estrategia o el modo operativo.

Los gastos son devengados diariamente y pagados externamente. Por eso el resultado económico puede ser negativo aunque la cuenta del broker conserve fondos. Si los gastos exceden el patrimonio, se mantiene la pérdida completa en dólares y se marcan como indefinidas las métricas compuestas que cruzarían capital no positivo. Los CSV conservan ese caso; no se elimina el escenario desfavorable.

Bootstrap y placebo incluyen resultados degenerados: un Sharpe indefinido no aprueba un criterio. Las frecuencias de remuestreo no son probabilidades de ganar dinero en el futuro. Los años calendario mantienen continuidad de capital y riesgo; no son un optimizador entrenado en un periodo virgen.

## Qué falta para una afirmación operable

- Históricos de disponibilidad por par Bitso, incluidos suspensiones/deslistados y la última salida ejecutable. La lista actual no demuestra disponibilidad histórica.
- Precio y hora negociables posteriores a la señal, restricciones por libro, redondeos, latencia, fills y costos observables. Un cierre proxy no reproduce una orden.
- Precios nominales y dividendos/splits separados para ETF, con contabilidad idempotente.
- Reconstrucción del estado de selección: una ventana móvil de 720 filas puede cambiar incumbentes aunque la señal sea causal. El diagnóstico reconstruye las 250 observaciones mínimas dentro de cada ventana.
- Un periodo posterior reservado, protocolo propio y observación futura continua de al menos 28 días; ese mínimo operacional no demuestra significancia ni rentabilidad.

Se revisaron conectores disponibles para datos históricos especializados y no apareció uno que resolviera estos requisitos. No se instaló un plugin genérico: documentación, datos congelados y herramientas locales bastan para esta fase. Un proveedor nuevo requiere verificar cobertura histórica real antes de incorporarlo o pagar una suscripción.

Las familias de momentum mensual BTC/ETH y tendencia mensual ETF quedan documentadas como hipótesis posteriores. No se combinan con este estudio ni se prueban hasta revisar antecedentes y registrar un protocolo separado. Si ninguna variante supera sus criterios, el resultado válido es que no hay mejora demostrada.

## Corrección técnica del primer arranque — 4-oct

El primer intento, código `13427fb`, se detuvo al serializar `approved_on` como objeto fecha YAML, antes de crear el manifiesto o leer precios. Se conserva el directorio `20261004T174535Z-2493193d`, su traceback y el evento `run_initialization_failed`. No se iniciaron variantes.

La corrección preserva fechas y timestamps de metadatos como texto al cargar el frontmatter, usando un SafeLoader local. No modifica el archivo aprobado, plan, parámetros, precios ni criterios. Se registra como commit técnico posterior para conservar los tres SHA previos, sin reescribir la evidencia. La comparación se reintenta con el mismo preregistro aprobado y un nuevo identificador de corrida.
