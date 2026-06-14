import re
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.models.schemas import AskRequest
from app.services.llm_service import (
    generate_answer_from_context,
    generate_general_answer,
)
from app.services.vector_store import get_vector_store, search_vector_store
from app.storage.memory_store import (
    append_chat_turn,
    get_collection_metadata,
    get_chat_history,
    get_document_metadata,
    get_latest_collection_id,
)


router = APIRouter()

TOP_K_CHUNKS = 5
DOCUMENT_SCOPED_SIMILARITY_THRESHOLD = 1.15
DOCUMENT_GENERAL_SIMILARITY_THRESHOLD = 0.85
EXACT_MATCH_SIMILARITY_THRESHOLD = 0.55
RELATIVE_CITATION_MARGIN = 0.35
MIN_UNSCOPED_KEYWORD_OVERLAP = 2
WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.-]*")
STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "about",
    "basic",
    "can",
    "could",
    "describe",
    "detail",
    "details",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "give",
    "hello",
    "help",
    "how",
    "info",
    "information",
    "is",
    "it",
    "know",
    "me",
    "of",
    "on",
    "overview",
    "please",
    "some",
    "tell",
    "the",
    "there",
    "this",
    "to",
    "u",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
}


def _resolve_collection_id(collection_id: str | None) -> str | None:
    return (collection_id or "").strip() or None


def _resolve_document_id(document_id: str | None) -> str | None:
    return (document_id or "").strip() or None


def _resolve_session_id(session_id: str | None) -> str:
    return (session_id or "").strip() or str(uuid.uuid4())


def _is_document_scoped_question(question: str) -> bool:
    q = question.lower()
    pdf_keywords = [
        "in this pdf",
        "in the pdf",
        "from the pdf",
        "from this document",
        "from the document",
        "in the document",
        "according to the pdf",
        "according to the document",
        "uploaded file",
        "uploaded document",
        "this file",
        "this document",
        "from page",
        "page ",
        "chapter ",
        "summarize the pdf",
        "summarize this document",
    ]

    return any(keyword in q for keyword in pdf_keywords)


def _build_matches(results) -> list[dict]:
    matches = []

    for doc, score in results:
        matches.append(
            {
                "page": doc.metadata.get("page", "unknown"),
                "filename": doc.metadata.get("filename", "Unknown document"),
                "document_id": doc.metadata.get("document_id"),
                "text": doc.page_content,
                "score": float(score),
                "chunk_id": doc.metadata.get("chunk_id"),
            }
        )

    return matches


def _build_citations(matches: list[dict]) -> list[dict]:
    citations = []
    seen = set()

    for match in matches:
        filename = match["filename"]
        page = match["page"]
        citation_key = (filename, page)

        if citation_key in seen:
            continue

        seen.add(citation_key)
        citations.append({"filename": filename, "page": page})

    return citations


def _significant_terms(text: str) -> set[str]:
    return {
        token.lower().strip(".")
        for token in WORD_PATTERN.findall(text)
        if len(token) > 2 and token.lower().strip(".") not in STOPWORDS
    }


def _keyword_overlap(question: str, matches: list[dict]) -> set[str]:
    question_terms = _significant_terms(question)

    if not question_terms:
        return set()

    context_terms = set()

    for match in matches[:3]:
        context_terms.update(_significant_terms(match.get("text", "")))
        context_terms.update(_significant_terms(match.get("filename", "")))

    return question_terms & context_terms


def _should_answer_from_documents(
    question: str,
    matches: list[dict],
    document_scoped: bool,
) -> bool:
    if not matches:
        return False

    best_score = matches[0]["score"]

    if document_scoped:
        return best_score <= DOCUMENT_SCOPED_SIMILARITY_THRESHOLD

    if best_score > DOCUMENT_GENERAL_SIMILARITY_THRESHOLD:
        return False

    question_terms = _significant_terms(question)
    overlap_count = len(_keyword_overlap(question, matches))

    if len(question_terms) < MIN_UNSCOPED_KEYWORD_OVERLAP:
        return False

    if best_score <= EXACT_MATCH_SIMILARITY_THRESHOLD:
        return overlap_count >= 1

    return overlap_count >= MIN_UNSCOPED_KEYWORD_OVERLAP


def _filter_relevant_matches(
    matches: list[dict],
    document_scoped: bool,
) -> list[dict]:
    if not matches:
        return []

    best_score = matches[0]["score"]
    threshold = (
        DOCUMENT_SCOPED_SIMILARITY_THRESHOLD
        if document_scoped
        else DOCUMENT_GENERAL_SIMILARITY_THRESHOLD
    )
    score_limit = min(threshold, best_score + RELATIVE_CITATION_MARGIN)
    return [match for match in matches if match["score"] <= score_limit]


@router.post("/ask")
def ask_question(
    payload: AskRequest,
    user: dict = Depends(get_current_user),
):
    question = payload.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    collection_id = _resolve_collection_id(payload.collection_id)
    document_id = _resolve_document_id(payload.document_id)
    session_id = _resolve_session_id(payload.session_id)
    document_scoped = _is_document_scoped_question(question)
    user_id = user["user_id"]

    if document_id:
        document = get_document_metadata(user_id, document_id)

        if not document:
            raise HTTPException(status_code=404, detail="Document was not found.")

        if collection_id and collection_id != document["collection_id"]:
            raise HTTPException(
                status_code=400,
                detail="Document does not belong to the selected collection.",
            )

        collection_id = collection_id or document["collection_id"]

    if document_scoped and not collection_id and not document_id:
        collection_id = get_latest_collection_id(user_id)

    if collection_id and not get_collection_metadata(user_id, collection_id):
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    if document_scoped and not collection_id and not document_id:
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF before asking a document-specific question.",
        )

    try:
        matches = []

        if collection_id or document_id:
            vector_store = get_vector_store()
            try:
                results = search_vector_store(
                    vector_store,
                    question,
                    user_id=user_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    top_k=TOP_K_CHUNKS,
                )
                matches = _build_matches(results)
            except Exception:
                if document_scoped:
                    raise
                matches = []

        if not _should_answer_from_documents(question, matches, document_scoped):
            if document_scoped:
                answer = (
                    "I could not find enough evidence in the uploaded PDF to answer "
                    "that confidently."
                )
                source = "no_match"
            else:
                answer = generate_general_answer(question)
                source = "general"
            citations = []
        else:
            relevant_matches = _filter_relevant_matches(matches, document_scoped)
            history = get_chat_history(user_id, session_id)
            answer = generate_answer_from_context(question, relevant_matches, history)
            source = "pdf"
            citations = _build_citations(relevant_matches)

        append_chat_turn(
            user_id,
            session_id,
            collection_id,
            question,
            answer,
            source,
            citations,
        )

        return {
            "question": question,
            "answer": answer,
            "source": source,
            "session_id": session_id,
            "collection_id": collection_id,
            "document_id": document_id,
            "citations": citations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate answer: {str(e)}",
        )
