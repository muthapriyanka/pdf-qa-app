import os
import re
from typing import Any

import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
TRAILING_FOLLOW_UP_PATTERN = re.compile(
    r"\n+\s*(Would you like|Do you want|Let me know if|If you want|If you'd like)"
    r"[\s\S]*$",
    re.IGNORECASE,
)
DOCUMENT_CITATION_PATTERN = re.compile(
    r"\s*\[[^\]\n]*(?:\.pdf|p\.\s*\d+|page\s*\d+|source\s*\d+)[^\]\n]*\]\s*",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://\S+")
DANGLING_REFERENCE_PATTERN = re.compile(
    r"\s*(?:See|For more details,? see|Refer to)\s*$",
    re.IGNORECASE,
)


def _call_ollama(prompt: str) -> str:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                },
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not reach Ollama. Make sure Ollama is running and the model "
            f"'{MODEL_NAME}' is available."
        ) from exc

    return response.json().get("response", "").strip()


def _format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "No previous conversation."

    return "\n".join(
        f"User: {turn['question']}\nAssistant: {turn['answer']}"
        for turn in history[-4:]
    )


def _format_context(matches: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"Document: {match.get('filename', 'Unknown document')}\n"
        f"Page: {match['page']}\n"
        f"Text:\n{match['text']}"
        for match in matches
    )


def _clean_trailing_follow_up(answer: str) -> str:
    return TRAILING_FOLLOW_UP_PATTERN.sub("", answer).strip()


def _clean_document_answer(answer: str) -> str:
    answer = _clean_trailing_follow_up(answer)
    answer = DOCUMENT_CITATION_PATTERN.sub("", answer)
    answer = URL_PATTERN.sub("", answer)
    answer = DANGLING_REFERENCE_PATTERN.sub("", answer)
    return answer.strip()


def generate_answer_from_context(
    question: str,
    matches: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> str:
    prompt = f"""
You are a careful multi-document question-answering assistant.

Rules:
- Answer using only the supplied document context and prior conversation.
- Treat the document context as the source of truth. Do not add outside facts,
  assumptions, or examples that are not supported by the context.
- Write in clear, natural language. You may paraphrase the document, but do not
  change its meaning.
- Do not write citations, page numbers, filenames, source labels, markdown
  links, URLs, or bracketed references in the answer text. The application will
  show verified citations separately.
- Do not mention source labels, distance scores, retrieval scores, or the phrase
  "provided document context" in the final answer.
- If the context only partially answers the question, answer the supported part
  and clearly say what could not be verified from the uploaded documents.
- If the context does not contain the answer, say you could not find enough
  evidence in the uploaded documents. Do not fill the gap from general knowledge.
- Do not end with a follow-up question such as "Would you like...".
- Be concise, but include enough detail to be useful.

Previous conversation:
{_format_history(history or [])}

Document context:
{_format_context(matches)}

Question:
{question}

Answer:
"""
    return _clean_document_answer(_call_ollama(prompt))


def generate_general_answer(question: str) -> str:
    prompt = f"""
You are a helpful assistant. Answer the question clearly and naturally.
Do not invent document citations or pretend the answer came from an uploaded
PDF. Do not end with a follow-up question such as "Would you like...".

Question:
{question}

Answer:
"""
    return _clean_trailing_follow_up(_call_ollama(prompt))
