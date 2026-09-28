# AVAX: disponibilidad spot de referencia verificable

Evidencia consultada el **28-sep-2026 UTC**. Este documento no contiene rendimientos ni aprueba una estrategia. Sustenta una política de disponibilidad que debe quedar preregistrada antes de aplicarse a otra comparación.

El [anuncio oficial de Binance](https://www.binance.com/kk-KZ/support/announcement/detail/202d37b746bf46e3ae72b256799007ea), publicado el 22-sep-2020, fija la apertura de AVAX/BTC, AVAX/BNB, AVAX/BUSD y AVAX/USDT a las **06:30 UTC del 22-sep-2020**. La ruta inglesa respondió 429 durante la consulta; la página oficial kk-KZ conserva el texto original en inglés. El dato relevante es la apertura anunciada del mercado, no la fecha de lanzamiento de la red.

Se verificaron dos archivos del repositorio público oficial de Binance:

| Archivo spot | Evidencia observada | SHA256 del ZIP, igual al CHECKSUM oficial |
|---|---|---|
| [AVAXUSDT diario, septiembre de 2020](https://data.binance.vision/data/spot/monthly/klines/AVAXUSDT/1d/AVAXUSDT-1d-2020-09.zip) | 9 velas, del 22 al 30 de septiembre; todas con volumen y operaciones positivos | `5bcb42ce41a691f29c2a9cad5ae4f2ddf6bdd04e16dcf8214da23630e4f31c39` |
| [AVAXUSDT por minuto, 22-sep-2020](https://data.binance.vision/data/spot/daily/klines/AVAXUSDT/1m/AVAXUSDT-1m-2020-09-22.zip) | 1,050 velas; la primera abre a las 06:30 UTC y tiene volumen y operaciones positivos | `b9b4cee0befd006126bc8a7ea7a35f7f658f2ab2808a0e0c31a67129ed369497` |

Las consultas de ambos ZIP y sus CHECKSUM respondieron HTTP 200. El primer cierre diario corresponde a **2020-09-22 23:59:59.999 UTC**. Su apertura etiquetada a las 00:00 delimita el intervalo diario; no demuestra negociación antes de las 06:30. La [documentación oficial](https://github.com/binance/binance-public-data) identifica estas velas como datos spot procedentes de `/api/v3/klines`, describe sus columnas y advierte que los archivos históricos pueden revisarse.

La evidencia estructurada está en [avax_spot_availability.json](avax_spot_availability.json), SHA256 **`b6483adcc33ea32a162e9cd4dad52224714832a8d3abf9aff5dc55ca93848850`**. Incluye URLs, fecha de consulta, hashes de ZIP/CSV/CHECKSUM y detalles de la corroboración por minuto. Se conserva el [CSV diario oficial exacto](AVAXUSDT-1d-2020-09.csv), sin encabezado ni modificación de sus bytes, SHA256 `ba0fd51da88d5fe9c03c21c351e86076d37f9044316477c55aa4964af3fc21e2`. El CHECKSUM diario descargado tiene SHA256 `3b7af6451208e58eeb77118c6973b90c0f0fbb67a63d931c68aff8a7e9145b21`; su texto completo está en el JSON. No se conservaron localmente los ZIP ni el CSV por minuto.

## Regla propuesta para el siguiente preregistro

```json
{
  "asset": "AVAX",
  "available_from": "2020-09-22",
  "evidence_sha256": "b6483adcc33ea32a162e9cd4dad52224714832a8d3abf9aff5dc55ca93848850"
}
```

1. Conservar el panel original y fijar su SHA256. Verificar también los bytes del archivo de evidencia contra el hash de la política.
2. En una copia derivada, convertir a ausente únicamente AVAX en fechas anteriores al 22-sep-2020. Registrar en cuarentena cada valor original no ausente, con fecha, activo y motivo. Para el panel de la primera corrida corresponden las observaciones del 13 y 14 de julio; no se modifica aquel panel ni se aplica aquí la transformación.
3. Conservar exactamente todos los precios posteriores al corte y todos los demás activos. No rellenar huecos, no interpolar, no sustituir precios y no mover fechas de evaluación, capital, estrategias, costos o criterios.
4. Mantener las 250 observaciones válidas requeridas para elegibilidad y el uso de señales al cierre para la decisión siguiente. Con cierres continuos desde el 22-sep-2020, el cierre 250 corresponde al 29-may-2021. No contar los puntos de julio como historia spot verificada por esta política.
5. Rechazar cualquier nuevo hueco interno posterior a la disponibilidad. Conservar la primera corrida fallida y registrar de forma independiente el dataset derivado, la cuarentena y su hash.

`lab.research_data.apply_availability_policy(prices, policy)` implementa solo esa transformación pura y su auditoría. No abre archivos, no descarga, no calcula resultados ni certifica por sí mismo que exista el archivo cuyo hash recibe. La verificación del archivo y el registro durable corresponden al ejecutor antes de cualquier simulación.

## Alcance y límites

- **Binance no es Bitso.** Esta fecha verifica un mercado spot de referencia, no el listado histórico de AVAX en Bitso ni la ejecutabilidad del bot en aquella fecha.
- **USDT no es USD.** El CSV AVAXUSDT sirve como evidencia de disponibilidad. Sus precios no se insertan en el panel USD ni se supone una conversión 1:1.
- La evidencia no demuestra la inexistencia de otros mercados spot o de IOUs anteriores. Los puntos de julio se clasifican como no verificados para esta política, no como datos falsos o IOUs demostrados.
- El ZIP diario declara modificación el 22-jun-2021. Verifica acontecimientos históricos, pero no acredita que ese archivo concreto estuviera disponible durante cada decisión pasada. Se conserva la distinción entre fecha del mercado, publicación y captura actual.
- El precio USD después del corte conserva las limitaciones de procedencia del pipeline original. La corrección de disponibilidad no reconstruye la procedencia de cada observación ni los listados históricos de todo el universo.
- La fecha se fija por anuncio y archivo spot, antes de observar resultados de la comparación. No se prueba más de un corte para escoger el de mejor rendimiento. Cambiarla requiere otra política explícita.
