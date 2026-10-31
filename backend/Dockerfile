# Slim by default to fit a 512 MB instance; JavaScript pages are then rendered through Jina Reader.
# Build with --build-arg WITH_BROWSER=1 to include Playwright Chromium instead.
FROM python:3.13-slim
ARG WITH_BROWSER=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
 && if [ "$WITH_BROWSER" = "1" ]; then pip install ".[browser]" && python -m playwright install --with-deps chromium; \
    else pip install .; fi \
 && rm -rf app

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
# Raw files; the parsed text lives in Postgres, so losing this on restart is fine.
RUN pip install --no-deps . && useradd -m ritam && mkdir -p /app/data && chown -R ritam /app
USER ritam

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
