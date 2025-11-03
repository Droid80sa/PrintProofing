FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY package.json package-lock.json ./
RUN npm ci --no-audit --fund=false

COPY tailwind.config.js postcss.config.js ./
COPY frontend ./frontend
COPY app/templates ./app/templates
COPY app/static ./app/static
COPY docs ./docs
COPY ["Updated UI", "Updated UI"]
RUN mkdir -p app/static/dist
RUN npm run build:css

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

WORKDIR /app

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY docs ./docs
COPY env.txt ./env.txt

COPY --from=frontend-builder /frontend/app/static/dist ./app/static/dist

RUN adduser --disabled-password --gecos '' appuser
RUN mkdir -p /mnt/proofs && chown appuser:appuser /mnt/proofs
RUN chown -R appuser:appuser /app

ENV PATH="/home/appuser/.local/bin:${PATH}"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app.app:app"]
