import os
from pathlib import Path

from langchain_chroma import Chroma

from app.services.embedder import embedding_model


APP_DATA_DIR = os.getenv("APP_DATA_DIR")
CHROMA_DIR = os.getenv(
    "CHROMA_DIR",
    str(Path(APP_DATA_DIR) / "chroma_db")
    if APP_DATA_DIR
    else str(Path(__file__).resolve().parents[2] / "chroma_db"),
)
COLLECTION_NAME = "documents"


def get_vector_store():
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_model,
        persist_directory=CHROMA_DIR
    )


def create_vector_store(chunks, ids: list[str] | None = None):
    vector_store = get_vector_store()
    vector_store.add_documents(chunks, ids=ids)
    return vector_store


def search_vector_store(
    vector_store,
    question: str,
    collection_id: str | None = None,
    document_id: str | None = None,
    top_k: int = 3,
):
    if collection_id:
        search_filter = {"collection_id": collection_id}
    elif document_id:
        search_filter = {"document_id": document_id}
    else:
        return []

    return vector_store.similarity_search_with_score(
        question,
        k=top_k,
        filter=search_filter
    )
