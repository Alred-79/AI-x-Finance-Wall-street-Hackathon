FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 AUTO_INDEX=0 DATA_DIR=/app/data PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src ./src
COPY datasets ./datasets
COPY --from=web /web/dist ./frontend/dist
RUN mkdir -p /app/data/cache/fastembed && python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/data/cache/fastembed')" \
    || echo "embedding model warm-up skipped; it will download on first use"
EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.app.main:app --host 0.0.0.0 --port ${PORT}"]
