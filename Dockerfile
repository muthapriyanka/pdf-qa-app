FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    APP_DATA_DIR=/data \
    SQLITE_DB_PATH=/data/app_data.sqlite3 \
    CHROMA_DIR=/data/chroma_db \
    OLLAMA_MODELS=/data/ollama \
    HF_HOME=/data/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/data/sentence-transformers \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_URL=http://127.0.0.1:11434/api/generate \
    OLLAMA_MODEL=qwen2.5:0.5b \
    OLLAMA_TIMEOUT_SECONDS=180 \
    EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libgomp1 \
        zstd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

RUN useradd -m -u 1000 user \
    && mkdir -p /app /data \
    && chown -R user:user /app /data

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /app

COPY --chown=user:user backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY --chown=user:user backend /app/backend
COPY --chown=user:user frontend-simple /app/frontend-simple
COPY --chown=user:user docker/start.sh /app/start.sh

RUN chmod +x /app/start.sh

USER user

EXPOSE 7860

CMD ["/app/start.sh"]
