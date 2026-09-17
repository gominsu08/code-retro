FROM node:24-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build -- --logLevel warn

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production COOKIE_SECURE=true PORT=8000
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY server/ ./server/
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps . && useradd --uid 10001 --create-home appuser
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY web/public/favicon.svg ./web/public/favicon.svg
COPY --from=web /app/web/dist ./web/dist
USER appuser
EXPOSE 8000
CMD ["python", "-m", "server.launch"]
