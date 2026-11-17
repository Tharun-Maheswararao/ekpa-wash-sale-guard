# One container serves the API and the built React app on $PORT (Render, Fly, Railway all set it).
FROM node:20-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml backend/
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "python-multipart>=0.0.9"
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn washguard.api:app --app-dir backend --host 0.0.0.0 --port ${PORT}"]
