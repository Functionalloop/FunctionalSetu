# JANSETU API image. Build context is the repo root (see .dockerignore):
#   docker compose -f deploy/docker-compose.yml build
# The same image runs the API (default command) and the one-off scripts
# (migrate, create_super_admin, ...) through the compose service "ops".
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # uvicorn reads these: worker processes, and trust X-Forwarded-For from Caddy
    # (the API port is reachable only inside the compose network).
    WEB_CONCURRENCY=2 \
    FORWARDED_ALLOW_IPS=*

WORKDIR /srv/jansetu

COPY backend/pyproject.toml backend/constraints.txt backend/
COPY backend/app backend/app
RUN pip install -c backend/constraints.txt ./backend \
 && rm -rf backend/build backend/*.egg-info

# Migrations and scripts, for `docker compose run --rm ops python scripts/...`
COPY db db
COPY scripts scripts

# /srv/files: uploaded images (9.4). A new named volume copies this owner, so the API can write there.
RUN useradd --system --uid 10001 --no-create-home jansetu \
 && mkdir -p /srv/files && chown jansetu /srv/files && chmod 700 /srv/files
USER jansetu

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
