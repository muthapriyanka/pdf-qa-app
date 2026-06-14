from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.models.schemas import CreateSessionRequest, UpdateSessionRequest
from app.services.vector_store import delete_collection_vectors
from app.storage.memory_store import (
    clear_chat_messages,
    delete_collection_metadata,
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
def get_state(user: dict = Depends(get_current_user)):
    return {
        "user": user,
        "collections": list_collection_metadata(user["user_id"]),
        "sessions": list_chat_sessions(user["user_id"]),
    }


@router.get("/sessions")
def get_sessions(user: dict = Depends(get_current_user)):
    return {"sessions": list_chat_sessions(user["user_id"])}


@router.post("/sessions")
def create_session(
    payload: CreateSessionRequest,
    user: dict = Depends(get_current_user),
):
    collection_id = _normalize_collection_id(payload.collection_id)

    if collection_id and not get_collection_metadata(user["user_id"], collection_id):
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    return create_chat_session(
        user_id=user["user_id"],
        collection_id=collection_id,
        title=(payload.title or "").strip() or "Chat",
    )


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: str, user: dict = Depends(get_current_user)):
    collection = get_collection_metadata(user["user_id"], collection_id)

    if not collection:
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    deleted_collection = delete_collection_metadata(user["user_id"], collection_id)

    if not deleted_collection:
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    deleted_chunks = 0

    try:
        deleted_chunks = delete_collection_vectors(collection)
    except Exception:
        deleted_chunks = 0

    return {
        "deleted": True,
        "collection_id": collection_id,
        "deleted_chunks": deleted_chunks,
    }


@router.patch("/sessions/{session_id}")
def update_session(
    session_id: str,
    payload: UpdateSessionRequest,
    user: dict = Depends(get_current_user),
):
    title = payload.title.strip() if payload.title is not None else None
    collection_id = _normalize_collection_id(payload.collection_id)

    if payload.title is not None and not title:
        raise HTTPException(status_code=400, detail="Chat title cannot be empty.")

    if collection_id and not get_collection_metadata(user["user_id"], collection_id):
        raise HTTPException(status_code=404, detail="Document collection was not found.")

    if title is None and collection_id is None:
        raise HTTPException(status_code=400, detail="No chat updates were provided.")

    if collection_id is None:
        session = rename_chat_session(user["user_id"], session_id, title or "")
    else:
        session = update_chat_session(
            user["user_id"],
            session_id,
            title=title,
            collection_id=collection_id,
        )

    if not session:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    deleted = delete_chat_session(user["user_id"], session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return {"deleted": True, "session_id": session_id}


@router.delete("/sessions/{session_id}/messages")
def clear_session_messages(session_id: str, user: dict = Depends(get_current_user)):
    session = clear_chat_messages(user["user_id"], session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Chat session was not found.")

    return session
