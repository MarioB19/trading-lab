FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src ARENA_ATTESTATION=/app/arena-attestation.json
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 trader \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trader
COPY src ./src
COPY config.yaml ./config.yaml
COPY configs/arena ./configs/arena
COPY reports/four_strategy_arena_v1_preregistro.md ./reports/four_strategy_arena_v1_preregistro.md
COPY dashboard/arena ./dashboard/arena
COPY arena-attestation.json release.json ./
ARG ARENA_SOURCE_COMMIT
ENV TRADING_LAB_BUILD_ID=$ARENA_SOURCE_COMMIT
RUN python -c 'from lab.arena import execution_proof; from lab.arena_hosted import PREREG; execution_proof(PREREG); from lab.arena_reporting import TZ; assert str(TZ) == "America/Mexico_City"'
ENTRYPOINT ["python", "-m", "lab.arena_hosted", "run"]
