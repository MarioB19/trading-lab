# AGENTS.md — Trading Lab

Bot de inversión de Brandon: cripto y ETFs, **solo en simulado**. Lo opera Claude desde el
25-oct-2026 (antes, Codex). Las mismas reglas valen para cualquier agente. `CLAUDE.md`
importa este archivo, así que basta con editar este.

## La misión, en una línea

**Encontrar ventaja después de costos, o dejar de perder dinero en costos.** Medir y auditar
sirve a esa misión, no la sustituye. Un día sin hipótesis probada ni mejora concreta no es
"mejora continua". La infraestructura más confiable del mundo no gana un peso si la estrategia
no supera sus comisiones.

## Qué corre hoy

| Sistema | Qué hace | Dónde |
|---|---|---|
| Piloto cripto (US$500) | Tendencia + momentum, hasta 5 monedas, volatilidad objetivo 40%, una vez al día (00:00 UTC) contra el libro de Bitso | Railway, servicio `trading-lab` |
| Piloto ETFs (US$500) | 60% SPY / 40% IEF, banda de 5 puntos | Mismo servicio, simulador interno |
| Arena (US$4,000) | Cuatro estrategias BTC intradía. **Se apaga por decisión del 25-oct** (perdía en comisiones por diseño) | Railway, servicio `trading-arena` |

Panel: https://trading-lab-production-a56b.up.railway.app/ (autenticado). Railway: proyecto
`24021d85-bbad-4f2c-850c-e1230822e7b0`, entorno production. El estado vivo está en la SQLite
del volumen; `state/` en Git es historial de septiembre.

## Lo que ya sabemos (no redescubrirlo)

- Último corte completo (17–20 oct): piloto ≈ −5% desde US$1,000, sobre todo por la caída de
  cripto; arena ≈ −5%, y **casi dos tercios de su pérdida semanal fueron comisiones**.
- Comisiones simuladas de Bitso: 0.30% maker, 0.36% taker. Costo medido del piloto: ~37 pb por
  movimiento. Con estos costos, cualquier estrategia de corto plazo necesita ganar >0.7% bruto
  por ida y vuelta solo para quedar en cero (`reports/corto_plazo_informe.md`).
- La rotación diaria del bloque cripto cuesta ≈12% del capital al año en el backtest
  (`reports/tiempo_real_informe.md`, con 0.45% por operación). Bajar la rotación es
  la palanca con mejor evidencia: `cost-aware-v1` (margen 15% / banda 4pp) dio US$3,756 contra
  US$3,057 del control en 2021–2026, pero falló placebo y comparación múltiple, así que no se promovió.
- Descartado con evidencia: táctica en ETFs, multi-mercado, operar cada hora o cada 4 h,
  reversión/ruptura de corto plazo con estos costos, versión agresiva top 3.
- El catálogo de hipótesis vigente vive en el vault: `00 — Dirección/🧪 Backlog de hipótesis — Trading Lab.md`.

## Reglas duras

1. **Dinero real: nunca.** No cambiar `mode`, no agregar `--live`, no escribir `.env` ni secretos.
   Pasar a real lo decide y lo hace Brandon a mano, después de 4 semanas en simulado de la estrategia exacta.
2. Nada de retiros, transferencias, apalancamiento, margen, futuros ni cortos.
3. **Nunca cambiar la estrategia por el rendimiento de unos días.** Todo cambio parte de una hipótesis
   escrita antes de correr (preregistro con su propio commit). Hay dos tipos y cada uno tiene su barra:
   - **Cambio de costo** (misma señal, menos fricción: bandas, orden mínima, frecuencia de rebalanceo,
     ejecución maker): mejora neta en la mayoría de los años del walk-forward, bootstrap por bloques de
     la diferencia neta > 0 con 90% de confianza, caída máxima no peor por más de 2 puntos, y estrés de
     costos ×1.5. El placebo no aplica: no se afirma un mejor timing.
   - **Cambio de señal** (se afirma ventaja nueva): walk-forward fuera de muestra, placebo (p < 0.05),
     bootstrap contra el control, Sharpe deflactado con todos los intentos y estrés de costos ×1.5.
4. Cada variante probada se registra (grid de `research_multi` o tabla de intentos del preregistro):
   todas cuentan para el Sharpe deflactado. No esconder intentos fallidos.
5. Señales solo con datos hasta el cierre. Toda estrategia nueva lleva su prueba de "sin mirar al futuro".
6. Bot e investigación comparten las funciones de `lab.portfolio`. No duplicar lógica.
7. Un activo sin precio nunca vale cero. Datos viejos bloquean el día.
8. **No inventar números.** Cítalos de la API, de `reports/` o corre el código. "Sin dato" es válido.
9. No editar SQLite ni `state/` a mano; usar `lab.ops` (backup/restore a destino vacío y desactivado).
10. Un solo escritor por base: nunca dos workers sobre el mismo volumen.

## Autonomía (decidida por Brandon el 25-oct)

En simulado, Claude tiene acceso total: puede hacer commits y push a `main`, desplegar en Railway,
pausar o detener servicios y cambiar parámetros **si se cumplen las reglas de arriba**. Antes de
desplegar: pruebas en verde y respaldo reciente. Después: verificar salud y el siguiente ciclo.
Una candidata que pasa su barra puede reemplazar al control en el piloto simulado; con eso, el reloj
de 4 semanas para considerar dinero real vuelve a empezar. Todo cambio de estrategia queda en el
Registro de decisiones del vault.

## Comandos

- Entorno: Python 3.13. `uv venv -p 3.13 .venv && uv pip install -r requirements-dev.lock.txt && uv pip install --no-deps -e .`
- Pruebas: `python -m pytest -q -W ignore` (todas en verde antes de cualquier commit).
- Consistencia bot/backtest: `python -m lab.bot --replay 365 --sleeve crypto` (diferencia < 2%).
- Investigación: `python -m lab.research_multi --describe` y `docs/RESEARCH_PROTOCOL.md`.
  Estadística: `lab.validation` (walk-forward, placebo, bootstrap, Sharpe deflactado) y `lab.research_statistics`.
- Operación (lectura del panel, arena, Railway): `python3 scripts/claude/tl.py --help` y `docs/OPERACION_CLAUDE.md`.
- Despliegue del piloto: `docs/RAILWAY_RUNBOOK.md` → "Entrega de código".

## Cómo se reporta

Para Brandon, en español claro, con los números primero:
1. ¿Ganamos o perdimos? En US$ y MXN, semana y acumulado, por bloque, contra BTC y SPY.
2. ¿Por qué? Mercado vs. estrategia vs. costos.
3. ¿Qué cambiamos o probamos, y qué salió?
4. Salud en una línea. Solo si algo falla se detalla.

Sin pronósticos de precio. Sin SHAs, bytes ni conteos de capturas, salvo que expliquen un problema.

## Commits

En español, en presente, explicando qué cambia y por qué. Historial de autorizaciones y
despliegues de la etapa Codex: `docs/HISTORIAL_AGENTES_CODEX.md`.
