# Railway builds only the operational paper application from an allowlisted bundle.
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 trader \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trader
COPY src ./src
COPY config.yaml ./config.yaml
COPY dashboard ./dashboard
COPY release.json ./release.json
RUN python -c 'import yaml; from lab.runtime import validate_config; validate_config(yaml.safe_load(open("config.yaml")))'
# Root only prepares the mounted directories; entrypoint drops UID/GID before
# starting either HTTP or the paper worker. No recursive chown of the volume.
ENTRYPOINT ["python", "-m", "lab.railway_entrypoint"]
