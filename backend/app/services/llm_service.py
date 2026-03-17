import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3"


def generate_answer_from_context(question: str, matches: list):
    context = "\n\n".join(
        [f"Page {m['page']}: {m['text']}" for m in matches]
    )

    prompt = f"""
You are a helpful PDF question-answering assistant.

Use the context below to answer the question if it is relevant.

If the context does not contain the answer, answer using your general knowledge.

Do not say "based on the context" unless the answer clearly comes from it.
Keep the answer clear and concise.

Context:
{context}

Question:
{question}

Answer:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
    )
    response.raise_for_status()
    return response.json()["response"]


def generate_general_answer(question: str):
    prompt = f"""
You are a helpful assistant. Answer the following question clearly and naturally.

Question:
{question}

Answer:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
    )
    response.raise_for_status()
    return response.json()["response"]