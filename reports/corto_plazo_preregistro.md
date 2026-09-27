# Pre-registro: estrategias de corto plazo en cripto

Declarado el 27-sep-2026, antes de programar o correr estas estrategias. Resultados en
`reports/corto_plazo_informe.md`.

## Pregunta

¿Una estrategia hecha para ganancias cortas (horas o pocos días) le gana al bot diario actual,
con costos reales de Bitso?

## Datos y reglas comunes

- Las mismas velas de 1 hora de la prueba de tiempo real (`data/hourly_prices.csv`, Coinbase y Bitstamp,
  2020 a hoy) y el mismo universo: las criptos del bot con historia por hora. Una cripto entra cuando tiene
  30 días de historia por hora.
- Solo compras (sin cortos ni apalancamiento). Lo que no está invertido queda en efectivo.
- Las decisiones usan solo precios hasta la hora de la decisión y se aplican en la hora siguiente.
- Costo de 0.45% por operación. Sin banda de rebalanceo: se opera cada vez que cambia la cartera.
- Fuera de muestra: 1-ene-2021 a hoy. Comparación con rendimientos diarios, sin kill switch (con él la
  referencia se apaga en 2023 y la comparación queda plana; se reporta aparte).
- Referencia (R0): el bot diario actual en los mismos datos (`lab.research_rt`, variante R0).

## Variantes (4)

| Clave | Regla |
|---|---|
| C1 | Reversión: cada 4 horas compra, en partes iguales, las 3 criptos que más cayeron en las últimas 24 horas. |
| C2 | Reversión con umbral: igual que C1, pero solo las que cayeron más de 5% en 24 horas; si ninguna, efectivo. |
| C3 | Ruptura 24/12: cada hora, una cripto entra si su precio supera el máximo de las 24 horas anteriores y sale si baja del mínimo de las 12 horas anteriores. Peso 1/5 por cripto; si hay más de 5 dentro, partes iguales. |
| C4 | Ruptura 72/36: igual que C3 con 72 y 36 horas. |

## Criterios (una variante se aprueba solo si pasa los cinco)

1. Sharpe fuera de muestra mayor que el de R0.
2. Bootstrap por bloques de 30 días: P(Sharpe mejor que R0) ≥ 80%.
3. Placebo (la misma cartera desfasada días completos, 100 versiones): p < 0.05.
4. Caída máxima no peor que la de R0 por más de 1 punto.
5. Con 0.60% por operación sigue con mayor Sharpe que R0 con 0.60%.

Se reporta también el resultado con 0.30% (órdenes límite en el mejor caso), sin que cambie la decisión.
Las 4 variantes cuentan como intentos adicionales en el Sharpe deflactado de la investigación cripto.

## Qué pasa según el resultado

- Si una pasa: se agrega como bloque separado en simulado, apagado para dinero real, 4 semanas mínimo.
- Si ninguna pasa: no se agrega nada y el bot sigue operando una vez al día.
