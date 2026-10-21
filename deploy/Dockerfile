# syntax=docker/dockerfile:1
FROM node:20-alpine AS admin
WORKDIR /web
COPY apps/admin-web/package.json apps/admin-web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/admin-web/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/server:/app/packages/aoc_core:/app/packages/aoc_protocol \
    AOC_HOST=0.0.0.0 \
    AOC_PORT=8080 \
    AOC_ADMIN_STATIC_DIR=/app/apps/admin-web/dist
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt -r requirements.txt
COPY packages ./packages
COPY apps/server ./apps/server
COPY data ./data
COPY --from=admin /web/dist ./apps/admin-web/dist
EXPOSE 8080
CMD ["python", "apps/server/main.py", "--host", "0.0.0.0", "--port", "8080"]
