from fastapi import APIRouter, HTTPException
from app.models.schemas import AskRequest
from app.services.vector_store import get_vector_store, search_vector_store
from app.services.llm_service import generate_answer_from_context, generate_general_answer

router = APIRouter()

SIMILARITY_THRESHOLD = 1.5


def is_pdf_question(question: str) -> bool:
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
        "chapter "
    ]

    return any(keyword in q for keyword in pdf_keywords)


@router.post("/ask")
def ask_question(payload: AskRequest):
    question = payload.question.strip()
    document_id = payload.document_id.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        vector_store = get_vector_store()
        results = search_vector_store(vector_store, question, document_id=document_id, top_k=3)

        matches = []
        if results:
            for doc, score in results:
                matches.append({
                    "page": doc.metadata.get("page", "unknown"),
                    "text": doc.page_content,
                    "score": float(score)
                })

        force_pdf = is_pdf_question(question)

        if force_pdf and matches:
            best_score = matches[0]["score"]

            if best_score < SIMILARITY_THRESHOLD:
                answer = generate_answer_from_context(question, matches)
                return {
                    "question": question,
                    "answer": answer,
                    "source": "pdf",
                    "citations": [
                        {
                            "page": match["page"],
                            "snippet": match["text"][:300]
                        }
                        for match in matches
                    ]
                }

        answer = generate_general_answer(question)
        return {
            "question": question,
            "answer": answer,
            "source": "general",
            "citations": []
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate answer: {str(e)}")