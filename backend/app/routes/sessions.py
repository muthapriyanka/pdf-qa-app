from fastapi import APIRouter, HTTPException

from app.models.schemas import CreateSessionRequest, UpdateSessionRequest
from app.storage.memory_store import (
    clear_chat_messages,
    create_chat_session,
    delete_chat_session,
    get_collection_metadata,
    list_chat_sessions,
    list_collection_metadata,
    rename_chat_session,
    update_chat_session,
)


router = APIRouter()


def _normalize_collection_id(collection_id: str | None) -> str | None:
    value = (collection_id or "").strip()
    return value if value and value != "general" else None


@router.get("/state")
def get_state():
    return {
        "collections": list_collection_metadata(),
        "sessions": list_chat_sessions(),
    }


@router.get("/sessions")
def get_sessions():
    return {"sessions": list_chat_sessions()}


@router.post("/sessions")
def create_session(payload: CreateSessionRequest):
    collection_id = _normalize_collection_id(payload.collection_id)

    if collection_id and not get_collection_metadata(collection_id):
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    return create_chat_session(
        collection_id=collection_id,
        title=(payload.title or "").strip() or "Chat",
    )


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: UpdateSessionRequest):
    title = payload.title.strip() if payload.title is not None else None
    collection_id = _normalize_collection_id(payload.collection_id)

    if payload.title is not None and not title:
        raise HTTPException(status_code=400, detail="Chat title cannot be empty.")

    if collection_id and not get_collection_metadata(collection_id):
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    if title is None and collection_id is None:
        raise HTTPException(status_code=400, detail="No chat updates were provided.")

    if collection_id is None:
        session = rename_chat_session(session_id, title or "")
    else:
        session = update_chat_session(session_id, title=title, collection_id=collection_id)

    if not session:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    deleted = delete_chat_session(session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return {"deleted": True, "session_id": session_id}


@router.delete("/sessions/{session_id}/messages")
def clear_session_messages(session_id: str):
    session = clear_chat_messages(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return session
