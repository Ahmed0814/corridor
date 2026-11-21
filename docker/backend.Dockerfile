# One backend image, four processes (DECISIONS D-002):
#   api       uvicorn config.asgi:application ...
#   realtime  daphne config.asgi:application ...
#   worker    celery -A config worker ...
#   beat      celery -A config beat ...
# Build context: repository root.

FROM ghcr.io/astral-sh/uv:0.12.12 AS uv

# --------------------------------------------------------------------------- builder
FROM python:3.12.16-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --------------------------------------------------------------------------- runtime
FROM python:3.12.16-slim-bookworm AS runtime
# GeoDjango native libraries (GDAL pulls GEOS and PROJ). libcurl for kombu's SQS transport.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gdal-bin libcurl4 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app backend/ /app/

# Static assets for the internal admin, served by WhiteNoise. Build-time only settings:
# DJANGO_ENV=development uses the insecure local key, which never reaches runtime.
RUN DJANGO_ENV=development python manage.py collectstatic --noinput \
 && chown -R app:app /app/staticfiles

ARG RELEASE=dev
ENV RELEASE=${RELEASE}

USER app
EXPOSE 8000 8001
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/live', timeout=2).status == 200 else 1)" || exit 1

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
