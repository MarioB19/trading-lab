# Imagen de mantenimiento de la arena (F1 del plan «Un dominio y estrategia ganadora»).
# Monta el volumen y responde /healthz; nunca arranca el worker ni rota respaldos.
# El modo lo fija la imagen (ENV), no una variable de Railway: el comando de arranque del
# servicio (`python -m lab.arena_hosted run`) sigue igual y despacha a lab.arena_maintenance.
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src ARENA_MAINTENANCE=read-only-backup
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 trader \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trader
COPY src ./src
COPY configs/arena ./configs/arena
COPY release.json ./
ARG ARENA_SOURCE_COMMIT
ENV TRADING_LAB_BUILD_ID=$ARENA_SOURCE_COMMIT
RUN python -c 'from lab import arena_maintenance; assert arena_maintenance.enabled(); from lab.arena import plan; plan()'
ENTRYPOINT ["python", "-m", "lab.arena_hosted", "run"]
