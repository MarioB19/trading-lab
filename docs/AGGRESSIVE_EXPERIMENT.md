# Cartera experimental agresiva: preparación y comparación

Estado previo a la primera corrida: **protocolo y commits locales confirmados por Brandon el 27-sep CDMX / 28-sep UTC**. La comparación se ejecutará después de registrar el preregistro y el código; el paper prospectivo aún no se inicia. El bot actual conserva su configuración. La integración GCP sigue pendiente de la conexión posterior.

## Qué se comparará

| | Control | Experimental |
|---|---|---|
| Capital ficticio inicial | US$1,000 | US$1,000 |
| Cripto / ETF inicial | 500 / 500 | 500 / 500 |
| Máximo de criptos | 5 | 3 |
| Volatilidad objetivo anual cripto | 40% | 60% |
| Peso objetivo máximo por cripto | 40% | 40% |
| ETFs | SPY 60% / IEF 40% | Igual |
| Filtro BTC y freno | Vigentes | Iguales |
| Kill switch cripto / ETF | 45% / 25% | Igual |
| Cadencia / apalancamiento | Diaria / ninguno | Igual |

El objetivo de volatilidad no es una tasa de ganancia. Comparar cuentas con el mismo inicio evita atribuir a la estrategia diferencias de capital, precio de entrada o posiciones previas. No se copian ni se transfieren inversiones del bot actual; son cuatro ledgers internos, dentro de una base exclusiva del ensayo.

Configuración completa en `configs/experiments/aggressive_v1.yaml`; protocolo con hash, IDs, semillas y umbrales en `reports/aggressive_v1_preregistro.md`. La candidata ya existía entre las variantes históricas: esta reevaluación no es un holdout virgen ni una selección de la mejor curva.

## Qué cuenta como mejora

La comparación primaria es el bloque cripto. El total con ETFs idénticos se informa también, sin mover capital entre bloques.

- CAGR neto al menos **3 puntos porcentuales** mayor al control y Sharpe no inferior.
- Caída máxima no más de **5 puntos** peor al control y no peor de **−50%**.
- Al menos tres años completos y ventaja de retorno en al menos la mitad de ellos. Parámetros fijos, sin reiniciar capital, máximos o kill switch cada enero.
- Bootstrap emparejado: 2,000 réplicas, bloques de 30 días; frecuencias de retorno y Sharpe superiores de al menos 80%. No son probabilidades de ganancias futuras.
- Placebo de timing: 200 desplazamientos y p finito menor de 0.05. Este gate no demuestra por sí solo superioridad frente al control.
- Costo cripto base **0.45% por lado**, no inferioridad de CAGR y Sharpe con **0.60%**; **1%** es un estrés informativo. El modelo de ETF usa 0.05% por lado.

Todos los criterios deben quedar visibles aunque fallen. Si una regla falla, su estado es no aprobada; cualquier cambio de hipótesis se registra con otro ID antes de repetir. No se promueve la cartera automáticamente.

## Primera comparación histórica

Preparación sin descargar datos ni calcular rentabilidad:

```bash
python -m lab.aggressive_research --describe
```

El preregistro aprobado debe guardarse en **su propio commit**, seguido por el commit del código que se ejecutará, incluyendo la base técnica GCP. Brandon autorizó estos commits y la primera comparación; push y despliegue permanecen fuera de esta autorización. El gate valida contenido exacto, hash, variantes, ancestro y árbol limpio antes de cargar datos.

Después, con los commits autorizados:

```bash
python -m lab.aggressive_research --preregistration-commit SHA_COMPLETO_DEL_PREREGISTRO
```

Conserva manifiesto, datasets congelados, curvas, costos, comparación JSON/Markdown y ledger en `reports/experiments/`. El periodo histórico está fijado a 2021-01-01..2026-09-26, usando historia de señales desde 2019. Los máximos y kills son continuos. No sobrescribe informes anteriores.

## Paper prospectivo separado

Se usa `lab.paper_comparison` con un directorio exclusivo, por ejemplo `/tmp/trading-aggressive-paper` para un ensayo local o un volumen persistente dedicado para observación prolongada. Nunca `state/`, el volumen del runtime principal ni una carpeta que contenga su base/flag de activación.

```bash
python -m lab.paper_comparison --describe
python -m lab.paper_comparison --status --data-dir /tmp/trading-aggressive-paper
```

El runner verifica el mismo preregistro antes de calcular. Admite dos paneles CSV de cierres compartidos, con fecha ISO en la primera columna, o captura pública cuando se usa `--fetch`. La misma captura de cada mercado se aplica a ambas carteras. Las transacciones guardan el par completo: un fallo no publica una cartera con la otra atrasada.

