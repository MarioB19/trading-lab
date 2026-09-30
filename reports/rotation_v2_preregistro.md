---
protocol_version: 1
status: approved
approved_by: Brandon
approved_at_utc: '2026-09-30T01:59:44.167619+00:00'
experiment_id: rotation-v2
hypothesis: Un margen relativo de 15% para sustituir un activo reduce la rotación
  cripto al menos 15% y mejora el CAGR neto al menos 0.5 puntos porcentuales frente
  al control de margen cero, sin deteriorar Sharpe ni más de 1 punto de caída máxima.
evaluation_window: 'Diagnóstico retrospectivo con parámetros fijados: 2021-01-01 a
  último cierre disponible, años completos separados e informe causal walk-forward.
  2021-2026 ya fue inspeccionado. No es holdout virgen. Evidencia prospectiva posterior
  al preregistro, al menos 28 días completos, requerida antes de promoción.'
config_sha256: 6dffbd1a1f51ffdb440dd6a67c3cc3e0644cd3d29ee52d6a8cc20cccda73cca3
variant_ids:
- crypto:2556ba33f438fb24984b
- crypto:70a0d62d363a70c0c768
- crypto:b55ee4b39c1951067253
- crypto:900c772617bd2a237263
- crypto:6e2524e6e35ef79075c9
- crypto:04bb2f18ce2a545767f8
- crypto:615399435e7790df8cb6
- crypto:aa6fb3caee9334e04e7f
- crypto:81851c9eda68767117e5
- crypto:deabaa77253508b22f3b
- crypto:a74e069540b13527bc82
- crypto:1ad098d641fface79658
- crypto:1c0a7d46fcf0cb4cddf7
- crypto:93a8453229eaee9f2492
- crypto:3b11b8ae256e5e619fc1
- crypto:7d799fe5272f61782d4f
- crypto:e3aae0ba782eefa36d63
- crypto:0715752a40d15a64d203
- crypto:d6953d39d26c3971df41
- crypto:07a62a82fc331b14e6dc
- crypto:650af28249c6b2fa3e28
- crypto:13327dea0001a46a6c74
- crypto:f590e38bfadf2899bbff
- crypto:dff83252d27a3057cd9d
- crypto:de03f28c152eef4ff848
- crypto:d6870f0731196812054b
- crypto:d33afc806c85e0af51ee
- crypto:e9fd992a936f466908ea
- crypto:3149cd26f5be8c911a35
- crypto:433f3d009056118da249
- crypto:4b9ee736706f8fb0b180
- crypto:780f664eacefa273e069
- crypto:3ae1e7c0d2d772c0da07
- crypto:4a08c4274ca9553273a1
- crypto:1e879918a6cb8b59d5ae
- crypto:095d0690eacd92b2639e
- crypto:b159060c4563f3fdc407
- crypto:18488d547023e3780f32
- crypto:c741fb4fd71f08d89f2e
- crypto:20c7c15c3231c1b3b680
- crypto:95174601ed2699fa924a
- crypto:ebb8eaf0a4676f5e1936
- crypto:e24be3879848f9cf33e4
- crypto:8712ed0dc5f33a86ceb0
- crypto:3cc1cb784616f74b4310
- crypto:3d2afb4224c9e4fcb05e
- crypto:c4016afa3e18bff91d07
- crypto:73c9c0a01fe741586ff7
- crypto:554e1be9da2b10bd82e0
- crypto:ffd21730e6c12e743f80
- crypto:0acb8251ec6a69511c62
- crypto:061a0915f368832b8d20
- crypto:11e7e5e9801e1238bbfa
- crypto:beadb0783804670a3da2
- crypto:da0494f350d6e8d05278
- crypto:c22c0b5b1b3accfe4ad2
- crypto:2b12bfad2351b6e2494a
- crypto:29cdff1eb71e3ac7c4ba
- crypto:c556a1d5659373e3ba62
- crypto:000f8c18d6d675823622
- crypto:8ad0302a8ff89d73545f
- crypto:fda8e93d98839d4cd293
- crypto:15fd191df31d41d1afc1
- crypto:95e5482b523053db12a1
- crypto:4abe4e54f064b8c93707
- crypto:5c439bc40a7bc42baf09
- crypto:3b08243fb6457e30e080
- crypto:906e7d0f46a5c2e33750
- crypto:8cb81051ec7c1dc57262
- crypto:9557db6d2106e6265548
- crypto:2aeeb132e534342c6fcd
- crypto:f733276450ed2743de44
- stocks:46f174273193e39a79eb
- stocks:6717a33949e726c4d521
- stocks:31ea28f59d7497c4c9bd
- stocks:045e3fdeff27e616d751
- stocks:086f7528e55718c55340
- stocks:46144c084803495036b7
- stocks:9145befac8919825bdff
- stocks:e633e64c9d8d5c86c486
- stocks:2930bf86b9f46361e9fb
- stocks:ea33d7259042f54cf302
- stocks:1f1e82012a9b150aae1f
- stocks:68f2703627c9c7d01072
- stocks:dd087bc69acdfc376ffe
- stocks:3935d2516c5afefdfd0c
- stocks:356f9a2bf12da4f0faa4
- stocks:79b5db0e27b7dcbff1f6
- stocks:86c0ce44db2f6f5ca148
- stocks:15a65e6eeaa42901bbe2
criteria:
  walk_forward: CAGR neto candidata >= control + 0.005, Sharpe >= control; supera
    al control en al menos 60% de los años completos. Informar selecciones anuales
    causales y conservar cartera entre años. Históricos inspeccionados no bastan para
    promoción.
  placebo: p < 0.05 con 200 desplazamientos y corrección finita (1+k)/(1+n).
  bootstrap: '2000 réplicas emparejadas de bloques de 30 días: frecuencia de superioridad
    >= 0.80 en retorno y Sharpe frente al control de margen cero.'
  cost_stress: 'Por lado: base 0.45%; sensibilidad 0.30%, 0.60%, 1.00%. A 0.60% CAGR
    y Sharpe candidata >= control.'
  drawdown: Caída máxima candidata no peor que control en más de 0.01; se conservan
    freno y kill switch.
  turnover: Rotación acumulada candidata <= 0.85 * control, ambos con misma ventana
    y costos.
  causality: Pruebas de prefijo y modificación futura, last_only equivalente y salidas
    inmediatas por inelegibilidad/régimen.
  paper: 28 días completos prospectivos, misma identidad de código/configuración/corrida,
    sin incidencias pendientes; dinero real nunca se autoriza por este protocolo.
