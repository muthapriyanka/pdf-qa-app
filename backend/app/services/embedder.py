import os
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/all-MiniLM-L6-v2",
)
HF_LOCAL_FILES_ONLY = os.getenv("HF_LOCAL_FILES_ONLY", "false").lower() == "true"


@lru_cache(maxsize=1)
def get_embedding_model() -> HuggingFaceEmbeddings:
    model_kwargs = {"local_files_only": True} if HF_LOCAL_FILES_ONLY else {}
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs=model_kwargs,
    )


class LazyHuggingFaceEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return get_embedding_model().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return get_embedding_model().embed_query(text)


def get_embedding(text: str) -> list[float]:
    return get_embedding_model().embed_query(text)


embedding_model = LazyHuggingFaceEmbeddings()
