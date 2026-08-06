# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gfortran libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0-pthread libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 stokvel

WORKDIR /app

COPY --from=builder /root/.local /home/stokvel/.local
COPY --chown=stokvel:stokvel . .

RUN mkdir -p /app/data && chown -R stokvel:stokvel /app && chmod +x /app/entrypoint.sh

ENV PATH=/home/stokvel/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD sh -c 'curl -f http://localhost:${PORT:-5000}/healthz || exit 1'

ENTRYPOINT ["/app/entrypoint.sh"]
