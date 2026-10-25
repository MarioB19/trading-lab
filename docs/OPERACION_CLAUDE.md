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
(`trading-lab/`) se actualiza con `git pull --ff-only` al empezar.

## Credenciales (las pone Brandon, nunca Git)

Archivo `Trading Lab/.secretos/claude.env` en el vault (Obsidian no muestra carpetas con punto):

```
TL_PANEL_USER=brandon
TL_PANEL_PASSWORD=<contraseña del panel>
RAILWAY_API_TOKEN=<token de cuenta: railway.com/account/tokens>
```

Claude nunca imprime ni copia estos valores. `tl.py` los carga solo; para la CLI de Railway se
exportan sin mostrarlos: `set -a; . "../.secretos/claude.env"; set +a`.

## Leer el estado

```sh
cd "$HOME/mnt/Trading Lab/trading-lab"
python3 scripts/claude/tl.py check          # credenciales y salud
python3 scripts/claude/tl.py snapshot       # JSON crudo en runtime-data/claude/snapshots/
```

El snapshot guarda `/api/status`, `/api/performance`, `/api/execution-quality`, trades, equity y
eventos del piloto, y `/api/arena`, `/api/daily-audit` y `/api/fees` si la arena sigue viva.
Los análisis se hacen con código sobre ese JSON, nunca leyendo cifras a ojo.

Señales de alerta en `status`: `ready=false`, `mode` distinto de `paper`, `pending_orders` o
`unknown_orders` > 0, último ciclo con error, datos viejos. Kill switch: cripto se apaga a −45% y
ETFs a −25% desde el máximo; se avisa a 5 puntos.

## Arena

- Pausar las cuatro carteras (cancela cotizaciones y conserva inventario): `tl.py arena-pause-all`.
- Detener el servicio, conservando el volumen con la base y los respaldos: `tl.py stop trading-arena`.
- Volver a levantarlo: `tl.py redeploy trading-arena`. Las carteras siguen en pausa hasta reanudarlas.

## Desplegar el piloto

1. Pruebas en verde en Python 3.13 (nube o Mac) y commit en `main`.
2. En el shell del equipo, con Python 3.13 (`uv python install 3.13`) y la CLI (`npx -y @railway/cli`):
   ```sh
   set -a; . "../.secretos/claude.env"; set +a
   uv run -p 3.13 --no-project python scripts/railway/package.py runtime-data/railway/<RELEASE>/bundle
   npx -y @railway/cli link --project 24021d85-bbad-4f2c-850c-e1230822e7b0 --environment production --service trading-lab
   npx -y @railway/cli up runtime-data/railway/<RELEASE>/bundle --path-as-root --service trading-lab --environment production --detach
   ```
3. Verificar: `tl.py check`, `/api/status` con `ready=true` y el siguiente ciclo diario sin errores.
   Si algo sale mal: volver a desplegar el bundle anterior. Nunca hacer rollback de datos.

El paquete excluye estado, secretos e informes. El volumen conserva SQLite y respaldos entre
despliegues. Detalle completo y recuperación: `docs/RAILWAY_RUNBOOK.md`.

## Qué no hace Claude aunque tenga acceso

Cambiar `mode`, crear llaves de exchange, tocar variables o secretos de Railway, activar dos
escritores, editar SQLite a mano, borrar volúmenes o respaldos, o poner dinero real.
