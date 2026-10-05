# Arena de cuatro estrategias

Plataforma local independiente del piloto Railway. Cuatro carteras en BTC/USD,
**US$1,000 ficticios por estrategia, US$4,000 iniciales en total**. Todas son al
contado, sin endeudamiento ni cortos. El capital no se repone al reiniciar.

Contrato: `configs/arena/four_strategies_v1.json`. Protocolo aprobado:
`reports/four_strategy_arena_v1_preregistro.md`, commit local `61c6ac3` anterior
al commit de implementación. No hay push, despliegue Railway ni ruta real.

## Abrir y operar localmente

Desde la raíz de este worktree, con Python y las dependencias del proyecto:

```sh
../trading-lab/.venv/bin/python scripts/arena/local.py start
../trading-lab/.venv/bin/python scripts/arena/local.py status
../trading-lab/.venv/bin/python scripts/arena/local.py stop
```

Panel: http://127.0.0.1:8874/ . `start` verifica preregistro, SHA y árbol limpio,
inicia un servidor y un ejecutor exclusivos de la arena. Un lock impide dos
escritores. `stop` solo termina los PID propios comprobados; conserva saldos.
El Mac debe permanecer encendido, despierto, conectado y con Kingston montado.
No se instaló un LaunchAgent ni se afirma operación continua en la nube.

El panel permite ver y filtrar operaciones, decisiones y cotizaciones, comparar
patrimonio, cambiar periodo y exportar un **resumen** (últimos250 fills,100 decisiones
y hasta400 puntos por cartera; la base conserva todo). Pausar cancela cotizaciones
pero conserva inventario y valoración. Reanudar no reinicia un freno permanente.
El servidor escucha exclusivamente en127.0.0.1, comprueba Host/Origin en controles
y no es una API pública. No usa llaves, `.env`, login de exchange ni órdenes privadas.

## Qué ejecuta

- Scalping: ruptura y EMA9/21 sobre cierres5m,25% objetivo, salidas por señal,
  pérdida1%, objetivo1.5%, dos horas o cambio de díaUTC; hasta seis entradas diarias.
- Swing: reutiliza `lab.portfolio.target_weights`, medias20/50/100/200,
  momentum30/90/180, volatilidad objetivo40%, peso objetivo máximo90%, banda2pp.
- Reversión: z-score20 de cierres horarios, entrada<=−2 y salida>=0;
  25% objetivo, pérdida3% o veinticuatro horas.
- Creación de mercado: compra inicial de inventario25%, cotiza US$25 por lado,
  margen por lado al menos comisión maker+0.10%, inventario objetivo25%/máximo50%,
  sesgo de precio por inventario. TTL60s y latencia mínima1s. Se empieza sin BTC:
  la compra inicial paga costos y aparece en el historial.

Cada cartera tiene freno de caída20% desde máximo y pausa hasta el próximo díaUTC
al perder3% intradía. Son reglas de reacción, no garantías de precio ni pérdidas
máximas. La salida usa profundidad disponible; si no alcanza, el remanente se
conserva para el siguiente ciclo. En pausa manual el inventario permanece expuesto.

Las nuevas familias están declaradas en `SLEEVES.arena_crypto` y se cuentan como
intentos externos adicionales en el Sharpe deflactado de **nuevas** investigaciones
cripto. No se cambian ni recalculan los informes históricos.

## Datos y ejecución

GET públicos de Bitso: `order_book` y `trades`, BTC/USD. GET público Kraken OHLC
para5m/1h/1d, solo velas completas, continuas y frescas. No se afirma que Kraken
sea histórico de Bitso; el proveedor de señal se muestra en el panel. USD se
refiere al mercado de dólares digitales de Bitso, no a una cuenta bancaria USD.

Taker se ejecuta contra niveles visibles, respeta profundidad y efectivo, y paga
0.36%. Maker paga0.30% y únicamente simula fills con trades posteriores que
atraviesan el límite, del lado maker correspondiente, hasta10% de su volumen.
Un toque de precio, un trade anterior o un trade ya usado no bastan. Tras un hueco
mayor de60s o una página truncada que pierde el cursor se cancelan las cotizaciones;
no se reconstruyen fills faltantes. Las tarifas son supuestos del piloto, no
una confirmación del nivel de comisiones de una cuenta. No se simula prioridad
real en la cola; el libro público no acredita fills privados.

Las carteras son alternativas independientes, sin capital compartido. Cada una
simula contra la misma información pública, no contra un libro conjunto modificado
por las órdenes de las otras tres. No se usa margen ni inventario negativo.

## Persistencia y verificación

Base exclusiva: `runtime-data/arena-paper/arena.sqlite3`. No usar el directorio
del piloto ni editar SQLite a mano. Todo el ciclo (captura, cuatro libros, fills,
decisiones e historia) se confirma en una transacción. Los datos de velas se
comprimen y deduplican por hash. Una captura repetida o anterior no repite órdenes.
Errores conservan saldos y cancelan cotizaciones; el panel indica falta de frescura.

```sh
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.arena status
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.arena audit
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.arena backup --file /ruta/nueva/arena.sqlite3
PYTHONPATH=src ../trading-lab/.venv/bin/python -m lab.arena restore --file /ruta/arena.sqlite3 --directory /ruta/vacia
```

La auditoría verifica hashes de velas/capturas y reconstruye efectivo, inventario
y fees desde fills. El respaldo SQLite es consistente aunque el ejecutor esté
activo. La restauración exige destino nuevo y no inicia ningún proceso. Ninguna
prueba equivale a un respaldo externo automático; se necesita operación posterior.

La demostración artificial solo existe en tests mediante bases `kind=synthetic`,
separadas de paper. Una base paper exige preregistro aprobado, ancestro estricto,
plan idéntico y código limpio antes de **cada** ciclo. Cambiar código detiene
el experimento hasta una nueva decisión/versionado; no congelar otro SHA para
continuar la misma base sin una migración explícita.

## Límites de la entrega

Implementación y operación local no demuestran ganancia. El panel muestra P&L
neto de ejecución, antes de infraestructura e impuestos, sin rentabilidad esperada.
Los cuatro enfoques son versiones concretas de sus familias; no representan todos
los algoritmos posibles ni sistemas profesionales de alta frecuencia. Scalping
opera con cierres5m, no con latencia de milisegundos.

No se corrieron backtests ni se eligieron parámetros mirando resultados. Las
cuatro ventanas futuras, equivalencia operable, placebo, bootstrap y validación
independiente continúan pendientes. Veintiocho días transcurridos no prueban
continuidad ni rentabilidad. No existe botón para promover a dinero real.

Las funciones causales de señales están en `lab.portfolio.arena_directional_signal`,
compartidas por el ejecutor y cualquier validación posterior; no se duplican fórmulas.
