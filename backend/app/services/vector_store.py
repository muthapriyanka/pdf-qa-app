
from langchain_chroma import Chroma
from app.services.embedder import embedding_model

CHROMA_DIR = "./chroma_db"
COLLECTION_NAME = "documents"


def get_vector_store():
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_model,
        persist_directory=CHROMA_DIR
    )


def create_vector_store(chunks):
    vector_store = get_vector_store()
    vector_store.add_documents(chunks)
    return vector_store


def search_vector_store(vector_store, question: str, document_id: str, top_k: int = 3):
    return vector_store.similarity_search_with_score(
        question,
        k=top_k,
        filter={"document_id": document_id}
    )