# Conectar una cuenta sin activar operaciones reales

Fecha de revisión: 2026-09-28. Esta guía prepara una conexión de **consulta**. El runtime y el despliegue GCP siguen admitiendo exclusivamente `paper`. Conectar una cuenta real al diagnóstico no cambia esa configuración ni inicia el bot.

## Qué funciona ahora

`lab.account_readiness` consulta una lista cerrada de endpoints GET. No carga `.env`, no lee las variables operativas del bot, no importa su estado, no crea bases de datos y no consulta ni envía órdenes. Tampoco realiza transferencias. No sigue redirecciones ni utiliza credenciales de `.netrc` o proxies del entorno.

| Consulta | Entorno y servidor | Rutas permitidas |
| --- | --- | --- |
| Alpaca paper | `https://paper-api.alpaca.markets` | `/v2/account`, `/v2/positions` |
| Alpaca real | `https://api.alpaca.markets` | `/v2/account`, `/v2/positions` |
| Bitso real | `https://bitso.com` | `/api/v3/account_status/`, `/api/v3/balance/` |

Alpaca separa servidores y credenciales de paper y real. Bitso usa su servidor de producción para estas consultas; el diagnóstico no implementa un sandbox privado de Bitso. El paper cripto actual utiliza dinero ficticio, internamente o contra un libro público. Fuentes: [autenticación Alpaca](https://docs.alpaca.markets/us/docs/authentication), [entornos Bitso](https://docs.bitso.com/bitso-api/docs/set-up-your-testing-environment).

## 1. Elegir qué se va a conectar

Registrar primero proveedor, entorno y propósito: observar una cartera existente, probar Alpaca paper o preparar una futura asignación nueva al bot. La conexión inicial puede hacerse sin decidir que el bot administre las inversiones existentes.

- **Observar inversiones existentes:** usar únicamente el diagnóstico. Las cantidades observadas permanecen externas; no se inicia ningún proceso de trading.
- **Asignar capital nuevo al bot:** requiere una cuenta/entorno identificado, efectivo disponible conciliado y un ledger operativo separado. No basta con cambiar `capital`. El preflight no reserva ni mueve efectivo.
- **Administrar inversiones existentes:** requiere una migración explícita de propiedad que todavía no está implementada. Hasta aprobarla y verificarla, se mantienen fuera del bot.

Nunca usar el patrimonio completo de la cuenta como capital implícito del bloque. Compartir un símbolo —por ejemplo BTC o SPY— no demuestra que esas unidades pertenezcan al bot.

## 2. Preparar acceso de consulta

**Bitso:** en la web de Bitso, abrir el perfil, `API`, `Add new API`, poner un nombre identificable y seleccionar únicamente consulta de saldos e información de cuenta. Usar restricción de IP si se dispone de una salida fija. Completar el segundo factor y guardar la clave y el secreto en un gestor de secretos; el secreto se muestra una vez. No habilitar compra/venta, retiros ni cambios de seguridad para este diagnóstico. La API de información de cuenta devuelve `client_id`, necesario para verificar identidad; si no está disponible, el resultado será parcial y no se sustituye por un hash de la clave. Fuentes: [crear una API key y permisos](https://support.bitso.com/hc/en-us/articles/4415097148948-Create-an-API-key-on-Bitso), [estado de cuenta](https://docs.bitso.com/bitso-api/docs/get-account-status).

**Alpaca:** comenzar con las credenciales de una cuenta paper. Una clave de Trading API puede tener facultades de operación: hacer sólo GET desde este programa **no prueba** que la clave sea de sólo lectura. Si ya se dispone de una integración OAuth registrada, Alpaca permite acceso de lectura sin solicitar el scope `trading`; el diagnóstico acepta su token, pero no implementa el alta de la aplicación, el consentimiento, la obtención del token ni la comprobación de sus scopes. No usar documentación de credenciales de Broker API como si describiera los permisos de una cuenta individual de Trading API. Fuentes: [autenticación](https://docs.alpaca.markets/us/docs/authentication), [OAuth y scopes](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api).

El acceso privado de Bitso usa firma HMAC y Nonce v2: milisegundos más seis dígitos aleatorios. El adaptador operativo también fija este formato; no depende del nonce por defecto de CCXT. Fuentes: [firmas](https://docs.bitso.com/bitso-api/docs/create-signed-requests), [Nonce v2](https://docs.bitso.com/bitso-api/docs/nonce-v2-rollout).

## 3. Comprobar el programa sin credenciales

Desde la raíz del repositorio, con el entorno del proyecto instalado:

```sh
.venv/bin/python -m lab.account_readiness --broker alpaca --environment paper
.venv/bin/python -m lab.account_readiness --broker bitso --environment real
```

Estos comandos son offline por defecto. Devuelven `status: not_connected`, los nombres de variables requeridas y si hay credenciales de auditoría presentes. No imprimen sus valores. `--environment real` sólo selecciona el destino de una posible consulta; no cambia `mode`.

Variables exclusivas del diagnóstico:

| Proveedor | Variables |
| --- | --- |
| Alpaca | `TRADING_AUDIT_ALPACA_KEY_ID`, `TRADING_AUDIT_ALPACA_SECRET_KEY` |
| Alpaca OAuth, alternativa al par anterior | `TRADING_AUDIT_ALPACA_OAUTH_TOKEN` |
| Bitso | `TRADING_AUDIT_BITSO_API_KEY`, `TRADING_AUDIT_BITSO_API_SECRET` |

No reutiliza automáticamente `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, `BITSO_API_KEY` ni `BITSO_API_SECRET`. Rechaza mezclar token OAuth y claves Alpaca en una misma consulta.

## 4. Hacer una consulta privada de lectura cuando Brandon lo decida

La siguiente opción pide los valores sin eco en una terminal local. Los mantiene en memoria del proceso; no escribe `.env`, historial de shell ni archivos de credenciales. Elegir el proveedor y entorno en las dos líneas indicadas antes de ejecutarla. No pegar secretos en chats ni en argumentos de comandos.

```sh
.venv/bin/python - <<'PY'
from getpass import getpass
import json
from lab.account_readiness import CREDENTIALS, inspect_account

broker = "alpaca"       # "alpaca" o "bitso"
environment = "paper"  # "paper" o "real"; Bitso privado sólo "real"
credentials = {name: getpass(name + ": ") for name in CREDENTIALS[broker]}
report = inspect_account(broker, environment, connect=True, environ=credentials)
print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
credentials.clear()
PY
```

Para OAuth Alpaca, sustituir la construcción de `credentials` por `{"TRADING_AUDIT_ALPACA_OAUTH_TOKEN": getpass("Token de consulta: ")}`. Si el gestor de secretos ya inyecta las variables de auditoría en un proceso temporal, la CLI equivalente añade `--connect` al comando offline correspondiente. El diagnóstico no configura ese gestor ni guarda el resultado.

La salida contiene montos de cartera: aunque elimina nombres, correo, número de cuenta, ID original y secretos, sigue siendo información financiera privada. Revisarla localmente antes de compartirla.

## 5. Interpretar el resultado

- `authentication.verified`: al menos una consulta privada devolvió respuesta válida de transporte; no demuestra permiso para operar.
- `read_only_connection_ready: true` y `status: connected_read_only`: se leyeron y validaron identidad de cuenta y posiciones/saldos de ambos endpoints. Una cuenta bloqueada puede seguir siendo consultable; revisar `blockers`.
- `account.identity.key`: huella opaca del ID del proveedor más proveedor y entorno. Alpaca usa `account.id`; Bitso, `account_status.client_id`. Rotar una API key conserva esta identidad; cambiar cuenta o entorno no.
- `holdings.items`: posiciones o saldos distintos de cero, siempre `owned_by_bot: false`. Bitso diferencia total, disponible y bloqueado; USD, MXN y USDC no se equiparan ni se convierten.
- `capabilities.scope: this_diagnostic_only`: describe las funciones de este programa. `credential_read_only_verified: false` y `order_permissions: not_tested` dejan explícito que no se verificaron las facultades completas de la credencial.
- `ready_for_trading: false` y `live_authorized: false`: permanecen falsos incluso si la lectura fue correcta.

Alpaca proporciona el estado de cuenta y sus posiciones mediante [Account](https://docs.alpaca.markets/us/reference/getaccount-1) y [Positions](https://docs.alpaca.markets/us/reference/getallopenpositions). Bitso documenta los campos total/disponible/bloqueado en [Balance](https://docs.bitso.com/bitso-api/docs/get-account-balance).

Un 401 exige revisar credencial/entorno; un 403 puede dejar sólo lectura parcial; un 429 requiere esperar según el proveedor. No hay reintentos automáticos ni aumento automático de permisos. Una respuesta incompleta, redirección o error numérico no se trata como cartera vacía. Los errores se muestran por categoría, sin copiar cuerpos privados.

## 6. Identidad, propiedad y estado anterior

Los adaptadores ahora verifican un identificador estable del proveedor antes de crear un ledger. Las claves antiguas basadas en huellas de API key se rechazan si aparecen en estado, documentos u órdenes del mismo proveedor/entorno. No hay migración silenciosa ni asignación adicional de efectivo al rotar claves.

El journal mantiene cantidades propias por bloque: comienza con posiciones vacías y sólo incorpora ejecuciones confirmadas registradas por él. También limita la asignación inicial al efectivo disponible que no está asignado a otro bloque del mismo ledger. Eso no acredita liquidación de efectivo, ausencia de órdenes ajenas ni una separación bancaria/subcuenta; se necesita conciliación antes de operar.

No borrar el namespace, reinicializar la base ni editar SQLite para saltar un error de identidad o propiedad. La importación `lab.ops import-legacy` está prevista para estado paper interno, no para adoptar una cartera externa ni convertir su valor en capital.

Para la eventual adopción de inversiones existentes se necesita: manifest revisable con cuenta/entorno, instante y hash de la captura; cantidades y efectivo asignados o excluidos por bloque; revisión de órdenes, ejecuciones y movimientos; aprobación de Brandon; y una migración atómica e idempotente a una base desactivada, con patrimonio, flujo y límites de riesgo coherentes. Si el saldo cambia desde la captura, se debe conciliar de nuevo. Este procedimiento todavía no está implementado y no se sustituye por una edición manual de estado.

## 7. Prueba paper y condiciones de activación manual

La siguiente etapa útil es Alpaca paper externo en un directorio propio, tras verificar identidad y conciliar su efectivo ficticio. El estado del simulador interno actual no se puede reutilizar como propiedad de la cuenta Alpaca. Preparar ese alta/migración explícita antes de cambiar el broker operativo. Bitso puede seguir en simulación pública sin API keys privadas.

Paper sirve para observar horarios, reinicios, fills parciales y recuperación. Sus resultados no acreditan ejecución real: Alpaca documenta diferencias como impacto de mercado, posición en cola y otros costes. [Limitaciones de paper trading](https://docs.alpaca.markets/us/docs/paper-trading).

Antes de considerar dinero real faltan, como mínimo:

1. Conciliación de cuenta real completa y aprobación explícita del alcance: sólo capital nuevo o cantidades existentes asignadas. Incluye órdenes ajenas, efectivo liquidado, ausencia de margen/cortos y mercados disponibles.
2. Ruta revisada de alta/migración de ledger e identidades legacy; no existe un comando genérico de adopción externa.
3. Resolver y probar incertidumbre remota de Bitso: hoy, si se pierde la respuesta sin ID remoto, el journal bloquea y exige conciliación manual. `origin_id` por sí solo no garantiza exactamente una ejecución: su unicidad documentada se limita a órdenes activas. [Orden Bitso](https://docs.bitso.com/bitso-api/docs/place-an-order), [historial de cambios](https://docs.bitso.com/bitso-api/docs/history-of-changes).
4. Conciliación de comisiones efectivas, movimientos, dividendos y acciones corporativas. El adaptador Alpaca no reconcilia automáticamente esos movimientos; una caída de efectivo o unidades frente al ledger debe investigarse.
5. Observar cuatro semanas en paper según el protocolo y probar reinicio, respuesta perdida, partial fill, cierre de mercado, liquidación pendiente y restore. Una conexión GET correcta no cumple estas pruebas.
6. Diseñar, revisar y validar una ruta operativa real separada. `lab.runtime`, la activación con `lab.ops` y el despliegue preparado son paper; no se habilita real cambiando una variable. Mantener un escritor, respaldos verificables, alertas y límites conciliados.
7. Sólo entonces Brandon decide y realiza la activación manual, con credenciales operativas separadas y permisos mínimos. Nunca añadir facultades de retiro, transferencia, margen, futuros o cortos.

No utilizar el bot legacy como atajo alrededor de estos bloqueos. Para la preparación y operación paper GCP, seguir [GCP_RUNBOOK.md](GCP_RUNBOOK.md); para el protocolo de evidencia, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md).
