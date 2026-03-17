from sklearn.metrics.pairwise import cosine_similarity
from app.services.embedder import get_embedding


def retrieve_relevant_chunks(question: str, chunks: list, top_k: int = 3):
    question_embedding = get_embedding(question)

    chunk_embeddings = [chunk["embedding"] for chunk in chunks]

    similarities = cosine_similarity(
        [question_embedding],
        chunk_embeddings
    )[0]

    scored_chunks = []
    for chunk, score in zip(chunks, similarities):
        scored_chunks.append({
            "chunk_id": chunk["chunk_id"],
            "page": chunk["page"],
            "text": chunk["text"],
            "score": float(score)
        })

    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    return scored_chunks[:top_k]