# Hugging Face Docker Deployment

This project can run as one Docker container:

- FastAPI API
- Static React UI
- SQLite session storage
- Chroma vector store
- Ollama local inference
- Hugging Face and Google OAuth for private per-user workspaces

## Recommended Hugging Face Space

Create a new Hugging Face Space with:

- SDK: Docker
- Hardware: free CPU is okay for a lightweight demo
- Persistent storage: recommended if you want uploaded PDFs/chats to survive restarts
- `hf_oauth: true` in `README.md` so Hugging Face provides Hugging Face OAuth variables
- Optional Google OAuth credentials as Space secrets

The Hugging Face provider requests `openid profile`. The Google provider
requests `openid profile email`. Uploaded PDFs, collections, and chat history
are scoped to the signed-in user.

## Default Demo Model

The Dockerfile uses:

```text
OLLAMA_MODEL=qwen2.5:0.5b
```

This is intentionally tiny for free CPU deployment. For better answers, try:

```text
OLLAMA_MODEL=llama3.2:1b
```

Local development can still use your normal Ollama model, such as `llama3`.

## Environment Variables

Useful defaults are already in the Dockerfile:

```text
PORT=7860
APP_DATA_DIR=/data
SQLITE_DB_PATH=/data/app_data.sqlite3
CHROMA_DIR=/data/chroma_db
OLLAMA_MODELS=/data/ollama
HF_HOME=/data/huggingface
SENTENCE_TRANSFORMERS_HOME=/data/sentence-transformers
OLLAMA_URL=http://127.0.0.1:11434/api/generate
OLLAMA_MODEL=qwen2.5:0.5b
OLLAMA_TIMEOUT_SECONDS=180
```

Optional Google OAuth secrets:

```text
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

For Google login, add this authorized redirect URI in Google Cloud Console:

```text
https://muthapriyanka27-pdf-qa-assistant.hf.space/api/auth/google/callback
```

If you do not attach persistent storage, `/data` may reset when the Space restarts.

## Deploy With Hugging Face CLI

Log in from this project environment:

```bash
cd backend
./venv/bin/hf auth login
```

Then create the Space and upload the app:

```bash
./venv/bin/hf repos create muthapriyanka27/pdf-qa-assistant \
  --type space \
  --space-sdk docker \
  --exist-ok

cd ..
backend/venv/bin/hf upload muthapriyanka27/pdf-qa-assistant . . \
  --repo-type space \
  --include "README.md" \
  --include "Dockerfile" \
  --include ".dockerignore" \
  --include "DEPLOYMENT.md" \
  --include "docker/**" \
  --include "backend/app/**" \
  --include "backend/requirements.txt" \
  --include "frontend-simple/**" \
  --exclude "backend/venv/**" \
  --exclude "backend/chroma_db/**" \
  --exclude "backend/*.sqlite3" \
  --exclude "frontend-simple/node_modules/**" \
  --exclude "**/__pycache__/**" \
  --exclude "**/*.pyc" \
  --commit-message "Deploy Docker RAG demo"
```

## Local Docker Test

```bash
docker build -t doc-qa-rag .
docker run --rm -p 7860:7860 doc-qa-rag
```

Then open:

```text
http://localhost:7860
```
