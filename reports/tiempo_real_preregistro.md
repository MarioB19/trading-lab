# Pre-registro: operar en tiempo real (bloque cripto)

Declarado el 26-sep-2026 (UTC), antes de descargar los datos por hora y de correr cualquier prueba.
Este archivo queda en git con esa fecha; los resultados van en `reports/tiempo_real_informe.md`.

## Pregunta

¿Revisar y operar más seguido que una vez al día mejora al bloque cripto, con costos reales de Bitso?

## Datos

- Velas de 1 hora contra USD de Coinbase y Bitstamp, de enero de 2020 a hoy, para las criptos del universo del bot
  que tengan historia por hora en esas fuentes (TRX no la tiene; queda fuera de las cuatro variantes por igual).
- El cierre diario es el precio de las 00:00 UTC, igual que la vela diaria que usa el bot.
- Fuera de muestra: 1-ene-2021 a hoy. Las reglas ya estaban fijadas antes (candidata cripto de `research_multi`).

## Regla común

La candidata cripto sin cambios: top 5, volatilidad objetivo 40%, filtro BTC, freno por caída, tope 40% por activo,
banda de 2 puntos, kill switch a 45%, costo 0.45% por operación. Las señales se calculan con los cierres diarios;
en una revisión a media sesión, el precio de ese momento hace de cierre provisional del día.

## Variantes

| Clave | Qué hace |
|---|---|
| R0 (referencia) | Revisa una vez al día a las 00:00 UTC. Es lo que hace hoy el bot. |
| R1 | Revisa cada 4 horas y rebalancea si algún peso pasa la banda. |
| R2 | Revisa cada hora y rebalancea si algún peso pasa la banda. |
| R3 (vigía) | Rebalancea solo a las 00:00 UTC. Cada hora recalcula el freno y el kill switch con el precio en vivo; si el freno se aprieta o se activa el kill switch, vende. Nunca compra fuera de las 00:00. |

Las cuatro se simulan con el mismo motor (`lab.portfolio.simulate_portfolio`) sobre la misma malla horaria,
y se comparan con rendimientos diarios.

## Criterios (una variante se aprueba solo si pasa los cinco)

1. Sharpe fuera de muestra mayor que el de R0.
2. Bootstrap por bloques de 30 días (mismos días): P(Sharpe mejor que R0) ≥ 80%.
3. Placebo (pesos desfasados en el tiempo, 100 versiones): p < 0.05.
4. Caída máxima fuera de muestra no peor que la de R0 por más de 1 punto.
5. Con 0.60% por operación sigue con mayor Sharpe que R0 con 0.60%.

Las tres variantes cuentan como intentos adicionales en el Sharpe deflactado de la investigación cripto.

## Qué pasa según el resultado

- Si una variante pasa: se enciende en simulado y pasa 4 semanas así antes de considerar dinero real. Si pasan varias,
  la de mayor Sharpe fuera de muestra.
- Si ninguna pasa: el bot sigue operando una vez al día. El motor en tiempo real queda en modo observación:
  cada hora actualiza la valuación, la caída y los precios en el tablero, sin operar.
