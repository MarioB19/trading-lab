---
protocol_version: 1
status: approved
experiment_id: h7c-sombra-exchanges
type: externo (medición de costo hacia adelante; no cambia el bot)
approved_by: Brandon pidió la simulación el 2-nov-2026 (23:41 CDMX); Claude la diseña con la autonomía acordada el 25-oct-2026 (DEC-030)
date: 2026-11-03
---

# H7c — Sombra de ejecución: las órdenes del piloto contra los libros de Binance y OKX (preregistro)

Pedido por Brandon tras la investigación externa del 2-nov (`reports/investigacion_externa_2026-11-02.md`): decidir
exchange para dinero real con datos propios, no solo con el backtest de H7b. Tipo: **externo**. Es una medición de costo
hacia adelante, como la prueba maker de H4 (DEC-034). No hay señal nueva ni backtest, y el bot no cambia.

**Hipótesis falsable:** con las mismas órdenes que decide el piloto, cotizadas en el mismo instante, el costo de
ejecución (comisión más distancia al medio del libro) en Binance u OKX es al menos **25 pb menor por orden** que el costo
real que paga el piloto en Bitso.

## Qué se mide

**Control: Bitso realizado.** Es el `cost_bps` de cada operación cripto del piloto: precio contra el medio del libro
al empezar, más comisión, con maker primero y el resto a mercado (DEC-034).

**Sombra por orden.** Justo antes de que el piloto envíe cada orden cripto a Bitso, se pide el libro del mismo activo
contra USDT en cada venue y se recorre para el mismo lado y el mismo importe en US$ que la orden. El costo de la sombra es
la distancia del precio promedio al medio de ese libro más la comisión taker del venue.

| Venue | Libro | Comisión taker | Nota |
|---|---|---|---|
| Binance spot | `data-api.binance.vision/api/v3/depth`, 100 niveles | 0.10% y, como variante, 0.075% (pagando con BNB) | Solo taker |
| OKX spot | `www.okx.com/api/v5/market/books`, 100 niveles | 0.10% | Solo taker |

Cada cotización registra el venue, el estado (`ok` o el error), el medio del libro, el spread, el costo de recorrer el
libro, la profundidad alcanzada y la brecha entre el medio del venue y la referencia del piloto en Bitso.

**Panel diario (informativo, no decide).** Una vez por ciclo diario del bloque cripto, después de operar, se cotiza una
compra y una venta de US$100 en las 16 monedas del universo en Bitso, Binance y OKX. Sirve a H6, que necesita historia de
spreads por moneda, y a H14. Al arrancar el servicio se corre el mismo panel una vez, como sondeo de acceso desde el
servidor (Railway, región `sfo`).

## Regla de decisión (escrita antes de ver datos)

- **Ventana:** desde el despliegue hasta el **1-dic-2026, 18:00 CDMX** (4 semanas), con al menos **20 órdenes** del
  piloto con cotización válida del venue. Si a esa fecha no hay 20, se extiende hasta llegar a 20, como máximo al
  29-dic-2026. Si no se llega, el veredicto es «falta dato».
- **Disponibilidad:** si menos del 95% de las cotizaciones del venue (órdenes y panel) llegan con libro válido, el
  venue queda como «no medible desde el servidor» y su diferencia no se interpreta.
- **Métrica principal:** diferencia media de costo ponderada por importe, Bitso realizado menos venue taker, en pb.
  Intervalo de confianza de 90% por bootstrap que remuestrea ciclos diarios completos (10,000 réplicas, semilla
  20261103).
- **Veredicto por venue:**
  - **Ventaja medida:** el límite inferior del intervalo es mayor que 25 pb.
  - **Sin ventaja clara:** en cualquier otro caso.
  - Para Binance, la ventaja se califica **robusta a la comisión** solo si también pasa con 0.10%, sin descuento BNB.
- **Efecto en dinero:** diferencia media × importe operado en la ventana, anualizado, en US$ y como % del bloque.
- Nada de esto cambia el bot. **La elección de exchange para dinero real es de Brandon**: el resultado es evidencia para
  H7, junto con regulación, custodia e impuestos.

## Límites declarados

- **Solo taker en Binance y OKX:** la sombra no simula órdenes maker y Bitso sí las intenta, así que el sesgo favorece a
  Bitso. Es conservador para la conclusión «el otro es más barato».
- **USDT no es USD:** cada costo se mide contra el medio de su propio libro. La conversión USD↔USDT y la entrada y salida
  en pesos (≈0.4 puntos al año según H7b) no entran.
- **Las órdenes son las del piloto:** con menos costo, el bot tendría otro efectivo y quizá otras órdenes. No se miden
  esos efectos de camino.
- **El servidor está en California:** si un venue bloquea por región, se registra como no disponible. No se usa proxy ni
  VPN. Brandon operaría desde México, donde ambos libros responden (prueba del 2-nov desde la Mac).
- **Sin efecto sobre la ejecución:** las cotizaciones van por una sesión HTTP aparte, con 8 s de tiempo máximo por
  libro. Nunca cambian el tamaño, el orden ni la ejecución en Bitso. Si fallan, se registra el error y el ciclo sigue.
