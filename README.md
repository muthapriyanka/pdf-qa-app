---
title: Docuery AI
emoji: 📄
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
hf_oauth: true
hf_oauth_expiration_minutes: 43200
---

# Docuery AI

A full-stack RAG document assistant for asking questions across uploaded PDFs.

The app uses FastAPI, ChromaDB, LangChain text splitting, Hugging Face embeddings,
Ollama LLM inference, citation-backed answers, Hugging Face OAuth,
user-scoped SQLite chat/session persistence, multi-file upload, and a
responsive light/dark UI.
