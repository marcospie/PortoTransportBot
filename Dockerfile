FROM python:3.11-slim

# PYTHONUNBUFFERED keeps logs streaming on Railway/Heroku/Docker.
# PYTHONDONTWRITEBYTECODE avoids .pyc files the non-root user cannot always write.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so this layer is cached independently of the source code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user instead of root. A fixed UID/GID (10001) is used so
# that a mounted volume can be chowned to a predictable owner on the host:
#   sudo chown -R 10001:10001 ./data     # before `docker compose up`
RUN groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

# .dockerignore keeps .git/, tests/ and the local data/ directory out of the
# build context, so this no longer bakes them into the image.
COPY --chown=appuser:appuser . .

# Runtime data directory. Created (and owned by appuser) *after* the COPY so the
# JSON fallback storage and the GTFS cache stay writable by the non-root user.
# NOTE: if you bind-mount or volume-mount over /app/data, the mount's ownership
# wins - chown it to 10001:10001 on the host or the bot cannot write there.
RUN mkdir -p /app/data/gtfs /app/data/favorites /app/data/settings \
             /app/data/commuter /app/data/users \
 && chown -R appuser:appuser /app/data

USER appuser

# The Telegram worker is a long-poll process with no HTTP port, so an HTTP probe
# would be meaningless for it. Instead the check verifies the two things that
# actually break in production: the application package must still import
# (catches a broken build or a missing dependency) and /app/data must be writable
# by appuser (catches a volume mounted with the wrong ownership, which silently
# breaks favorites/settings storage in JSON fallback mode).
# The WhatsApp/web variant additionally gets an HTTP /health probe - see the
# healthcheck block in docker-compose.yml.
HEALTHCHECK --interval=60s --timeout=20s --start-period=45s --retries=3 \
    CMD python -c "import tempfile, bot.main; tempfile.NamedTemporaryFile(dir='/app/data').close()"

CMD ["python", "run.py"]
