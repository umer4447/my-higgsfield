# Darkroom API and worker. One image, two process types: the entrypoint decides.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# The Prisma Python client shells out to Node for its query engine.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Dependencies first, so a source change does not reinstall the world.
COPY api/pyproject.toml ./api/pyproject.toml
RUN pip install --no-cache-dir -e "./api[s3]"

# The schema has to be present before `prisma generate`.
COPY prisma ./prisma
RUN python -m prisma generate --schema prisma/schema.prisma

COPY api ./api

# Never run as root.
RUN useradd --create-home --uid 10001 darkroom \
 && chown -R darkroom:darkroom /srv
USER darkroom

ENV PYTHONPATH=/srv/api

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1

# Fluid Compute reuses instances, so one worker process per container and let
# the platform scale containers. Graceful shutdown drains in-flight requests.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "25"]
