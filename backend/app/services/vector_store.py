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


def delete_collection_vectors(collection: dict) -> int:
    ids = []
    collection_id = collection["collection_id"]

    for document in collection.get("documents", []):
        document_id = document["document_id"]
        total_chunks = int(document.get("total_chunks") or 0)
        ids.extend(
            f"{collection_id}:{document_id}:{index}"
            for index in range(total_chunks)
        )

    if not ids:
        return 0

    vector_store = get_vector_store()
    vector_store.delete(ids=ids)
    return len(ids)


def search_vector_store(
    vector_store,
    question: str,
    user_id: str | None = None,
    collection_id: str | None = None,
    document_id: str | None = None,
    top_k: int = 3,
):
    filters = []

    if user_id:
        filters.append({"user_id": user_id})

    if collection_id:
        filters.append({"collection_id": collection_id})
    elif document_id:
        filters.append({"document_id": document_id})
    else:
        return []

    search_filter = filters[0] if len(filters) == 1 else {"$and": filters}

    return vector_store.similarity_search_with_score(
        question,
        k=top_k,
        filter=search_filter
    )
