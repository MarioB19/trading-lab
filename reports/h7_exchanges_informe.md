---
experiment_id: h7-exchanges
fecha: 2026-10-25
tipo: externo (informativo; la elección de exchange es decisión de Brandon)
---

# H7 — El control con la comisión de cada exchange (simulación)

Misma señal, mismo universo (16 monedas de Bitso), misma banda (2 pp) y kill switch (−45%), 2019-01-01 → 2026-09-26.
Solo cambia el costo por lado = comisión + medio spread (BTC/ETH ≈1 pb; promedio del piloto ≈3–4 pb; el spread de
Binance en pares USDT se supone ≈2 pb). Datos: `reports/h7_exchanges_simulacion.json`.

| Caso | Costo por lado | Rend. anual | Sharpe | Caída máx. | Costo/año | 2025 | 2026 (parcial) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Bitso USD taker (vigente, medido)** | 0.37% | +42.7% | 1.31 | −36.7% | 11.0% | −15.2% | +38.8% |
| Bitso USD 100% maker | 0.31% | +44.8% | 1.35 | −35.1% | 9.3% | −13.4% | +41.4% |
| Bitso MXN taker (0.78%) | 0.80% | +15.9% | 0.76 | −46.2% | 11.0% | kill switch | — |
| Kraken Pro taker (< US$2,500/mes) | 0.42% | +40.5% | 1.26 | −38.5% | 12.3% | −16.8% | +36.8% |
| Kraken Pro maker (< US$2,500/mes) | 0.27% | +46.7% | 1.39 | −33.6% | 8.1% | −11.5% | +43.1% |
| **Binance taker (0.10%)** | 0.12% | **+53.7%** | 1.53 | **−28.4%** | **3.7%** | −6.6% | +49.7% |
| Binance maker (0.10%) | 0.11% | +54.0% | 1.54 | −28.4% | 3.4% | −6.2% | +50.1% |
| Binance con BNB (0.075%) | 0.095% | +54.9% | 1.55 | −28.3% | 2.9% | −5.7% | +50.8% |

## Lectura

- **La comisión es la palanca más grande que existe en este proyecto.** Pasar de 0.37% a 0.12% por lado vale ≈11 puntos
  de rendimiento al año y ≈8 puntos menos de caída máxima, sin tocar una línea de la estrategia. Ninguna hipótesis de
  señal se acerca a eso.
- **Operar en pesos en Bitso (0.78%) mata la estrategia:** llega al kill switch. Si Bitso, solo pares en USD.
- Con Bitso al 100% maker (H4) o Kraken maker se ganan 2–4 puntos; es la mitad del camino. Kraken taker es peor que Bitso.
- **Lo que esta tabla no decide:** regulación y residencia fiscal, depósitos y retiros en pesos, custodia, si la cuenta
  del bot puede ser de Brandon con llaves de solo operar, y si el exchange paga rendimiento sobre el efectivo ocioso (H8).
  Todo eso es decisión de Brandon. Antes de dinero real, la estrategia exacta corre 4 semanas en simulado **contra el
  libro del exchange elegido** (M6 del semáforo); el simulador contra el libro hoy solo existe para Bitso.

## Limitaciones

- Spread supuesto por exchange, no medido (salvo Bitso). Universo de Bitso aunque otros exchanges listan más pares.
- Comisiones consultadas el 25-oct-2026; cambian con el volumen y con promociones.
