# Primera comparación cerrada — candidata agresiva rechazada

Periodo histórico: **2021-01-01 a 2026-09-26**. Dos carteras ficticias de US$1,000, 500 en cripto y 500 en los mismos ETFs SPY/IEF. Cifras después de comisión y deslizamiento modelados: 0.45% por lado en cripto y 0.05% en ETFs. No son ganancias obtenidas en una cuenta real ni rendimientos esperados.

| Bloque cripto | Control: top 5 / 40% | Agresiva: top 3 / 60% |
|---|---:|---:|
| Rentabilidad anualizada compuesta | 33.77% | 17.08% |
| Caída máxima | −39.48% | −45.13% |
| Sharpe | 1.129 | 0.753 |
| Capital final, desde US$500 | US$2,655.74 | US$1,235.87 |
| Costos acumulados modelados | US$1,322.48 | US$554.92 |

**La candidata falla los siete criterios preregistrados. No se promueve.** La regla activa se conserva. La simulación agresiva pierde su exposición desde el 18 de agosto de 2023 y el multiplicador de emergencia queda en cero desde el 19; permanece en efectivo después. Sus costos acumulados menores reflejan también que deja de operar, no una mejora de ejecución. No se rearma el kill switch para favorecer el resultado.

El total secundario, sumando los ETFs idénticos sin traspasos, termina en **US$3,439.80** para el control y **US$2,019.93** para la candidata. Su CAGR es 24.02% y 13.03%, y la caída máxima 31.20% y 38.58%, respectivamente.

## Criterios completos

- CAGR: falla; se exigía superar al control en 3 puntos porcentuales.
- Sharpe: falla; se exigía no inferioridad.
- Caída: falla; deterioro de 5.65 puntos frente al máximo permitido de 5, aunque permanece dentro del límite absoluto de 50%.
- Ventanas anuales fijas: gana 2 de 5 años completos (40%); se exigía al menos la mitad. Este criterio se llama `walk_forward` en el registro, pero no constituye un holdout no visto ni un proceso nuevo de entrenamiento walk-forward.
- Bootstrap: frecuencias de superioridad 22.25% en retorno y 26.20% en Sharpe; se exigía 80% en ambos. No son probabilidades de ganancias futuras.
- Placebo de timing: p=0.129353 con 200 desplazamientos; se exigía p<0.05.
- Estrés de costos de 0.60%: falla. El CAGR es 28.01% control frente a 16.10% agresiva, y el Sharpe 0.988 frente a 0.728.
- Estrés de 1%: informativo por preregistro; la candidata supera aquí al control, pero no cambia el veredicto de los criterios obligatorios. Con controles de caída persistentes, más costo puede cambiar cuándo se liquida una cartera; no implica una relación monótona del resultado.

## Procedencia y reproducción

Preregistro aprobado en commit propio `1fe6c8c586b6a9899190b4f987807daf9134846c`; código ejecutado `0541232af0ae9db2d56227c0442f0e4e4aa06401`; hash del plan `4fe0885b787d4ba341e4a8e606d4bd25aa0f2078427d1db99bba4194174381e1`.

Corrida única: `reports/experiments/aggressive-v2/20260928T023514Z-2b88ffec`. **27 artefactos verificados** y cadena del ledger íntegra. El manifiesto conserva las dos variantes terminadas, fuentes originales, datos derivados, auditoría, curvas y métricas. El [JSON resumido](aggressive_v2_resultado.json) conserva la conclusión y sus hashes.

El intento v1 fallido se conserva. V2 fija los mismos paneles y solo pone en cuarentena dos cotizaciones AVAX anteriores al mercado spot de referencia verificado el 2020-09-22. No rellena los 69 cierres ausentes ni sustituye USD por USDT. Ver [evidencia de disponibilidad](data_quality/avax_spot_availability.md).

Comando efectivamente ejecutado, después del gate y con el árbol limpio:

```sh
.venv/bin/python -m lab.aggressive_research --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c
```

## Alcance de la conclusión

El histórico ya fue inspeccionado; no es evidencia prospectiva. El universo actual de Bitso no reconstruye todos sus listados históricos. El pipeline puede incluir proxies tempranos y no identifica su procedencia por observación. El backtest no reproduce libros de órdenes, mínimos, topes ni el filtro operativo de saltos. No certifica un DSR global.

El seguimiento futuro que se inicie será exclusivamente una comprobación de funcionamiento de las dos carteras simuladas. **Completar 28 días no anula estos siete fallos ni rescata automáticamente la candidata.** No se cambia la estrategia por el resultado reciente ni se habilita dinero real. Cualquier nueva hipótesis necesita otro preregistro y evaluación completa.
