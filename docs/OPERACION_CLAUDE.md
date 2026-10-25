# Operación con Claude

Cómo lee, opera y despliega Claude el Trading Lab. Todo en simulado.

## Dónde trabaja Claude

| Tarea | Dónde | Por qué |
|---|---|---|
| Código, pruebas, investigación | Clon del repo en la nube (`git clone https://github.com/MarioB19/trading-lab`) o la Mac | Python 3.13 y `uv` disponibles; GitHub es la fuente de verdad |
| Leer el panel, pausar la arena, Railway | Shell del equipo de Brandon (`$HOME/mnt/Trading Lab/trading-lab`) | Ahí vive el archivo de credenciales |
| Notas, revisiones, decisiones | Vault en `$HOME/mnt/Trading Lab/` | Obsidian de Brandon |

`main` en GitHub es la única rama viva. Las copias de trabajo de Codex quedaron archivadas en
`90 — Archivo/worktrees-codex/` del vault (con su `runtime-data`). Para trabajo largo se usa una rama
`claude/<tema>` y se integra a `main` con pruebas en verde. La copia de la USB
(`trading-lab/`) se actualiza con `git pull --ff-only` al empezar. Git en la USB necesita permiso de
borrado (sus `.lock`); si no lo hay, se mueven dentro de `.git`.

## Credenciales (las pone Brandon, nunca Git)

Archivo `Trading Lab/.secretos/claude.env` en el vault (Obsidian no muestra carpetas con punto):

```
TL_PANEL_USER=brandon
TL_PANEL_PASSWORD=<contraseña del panel>
RAILWAY_API_TOKEN=<token de cuenta: railway.com/account/tokens>
```

Claude nunca imprime ni copia estos valores. `tl.py` los carga solo; para la CLI de Railway se
exportan sin mostrarlos: `set -a; . "../.secretos/claude.env"; set +a`.

## Panel único (DEC-032)

Un servicio (`trading-lab`), un volumen y un panel con tres pestañas, todo de solo lectura y con la
misma contraseña: **Piloto** (resultado, atribución a mercado, estrategia y costos, operaciones),
**Investigación** (semáforo de «ganadora», backlog, bitácora y carriles de candidatas) y
**Arena (archivo)** (resultado final, curva, auditoría diaria y las 267 operaciones).

- Dominio: `https://tradinglab.inovaris.online` (CNAME en Hostinger hacia Railway). Mientras el DNS no
  exista, `tl.py` usa `https://trading-lab-production-a56b.up.railway.app`. Ese dominio de Railway se
  quita cuando el propio lleve 7 días sano; después basta con borrar la segunda línea de `PILOT_URLS`.
- Límite de contraseñas: 10 fallidas en 15 minutos por cliente dan 429 durante 15 minutos.
- APIs nuevas: `/api/attribution`, `/api/research`, `/api/candidates`, `/api/arena-archive`
  (y `/fills`), `/api/backups/latest` y `/api/backups/part`.

## Leer el estado

```sh
cd "$HOME/mnt/Trading Lab/trading-lab"
python3 scripts/claude/tl.py check          # credenciales, dominios y salud
python3 scripts/claude/tl.py snapshot       # JSON crudo en runtime-data/claude/snapshots/
```

El snapshot guarda `/api/status`, `/api/performance`, `/api/execution-quality`, trades, equity,
eventos, atribución, investigación, carriles y el último respaldo. Los análisis se hacen con código
sobre ese JSON, nunca leyendo cifras a ojo:

```sh
python3 scripts/claude/review.py alerts  runtime-data/claude/snapshots/<archivo>.json   # código 1 si hay alertas
python3 scripts/claude/review.py weekly  runtime-data/claude/snapshots/<archivo>.json   # atribución (semana, 28 días, inicio)
```

La atribución tiene **una sola fórmula**, en `lab.attribution`; `review.py` imprime lo que devuelve
`/api/attribution`. Reparte el resultado de cada bloque en mercado (beta × referencia del propio bot),
estrategia (lo que aportó la regla antes de costos) y costos (comisión + diferencia contra el precio de
referencia), sin contar aportaciones ni retiros.

