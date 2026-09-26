# Proceso continuo para un servidor prendido 24/7 (opcional). Por defecto el bot ya corre cada
# hora en GitHub Actions; usa esto solo si quieres revisiones cada pocos minutos.
# Instrucciones en README → "Tiempo real 24/7 en un servidor".
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir "pandas>=2.1" "numpy>=1.26" "ccxt>=4.3" "pyyaml>=6.0" "requests>=2.31" \
 && pip install --no-cache-dir -e . --no-deps
# El repositorio completo (con state/ y config.yaml) se monta en /app al correr el contenedor.
CMD ["python", "-m", "lab.realtime", "--loop", "--every", "300"]
