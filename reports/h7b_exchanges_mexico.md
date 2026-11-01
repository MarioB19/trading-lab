---
experiment_id: h7b-exchanges-mexico
fecha: 2026-11-01
tipo: externo (informativo; la elección de exchange es decisión de Brandon)
---

# H7b — El bloque cripto vigente con la comisión de cada exchange usable desde México (simulación)

Actualiza H7 (25-oct) con el control vigente (orden mínima US$25, DEC-033), el costo medido del piloto y la situación
de cada exchange en México al 1-nov-2026. Pedido por Brandon como simulación sobre datos históricos, no en vivo.
Misma señal, universo de 16 monedas, banda 2 pp, kill −45%, US$500 desde el 2019-01-01 hasta el 2026-09-26, compuesto.
Costo por lado = comisión del nivel más bajo + medio spread supuesto (1 pb en Bitso; 2 pb en exchanges globales).
Entrada y salida en pesos, una vez sobre el capital: 0.78% por lado en Bitso (libro en pesos, taker) y 1% en los
globales (P2P, que se cotiza entre 0.5% y 1.5%). Datos: `reports/h7b_exchanges_mexico.json`. Script:
`scripts/research/h7b_exchanges_mexico.py`.

## Resultado

| Escenario | Costo por lado | Rend. anual | Sharpe | Caída máx. | Costo/año | US$500 se vuelven | Tras entrar y salir en pesos | Con costos ×1.5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bitso USD, taker (modelo vigente) | 0.37% | +41.9% | 1.29 | −37.1% | 10.8% | US$7,513 | US$7,397 | +35.1% |
| **Bitso USD, costo medido del piloto** | **0.49%** | **+37.5%** | 1.19 | −41.4% | 14.0% | **US$5,876** | US$5,785 | +17.9% (kill) |
| Bitso USD, 100% maker | 0.31% | +44.2% | 1.34 | −35.3% | 9.1% | US$8,523 | US$8,391 | +38.4% |
| Bitso en pesos, taker | 0.80% | +17.1% | 0.79 | −45.4% (kill) | 10.5% | US$1,693 | US$1,693 | +14.2% |
| Kraken Pro nivel 1, taker | 0.82% | +16.9% | 0.79 | −45.8% (kill) | 10.8% | US$1,672 | US$1,638 | +14.1% |
| Kraken Pro nivel 1, maker | 0.42% | +40.0% | 1.25 | −38.9% | 12.1% | US$6,776 | US$6,641 | +18.1% (kill) |
| **Global a 0.10% (Binance, OKX, Bybit, Bitget)** | **0.12%** | **+52.6%** | **1.51** | **−28.4%** | **3.6%** | **US$13,216** | **US$12,953** | +49.8% |
| Binance con descuento BNB (0.075%) | 0.095% | +53.9% | 1.53 | −28.3% | 2.9% | US$14,104 | US$13,823 | +51.6% |

Por año (rendimiento): Bitso medido 2021 +159.8%, 2022 −15.4%, 2023 +29.6%, 2024 +60.7%, 2025 −19.3%, 2026 +33.9%;
global a 0.10% 2021 +185.3%, 2022 −10.6%, 2023 +48.6%, 2024 +80.0%, 2025 −7.4%, 2026 +49.7%. «Kill»: la caída llega al
−45% y el bloque se apaga (en pesos en Bitso y Kraken taker, en 2023).

## Qué ofrece cada exchange en México (1-nov-2026)

| Exchange | Comisión spot, nivel más bajo | Pesos | Situación en México |
|---|---|---|---|
| Bitso | USD (USDC/USDT): 0.30% maker / 0.36% taker; pesos: 0.60% / 0.78% | SPEI directo | Autorizado como ITF (CNBV) |
| Binance | 0.10% / 0.10% (0.075% con BNB) | Sin SPEI directo; P2P o tarjeta | No opera como ITF en México |
| OKX | 0.08% según comparadores (la página oficial no cargó) | P2P o tarjeta | No regulado como ITF |
| Bybit | 0.10% | **Dejó de soportar pesos el 30-sep-2026**; P2P en pesos pausado hasta después del 2-nov | No autorizado como ITF |
| Bitget | 0.10% | P2P o tarjeta (SPEI vía socio en 2024) | No regulado como ITF |
| Kraken | 0.40% maker / 0.80% taker por debajo de US$2,500 al mes | SPEI gratis, se convierte a USD | Sin registro en México |

## Lectura

- **La comisión sigue siendo la palanca más grande.** Con el costo que de verdad paga hoy el piloto en Bitso (49 pb,
  más que los 37 del modelo por los spreads de monedas poco líquidas como TRX), el bloque habría rendido +37.5% anual con
  −41% de caída. En un exchange global a 0.10%, +52.6% con −28%: ≈15 puntos más al año y 13 menos de caída, misma
  estrategia. Sobre US$500 en 7.7 años: US$5.9 mil contra US$13.2 mil.
- **Entrar y salir en pesos casi no cambia la cuenta** (≈0.3–0.4 puntos al año), aunque el P2P cueste 1% por lado.
- **Bitso al costo medido no aguanta costos ×1.5:** toca el kill switch. Con 0.10% sí aguanta (+49.8%).
- **En Bitso conviene lo que ya se hace:** solo libros en USD (en pesos se apaga) y empujar las órdenes maker (H4).
- **Kraken no sirve a este tamaño:** 0.80% taker por debajo de US$2,500 al mes.
- **Lo que esta tabla no decide** (todo es de Brandon): Bitso es el único autorizado en México; los globales no tienen
  esa protección ni dan constancias fiscales mexicanas (el SAT puede pedir la información; conviene consultar a un
  contador), el riesgo de custodia es del exchange, los pesos entran por P2P, y la cuenta del bot tendría que ser suya con
  llaves de solo operar. Antes de dinero real, la regla sigue pidiendo 4 semanas en simulado contra el libro del exchange
  elegido; hoy el simulador contra el libro solo existe para Bitso.

## Limitaciones

- Histórico 2019–2026 (incluye la gran subida de 2020–2021): los niveles absolutos son optimistas; la diferencia entre
  escenarios, que es pura aritmética de comisión por rotación (≈29–30 veces al año), es lo robusto.
- Spreads de los exchanges globales supuestos (2 pb), no medidos. Universo de Bitso aunque los globales listan más.
- Comisiones consultadas el 1-nov-2026 en las páginas oficiales de Bitso, Binance y Kraken; OKX y Bitget según
  comparadores. Cambian con el volumen y con promociones.
