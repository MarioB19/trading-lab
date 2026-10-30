# Carril 1 (H10, Donchian 55/20) — cómo corre y qué falta

**Qué es.** Observación prospectiva de la candidata `donchian-55-20-equal` contra el control, con dinero ficticio
(US$500 + US$500 por cartera), aprobada por Brandon el 30-oct-2026 (DEC-037). Preregistro:
`reports/donchian_lane_v1_preregistro.md` (commit `405c3c2d6ba5f554b2f594d71f5fbb4530987362`). Plan:
`configs/experiments/donchian_lane_v1.yaml`. No toca el piloto, Railway ni dinero real.

**Dónde corre.** Fuera de Railway (ahí el gate exigiría fijar `TRADING_LAB_BUILD_ID` en cada despliegue, cosa que
solo Brandon puede hacer). Ejecutor separado en la Mac, desde el vault:

- venv: `Trading Lab/.venv-carriles` (Python 3.13, `requirements-runtime.txt`)
- código congelado: `Trading Lab/carriles/codigo-carril-1` (clon local fijo en el commit de `main` del primer `setup`;
  la base del carril está atada a ese commit exacto, así que ese clon no se actualiza)
- base y evidencia: `Trading Lab/carriles/carril-1/` (`comparison.sqlite3`, `comparison.json`, `comparison.md`)

```sh
VAULT="$HOME/mnt/Trading Lab"     # en el shell del equipo; en la Mac directa: /Volumes/KINGSTON/Projects/Second Brain/Projects/Trading Lab
bash "$VAULT/trading-lab/scripts/lanes/run_carril.sh" carril-1 "$VAULT" setup   # una vez
bash "$VAULT/trading-lab/scripts/lanes/run_carril.sh" carril-1 "$VAULT" run     # una observación al día (idempotente)
bash "$VAULT/trading-lab/scripts/lanes/run_carril.sh" carril-1 "$VAULT" status
```

Probado de punta a punta en la nube el 30-oct (setup, run y reintento idempotente). La primera observación real debe
hacerse desde la Mac para que la base viva en el vault.

**Qué falta (lo tiene que hacer Brandon).** El 30-oct Claude no pudo crear ni modificar tareas programadas (permiso
denegado por el clasificador de la sesión). Hay dos opciones:

1. Pedirle a Claude en una conversación nueva: «crea la tarea programada diaria del carril 1 con el texto de
   docs/CARRIL_1_TAREA.md» y aprobar el permiso cuando lo pida.
2. Crearla a mano en Claude (tareas programadas), diaria a las 08:31 CDMX, que requiera esta computadora, con este texto:

> Observación diaria del carril 1 de Trading Lab (bot de inversión simulado de Brandon): la candidata Donchian 55/20
> corre en paralelo al control, con dinero ficticio, en la Mac de Brandon. Nadie está mirando esta ejecución: no hagas
> preguntas, decide lo razonable y termina con un resumen de una o dos líneas.
>
> Contexto: Brandon aprobó el 30-oct-2026 abrir este carril (H10, DEC-037). La candidata NO superó la corrección por
> comparación múltiple del catálogo 100; el carril es observación hacia adelante durante al menos 28 días. Nada de esto
> toca el piloto ni Railway. Reglas: nunca dinero real, nunca editar la base SQLite a mano, no inventar números, no
> cambiar el plan ni el código congelado del carril. Nunca imprimas el contenido de Trading Lab/.secretos.
>
> Procedimiento, en el shell del equipo de Brandon (la carpeta «Trading Lab» del vault está montada bajo $HOME/mnt):
> 1. VAULT="$HOME/mnt/Trading Lab"; cd "$VAULT/trading-lab" && git pull --ff-only (si quedan .lock de git, muévelos dentro de .git y reintenta una vez).
> 2. Si no existen "$VAULT/.venv-carriles/bin/python" o "$VAULT/carriles/codigo-carril-1/.git": bash "$VAULT/trading-lab/scripts/lanes/run_carril.sh" carril-1 "$VAULT" setup (una vez; puede tardar 1–2 minutos; si corta por tiempo, repítelo: es idempotente).
> 3. bash "$VAULT/trading-lab/scripts/lanes/run_carril.sh" carril-1 "$VAULT" run (idempotente dentro del mismo día UTC).
> 4. Lee "$VAULT/carriles/carril-1/comparison.md" y termina con: días observados, capital del control y de la candidata (US$), diferencia y si hubo incidencias. Ejemplo: «carril-1: día 5/28, control US$498.2, candidata US$501.0 (+2.8), sin incidencias».
> 5. Solo si falla (gate bloqueado, red, base inconsistente): escribe en el vault «01 — Operación/🗓️ Revisiones/🗓️ Alerta carril — AAAA-MM-DD.md» con qué pasó y qué falta, y dilo en el resumen. No arregles el código congelado ni la base; si no es de red, se resuelve en la revisión del domingo.
> 6. Cuando comparison.json diga complete=true (28 días observados y transcurridos), di «carril-1 completo: listo para revisión humana».
>
> Si la computadora no responde o la USB KINGSTON no está montada, no reintentes: termina diciendo que hoy no se pudo observar el carril y por qué.

**Qué se decide a los 28 días.** Con `comparison.json`: resultado neto de la candidata no inferior al control, rotación
no mayor y caída no peor por más de 2 puntos → Brandon decide si va al piloto simulado 4 semanas más (DEC nuevo). Si no,
se cierra el carril y la familia F4 queda descartada con dato hacia adelante.

**Rasgo de la regla que conviene saber.** Cuando solo una moneda está en ruptura, la candidata la lleva al 100% del
bloque (escalado solo por su volatilidad): así se probó en el catálogo y de ahí salió buena parte de su rendimiento extra
(335 días así en 2019–2026). En la prueba del 30-oct eso fue TRX al 99%. Es concentración, no diversificación.