```bash
python -m lab.paper_comparison --once \
  --preregistration-commit SHA_COMPLETO_DEL_PREREGISTRO \
  --data-dir /tmp/trading-aggressive-paper --fetch
```

Alternativa con entradas explícitas:

```bash
python -m lab.paper_comparison --once \
  --preregistration-commit SHA_COMPLETO_DEL_PREREGISTRO \
  --data-dir /tmp/trading-aggressive-paper \
  --crypto-prices /ruta/crypto_closes.csv --stocks-prices /ruta/etf_closes.csv
```

No importa `.env`, no crea brokers privados, no envía órdenes y no recibe llaves. El capital es ficticio. Cada compra/venta se simula al cierre con comisión y deslizamiento modelados: **no prueba profundidad, prioridad maker o fills reales**. Los CSV deben contener cierres completos, historia suficiente y los activos requeridos; una vela futura o una revisión incompatible se rechaza.

El runner no instala un cron ni conecta GCP por ejecutarse una vez. La programación continua se habilitará cuando exista un entorno persistente elegido; mantenerla separada del ejecutor principal y de sus credenciales. El modo CSV registra procedencia declarada por el operador; eso no certifica por sí mismo autenticidad del proveedor.

### Conexión GCP posterior

El seguimiento ejecutable de esta entrega requiere un checkout Git limpio con el preregistro como ancestro. La imagen GCP incluye el plan y permite `--describe`/`--status`, pero **`--once` permanece bloqueado dentro de esa imagen**, porque no contiene Git ni su historial. No hay un bypass del preregistro.

Antes de programarlo en GCP se necesita una prueba de preregistro generada por CI y vinculada al commit y digest de la imagen, validada por el runner; o un entorno de investigación reproducible que conserve la verificación Git. Este trabajo de despliegue sigue pendiente. Usar un volumen separado, por ejemplo `/var/lib/trading-lab-paper/aggressive-v1`, con respaldo y programación propios, sin montar el estado ni las credenciales del bot principal. El build Docker general sigue pendiente por el error de espacio documentado en `VALIDATION.md`; la prueba de imagen declarada en CI todavía no es evidencia de un build logrado.

## Cuándo puede revisarse para promoción

Los backtests ya vistos no se cuentan como observación nueva. El paper debe acumular al menos **28 días completos desde su primer ciclo real**, con días observados, continuidad, datos completos y errores resueltos. Una pasada única o importar un CSV de un mes no cumple el periodo. Cuatro semanas prueban funcionamiento, no significancia estadística ni rentabilidad futura.

Un salto de decisiones diarias queda como incidencia durable del ensayo y evita marcarlo completo. Reintentar o cargar después las velas ausentes no convierte ese periodo en seguimiento prospectivo continuo.

La conclusión máxima será una candidatura para revisión humana. El modo actual no cambia y el acceso a dinero real continúa siendo decisión/acción manual exclusiva de Brandon.

## Limitaciones y trazabilidad

El histórico usa el subconjunto Bitso conocido en 2026, sin una reconstrucción completa de fechas de listado/deslistado. Los datos de investigación y el modelo de ejecución no reproducen todas las restricciones del bot. No se certifica un DSR global de todas las exploraciones pasadas. La evidencia debe distinguir rentabilidad retrospectiva, ejecución modelada, paper observado y broker externo.

El histórico no reproduce mínimos/tope por orden ni `max_price_jump`; esas reglas sí se conservan en el runner paper. Rechaza huecos internos de valoración desde el primer precio observado, para no simular una venta a un precio inexistente. Si la cobertura de los activos declarados es insuficiente, la comparación falla: no se eliminan monedas para mejorar el resultado.

Pruebas técnicas con datos sintéticos verifican causalidad, aislamiento, identidad, idempotencia y criterios de decisión. No sustituyen la comparación de mercado ni autorizan resultados inventados.

## Verificación local — 27 de septiembre de 2026

- Suite completa: **203 pruebas pasaron** en 50.05 s, incluidas 67 nuevas del plan, comparación y runner paper.
- Replay de consistencia de la regla vigente, 365 días: diferencia máxima bot/backtest **0.458%**, menor al límite de 2%. No es un resultado de la candidata.
- Ambos comandos `--describe` entregan el mismo SHA256 del protocolo: `4d7d97add8f79e86d5dd942691cf99ad4d0bac030508c3cff427fb66ac86886e`.
- Importación del runner paper y lectura del plan verificadas sin SciPy/sklearn. No equivale a una imagen Docker construida.
- `git diff --check` sin errores; `config.yaml` y `state/` sin diferencias frente al estado sincronizado `12a54c296d41e960ccc35f311979fa7ddb3dc060`.
- Estas pruebas preceden a la primera corrida de mercado. El preregistro ya está aprobado; el registro de la ejecución documentará su SHA y el del código. Todavía sin observaciones prospectivas ni despliegue.
