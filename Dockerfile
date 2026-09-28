# Multi-platform official Python image, pinned by manifest digest.
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ARG SOURCE_SHA=uncommitted
LABEL org.opencontainers.image.source="https://github.com/MarioB19/trading-lab" \
      org.opencontainers.image.revision="$SOURCE_SHA"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src \
    TRADING_LAB_BUILD_ID=${SOURCE_SHA}
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 trader \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trader
COPY src ./src
COPY config.yaml ./config.yaml
COPY configs/experiments/aggressive_v1.yaml ./configs/experiments/aggressive_v1.yaml
COPY reports ./reports
COPY dashboard ./dashboard
RUN python -c 'import yaml; assert yaml.safe_load(open("config.yaml"))["mode"] == "paper"'
USER 10001:10001
CMD ["python", "-m", "lab.runtime", "--config", "/app/config.yaml", "--data-dir", "/var/lib/trading-lab", "--interval", "300"]
