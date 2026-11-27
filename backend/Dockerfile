FROM python:3.12-slim

ARG INSTALL_PLAYWRIGHT_BROWSER=false

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client && rm -rf /var/lib/apt/lists/*
RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data/documents /data/backups \
    && chown -R app:app /data

COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && mkdir -p /ms-playwright \
    && if [ "$INSTALL_PLAYWRIGHT_BROWSER" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libatomic1 \
        && playwright install --only-shell --with-deps chromium \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && chmod -R a+rX /ms-playwright
COPY --chown=app:app . .

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