Señales de alerta en `status`: `ready=false`, `mode` distinto de `paper`, `pending_orders` o
`unknown_orders` > 0, último ciclo con error, datos viejos. Kill switch: cripto se apaga a −45% y
ETFs a −25% desde el máximo; se avisa a 5 puntos.

## Respaldo externo del piloto

El supervisor hace un respaldo verificado cada 24 h en el volumen. La copia externa se baja con:

```sh
python3 scripts/claude/pilot_backup.py      # a runtime-data/respaldos/piloto/, por tramos con huella
```

Comprueba la huella y el `integrity_check` antes de publicar el archivo y nunca reescribe una copia.

## Investigación: backlog y carriles

- El backlog vive en `research/backlog.yaml` (fuente única). La nota del vault se genera:
  `PYTHONPATH=src python -m lab.backlog check` y
  `PYTHONPATH=src python -m lab.backlog render --out "../00 — Dirección/🧪 Backlog de hipótesis — Trading Lab.md"`.
  No se edita la nota a mano.
- El semáforo de «ganadora» está en `research/semaforo.yaml` (propuesta hasta su preregistro en S02).
- Carriles de candidatas: `research/carriles.yaml` y `lab.lanes` (reutiliza `lab.paper_comparison`).
  Máximo dos activos, US$500 ficticios, cada uno en `/data/lanes/<id>` con su base. Corren una vez al
  día después del ciclo del piloto. Activar uno exige plan preregistrado con commit propio y su DEC.

## Arena (archivada)

- Apagada el 25-oct (DEC-031). Respaldo final verificado en `runtime-data/respaldos/arena-v1-final/`
  (USB) y `~/Documents/Trading Lab — respaldos/arena-v1-final/` (Mac). Archivo de consulta en Git:
  `archive/arena-v1/` (`python -m lab.arena_archive verify --db <restaurada> --archive archive/arena-v1`).
- La última imagen del servicio `trading-arena` es la de **mantenimiento** (`infra/arena/maintenance.Dockerfile`):
  monta el volumen y responde `/healthz`, sin worker ni rotación. Para volver a bajar algo:
  `python3 scripts/arena/package_maintenance.py <destino>`, `tl.py up trading-arena <destino>`,
  `scripts/claude/arena_backup.py status|download|verify` y `tl.py stop trading-arena` al terminar.
- Borrar el volumen y el servicio (F5) lo decide y lo hace Brandon a mano en Railway.

## Desplegar el piloto

1. Pruebas en verde en Python 3.13 (nube o Mac) y commit en `main`.
2. Compuertas: `main` reproduce lo que corre (comparar `release.json` del despliegue vigente contra el
   paquete de `main`), `python -m lab.bot --replay 365 --sleeve crypto` con diferencia < 2% y respaldo
   reciente (`last_backup` de `/api/status` del día y, si se puede, la copia externa).
3. Fuera de 17:30–19:00 CDMX (ciclo diario a las 18:00) y nunca el domingo por la mañana. En el shell del equipo:
   ```sh
   git pull --ff-only
   python3 scripts/railway/package.py runtime-data/railway/<RELEASE>/bundle
   python3 scripts/claude/tl.py up trading-lab runtime-data/railway/<RELEASE>/bundle
   python3 scripts/claude/tl.py deployment <ID> --logs 20
   ```
   `tl.py up` sube el mismo paquete que `railway up --path-as-root`, sin la CLI (que rechaza el token de
   espacio de trabajo), y solo acepta el perfil `operational-paper` sin cambios pendientes.
4. Verificar: `tl.py check`, `/api/status` con `ready=true` y el siguiente ciclo diario sin errores.
   Si algo sale mal: volver a desplegar el paquete anterior. Nunca hacer rollback de datos.

El paquete excluye estado, secretos e informes. El volumen conserva SQLite y respaldos entre
despliegues. Detalle completo y recuperación: `docs/RAILWAY_RUNBOOK.md`.

## Qué no hace Claude aunque tenga acceso

Cambiar `mode`, crear llaves de exchange, tocar variables o secretos de Railway, activar dos
escritores, editar SQLite a mano, borrar volúmenes o respaldos, o poner dinero real.