availability_policy:
  asset: AVAX
  available_from: '2020-09-22'
  evidence_sha256: b6483adcc33ea32a162e9cd4dad52224714832a8d3abf9aff5dc55ca93848850
source_sha256:
  crypto_prices.csv: d80331a61666d98a9998f5d2f4de666fbbdd69763529765ef4b34df1568577fa
  crypto_mcap.csv: bc324df4a6ea20ac1269fe2b43c3602b007c9771cca0eca586dbd0bdc23d3863
  etf_prices.csv: a4391485e8d632cc127e72a93409ec4ee54981d4533a077763fa8fc620c97b92
parent_preregistration: af34687109efbff2b7978ee802b7bb0387955bd3
data_cutoff: 2026-09-26 crypto; 2026-09-25 stocks
---

# Preregistro — menor rotación con disponibilidad AVAX corregida

Brandon autoriza la comparación y la elección basada en resultados. Se registra antes de calcular rendimientos. Se conservan sin cambios los 90 IDs, hash de configuración, hipótesis, parámetros, fechas de evaluación, costos y criterios del preregistro rotation-v1. Sus resultados todavía no se han calculado. La inicialización original falló antes de evaluar variantes: un timestamp YAML no serializable y la auditoría previa de 69 huecos de AVAX. La nueva fecha de aprobación se conserva como texto ISO.

Única corrección de datos: aplicar la función compartida `lab.research_data.apply_availability_policy` con la política exacta del frontmatter. Se ponen como ausentes las dos observaciones AVAX del 13/14-jul-2020 previas al mercado spot de referencia verificado del 22-sep-2020. No se interpolan los huecos, convierten USDT/USD, alteran otros activos ni extiende la muestra. Los originales se congelan por hash y se conservan junto a precios derivados y audit. Elegibilidad sigue exigiendo 250 observaciones válidas. Esta fecha es una referencia Binance, no fecha histórica de listado Bitso.

Evidencia: `reports/data_quality/avax_spot_availability.json`, hash exacto en la política; anuncio oficial [Binance](https://www.binance.com/kk-KZ/support/announcement/detail/202d37b746bf46e3ae72b256799007ea) y [archivos oficiales](https://github.com/binance/binance-public-data). La evidencia ha sido contrastada antes del ensayo.

Comparación fija: control `rotation_buffer=0.0` contra candidata `0.15`, ambos top 5, volatilidad objetivo 40%, filtro BTC, freno, banda 2% y mismo costo base 0.45% por lado. El grid completo se ejecuta para contabilidad y walk-forward; no se elige su máximo dentro de muestra como ganador. El bloque ETF sigue SPY/IEF 60/40 en operación.

Las limitaciones CoinMetrics/Yahoo, listado retrospectivo Bitso y ejecución aproximada continúan. `point_in_time_complete=false`. El histórico ya inspeccionado no es holdout nuevo. Ningún resultado autoriza activación: la candidata debe pasar todos los criterios y 28 días prospectivos completos; si falla se conserva el control. Nunca habilita dinero real.

El plan exacto se conserva en `rotation_v2_plan.json`, idéntico a v1 en configuración y variantes, con política y hashes de entradas añadidos. El lanzador posterior verifica esos hashes antes de leer precios, registra el intento, congela originales y aplica solo la corrección declarada. Ejecuta el pipeline completo existente sin refresh ni cambios operativos.

```sh
PYTHONPATH=src python scripts/research/rotation_v2.py --preregistration-commit SHA_PREVIO --source-cache RUTA_COPIA_CON_HASHES
```
