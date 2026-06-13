from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    collection_id: str | None = None
    document_id: str | None = None
    session_id: str | None = None


class CreateSessionRequest(BaseModel):
    collection_id: str | None = None
    title: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    collection_id: str | None = None
