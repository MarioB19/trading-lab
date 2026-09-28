# Multi-platform official Python image, pinned by manifest digest.
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 trader \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trader
ARG SOURCE_SHA=uncommitted
LABEL org.opencontainers.image.source="https://github.com/MarioB19/trading-lab" \
      org.opencontainers.image.revision="$SOURCE_SHA"
ENV TRADING_LAB_BUILD_ID=${SOURCE_SHA}
COPY src ./src
COPY config.yaml ./config.yaml
COPY dashboard ./dashboard
RUN python -c 'import yaml; from lab.runtime import validate_config; validate_config(yaml.safe_load(open("config.yaml")))'
USER 10001:10001
CMD ["python", "-m", "lab.runtime", "--config", "/app/config.yaml", "--data-dir", "/var/lib/trading-lab", "--interval", "300"]

# Explicit historical research target; never selected by operational delivery.
FROM base AS research
LABEL org.tradinglab.profile="research-archive"
COPY configs/experiments/aggressive_v1.yaml ./configs/experiments/aggressive_v1.yaml
COPY configs/experiments/aggressive_v2.yaml ./configs/experiments/aggressive_v2.yaml
COPY reports ./reports
ARG REQUIRE_RESEARCH_ATTESTATION=true
RUN if [ "$REQUIRE_RESEARCH_ATTESTATION" = "true" ]; then \
      python -c 'import json; from lab.data import ROOT; from lab.aggressive_plan import comparison_plan, preregistration_path; from lab.research_attestation import verify_attestation; p = ROOT / "configs/experiments/aggressive_v2.yaml"; a = ROOT / "reports/attestations/aggressive-v2.json"; d = json.loads(a.read_text()); plan, variants = comparison_plan(p); verify_attestation(ROOT, a, p, preregistration_path(plan), d["preregistration_commit"], plan, [v["id"] for v in variants]); print("Preregistration and packaged code verified")'; \
    elif [ "$REQUIRE_RESEARCH_ATTESTATION" != "false" ]; then exit 2; fi

# Last stage is the default: validated operational paper, no experiment plans,
# research reports, preregistration proof, data, secrets, or experimental jobs.
FROM base AS runtime
LABEL org.tradinglab.profile="operational-paper"
