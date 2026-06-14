import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_HISTORY_TURNS = 6
LEGACY_USER_ID = "legacy-user"
APP_DATA_DIR = os.getenv("APP_DATA_DIR")
DATABASE_PATH = Path(
    os.getenv(
        "SQLITE_DB_PATH",
        str(Path(APP_DATA_DIR) / "app_data.sqlite3")
        if APP_DATA_DIR
        else str(Path(__file__).resolve().parents[2] / "app_data.sqlite3"),
    )
)

document_store: dict[str, Any] = {
    "current_collection_id": None,
    "current_document_id": None,
    "collections": {},
    "documents": {},
    # Compatibility keys for the earlier single-document implementation.
    "filename": None,
    "document_id": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(connection, table, column):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def initialize_database() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                avatar_url TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                avatar_url TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS collections (
                collection_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'legacy-user',
                total_files INTEGER NOT NULL,
                total_pages_extracted INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                collection_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                total_pages_extracted INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                FOREIGN KEY (collection_id)
                    REFERENCES collections(collection_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'legacy-user',
                collection_id TEXT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (collection_id)
                    REFERENCES collections(collection_id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                source TEXT,
                citations_json TEXT,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id)
                    REFERENCES chat_sessions(session_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_documents_collection
                ON documents(collection_id);

            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_position
                ON chat_messages(session_id, position);

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
                ON auth_sessions(expires_at);
            """
        )
        _ensure_column(
            connection,
            "collections",
            "user_id",
            "user_id TEXT NOT NULL DEFAULT 'legacy-user'",
        )
        _ensure_column(
            connection,
            "chat_sessions",
            "user_id",
            "user_id TEXT NOT NULL DEFAULT 'legacy-user'",
        )
        connection.execute(
            "UPDATE collections SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
            (LEGACY_USER_ID,),
        )
        connection.execute(
            "UPDATE chat_sessions SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
            (LEGACY_USER_ID,),
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_collections_user_uploaded
            ON collections(user_id, uploaded_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
            ON chat_sessions(user_id, updated_at DESC)
            """
        )


def _normalize_collection_id(collection_id: str | None) -> str | None:
    value = (collection_id or "").strip()
    return value if value and value != "general" else None


def _decode_citations(citations_json: str | None) -> list[dict[str, Any]]:
    if not citations_json:
        return []

    try:
        citations = json.loads(citations_json)
    except json.JSONDecodeError:
        return []

    return citations if isinstance(citations, list) else []


def _row_to_document(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "document_id": row["document_id"],
        "collection_id": row["collection_id"],
        "filename": row["filename"],
        "total_pages_extracted": row["total_pages_extracted"],
        "total_chunks": row["total_chunks"],
    }


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["message_id"],
        "role": row["role"],
        "text": row["text"],
        "source": row["source"],
        "citations": _decode_citations(row["citations_json"]),
        "created_at": row["created_at"],
    }


def _collection_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    document_rows = connection.execute(
        """
        SELECT document_id, collection_id, filename, total_pages_extracted, total_chunks
        FROM documents
        WHERE collection_id = ?
        ORDER BY rowid
        """,
        (row["collection_id"],),
    ).fetchall()

    return {
        "collection_id": row["collection_id"],
        "user_id": row["user_id"],
        "documents": [_row_to_document(document) for document in document_rows],
        "total_files": row["total_files"],
        "total_pages_extracted": row["total_pages_extracted"],
        "total_chunks": row["total_chunks"],
        "uploaded_at": row["uploaded_at"],
    }


def _session_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    include_messages: bool = True,
) -> dict[str, Any]:
    messages = []

    if include_messages:
        message_rows = connection.execute(
            """
            SELECT message_id, role, text, source, citations_json, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY position
            """,
            (row["session_id"],),
        ).fetchall()
        messages = [_row_to_message(message) for message in message_rows]

    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "collection_id": row["collection_id"],
        "title": row["title"],
        "messages": messages,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _refresh_document_store(collection: dict[str, Any]) -> None:
    document_store["collections"][collection["collection_id"]] = collection
    document_store["current_collection_id"] = collection["collection_id"]

    if collection["documents"]:
        first_document = collection["documents"][0]
        document_store["current_document_id"] = first_document["document_id"]
        document_store["filename"] = first_document["filename"]
        document_store["document_id"] = first_document["document_id"]

    for document in collection["documents"]:
        document_store["documents"][document["document_id"]] = document


def save_collection_metadata(
    user_id: str,
    collection_id: str,
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    total_pages = sum(document["total_pages_extracted"] for document in documents)
    total_chunks = sum(document["total_chunks"] for document in documents)
    uploaded_at = _utc_now()

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO collections (
                collection_id,
                user_id,
                total_files,
                total_pages_extracted,
                total_chunks,
                uploaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_id) DO UPDATE SET
                user_id = excluded.user_id,
                total_files = excluded.total_files,
                total_pages_extracted = excluded.total_pages_extracted,
                total_chunks = excluded.total_chunks,
                uploaded_at = excluded.uploaded_at
            """,
            (
                collection_id,
                user_id,
                len(documents),
                total_pages,
                total_chunks,
                uploaded_at,
            ),
        )
        connection.execute(
            "DELETE FROM documents WHERE collection_id = ?",
            (collection_id,),
        )

        for document in documents:
            connection.execute(
                """
                INSERT INTO documents (
                    document_id,
                    collection_id,
                    filename,
                    total_pages_extracted,
                    total_chunks
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    document["document_id"],
                    collection_id,
                    document["filename"],
                    document["total_pages_extracted"],
                    document["total_chunks"],
                ),
            )

    metadata = get_collection_metadata(user_id, collection_id)

    if metadata:
        _refresh_document_store(metadata)
        return metadata

    raise RuntimeError("Collection metadata was not saved.")


def get_collection_metadata(
    user_id: str,
    collection_id: str,
) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT collection_id, user_id, total_files, total_pages_extracted, total_chunks, uploaded_at
            FROM collections
            WHERE collection_id = ? AND user_id = ?
            """,
            (collection_id, user_id),
        ).fetchone()

        return _collection_from_row(connection, row) if row else None


def list_collection_metadata(user_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT collection_id, user_id, total_files, total_pages_extracted, total_chunks, uploaded_at
            FROM collections
            WHERE user_id = ?
            ORDER BY uploaded_at DESC
            """,
            (user_id,),
        ).fetchall()

        return [_collection_from_row(connection, row) for row in rows]


def get_latest_collection_id(user_id: str) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT collection_id
            FROM collections
            WHERE user_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        return row["collection_id"] if row else None


def get_document_metadata(user_id: str, document_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT d.document_id, d.collection_id, d.filename, d.total_pages_extracted, d.total_chunks
            FROM documents d
            JOIN collections c ON c.collection_id = d.collection_id
            WHERE d.document_id = ? AND c.user_id = ?
            """,
            (document_id, user_id),
        ).fetchone()

        return _row_to_document(row) if row else None


def create_chat_session(
    user_id: str,
    collection_id: str | None = None,
    title: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    normalized_collection_id = _normalize_collection_id(collection_id)
    next_session_id = session_id or str(uuid.uuid4())
    now = _utc_now()

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions (
                session_id,
                user_id,
                collection_id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO NOTHING
            """,
            (
                next_session_id,
                user_id,
                normalized_collection_id,
                title or "Chat",
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (next_session_id, user_id),
        ).fetchone()

        return _session_from_row(connection, row)


def list_chat_sessions(user_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user_id,),
        ).fetchall()

        return [_session_from_row(connection, row) for row in rows]


def get_chat_session(user_id: str, session_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        return _session_from_row(connection, row) if row else None


def clear_chat_messages(user_id: str, session_id: str) -> dict[str, Any] | None:
    now = _utc_now()

    with _connect() as connection:
        session = connection.execute(
            """
            SELECT session_id
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        if not session:
            return None

        connection.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET title = 'Chat', updated_at = ?
            WHERE session_id = ?
            """,
            (now, session_id),
        )

        row = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        return _session_from_row(connection, row)


def rename_chat_session(
    user_id: str,
    session_id: str,
    title: str,
) -> dict[str, Any] | None:
    normalized_title = title.strip()[:80]
    now = _utc_now()

    if not normalized_title:
        return None

    with _connect() as connection:
        connection.execute(
            """
            UPDATE chat_sessions
            SET title = ?, updated_at = ?
            WHERE session_id = ? AND user_id = ?
            """,
            (normalized_title, now, session_id, user_id),
        )
        row = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        return _session_from_row(connection, row) if row else None


def update_chat_session(
    user_id: str,
    session_id: str,
    title: str | None = None,
    collection_id: str | None = None,
) -> dict[str, Any] | None:
    normalized_title = title.strip()[:80] if title is not None else None
    normalized_collection_id = _normalize_collection_id(collection_id)
    now = _utc_now()

    if title is not None and not normalized_title:
        return None

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT session_id
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        if not row:
            return None

        connection.execute(
            """
            UPDATE chat_sessions
            SET title = COALESCE(?, title),
                collection_id = ?,
                updated_at = ?
            WHERE session_id = ? AND user_id = ?
            """,
            (normalized_title, normalized_collection_id, now, session_id, user_id),
        )
        updated_row = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()

        return _session_from_row(connection, updated_row)


def delete_chat_session(user_id: str, session_id: str) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM chat_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )

        return cursor.rowcount > 0


def get_chat_history(user_id: str, session_id: str) -> list[dict[str, str]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT m.role, m.text
            FROM chat_messages m
            JOIN chat_sessions s ON s.session_id = m.session_id
            WHERE m.session_id = ? AND s.user_id = ?
            ORDER BY m.position DESC
            LIMIT ?
            """,
            (session_id, user_id, MAX_HISTORY_TURNS * 2),
        ).fetchall()

    ordered_rows = list(reversed(rows))
    history = []
    pending_question = None

    for row in ordered_rows:
        if row["role"] == "user":
            pending_question = row["text"]
        elif row["role"] == "assistant" and pending_question:
            history.append({"question": pending_question, "answer": row["text"]})
            pending_question = None

    return history[-MAX_HISTORY_TURNS:]


def append_chat_turn(
    user_id: str,
    session_id: str,
    collection_id: str | None,
    question: str,
    answer: str,
    source: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> None:
    normalized_collection_id = _normalize_collection_id(collection_id)
    now = _utc_now()

    with _connect() as connection:
        session = connection.execute(
            """
            SELECT session_id, user_id, collection_id, title
            FROM chat_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

        if session and session["user_id"] != user_id:
            raise ValueError("Chat session does not belong to this user.")

        if not session:
            connection.execute(
                """
                INSERT INTO chat_sessions (
                    session_id,
                    user_id,
                    collection_id,
                    title,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    normalized_collection_id,
                    question[:44],
                    now,
                    now,
                ),
            )
        else:
            normalized_collection_id = normalized_collection_id or session["collection_id"]

        message_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM chat_messages
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()["count"]
        current_position = connection.execute(
            """
            SELECT COALESCE(MAX(position), -1) AS position
            FROM chat_messages
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()["position"]

        if message_count == 0:
            connection.execute(
                """
                UPDATE chat_sessions
                SET title = ?
                WHERE session_id = ?
                """,
                (question[:44], session_id),
            )

        connection.execute(
            """
            INSERT INTO chat_messages (
                message_id,
                session_id,
                role,
                text,
                source,
                citations_json,
                position,
                created_at
            )
            VALUES (?, ?, 'user', ?, NULL, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                question,
                current_position + 1,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO chat_messages (
                message_id,
                session_id,
                role,
                text,
                source,
                citations_json,
                position,
                created_at
            )
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                answer,
                source,
                json.dumps(citations or []),
                current_position + 2,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET collection_id = ?, updated_at = ?
            WHERE session_id = ? AND user_id = ?
            """,
            (normalized_collection_id, now, session_id, user_id),
        )


def upsert_user(user: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now()
    user_id = str(user["user_id"])
    username = str(user.get("username") or "Hugging Face User")
    avatar_url = user.get("avatar_url")

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, username, avatar_url, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                avatar_url = excluded.avatar_url,
                updated_at = excluded.updated_at
            """,
            (user_id, username, avatar_url, now),
        )

    return {
        "user_id": user_id,
        "username": username,
        "avatar_url": avatar_url,
    }


def create_auth_session(
    session_token: str,
    user: dict[str, Any],
    expires_at: str,
) -> dict[str, Any]:
    stored_user = upsert_user(user)
    now = _utc_now()

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions (
                session_token,
                user_id,
                username,
                avatar_url,
                created_at,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_token) DO UPDATE SET
                user_id = excluded.user_id,
                username = excluded.username,
                avatar_url = excluded.avatar_url,
                expires_at = excluded.expires_at
            """,
            (
                session_token,
                stored_user["user_id"],
                stored_user["username"],
                stored_user.get("avatar_url"),
                now,
                expires_at,
            ),
        )

    return stored_user


def get_auth_session(session_token: str) -> dict[str, Any] | None:
    now = _utc_now()

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT user_id, username, avatar_url, expires_at
            FROM auth_sessions
            WHERE session_token = ? AND expires_at > ?
            """,
            (session_token, now),
        ).fetchone()

    if not row:
        return None

    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "avatar_url": row["avatar_url"],
        "expires_at": row["expires_at"],
    }


def delete_auth_session(session_token: str) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM auth_sessions WHERE session_token = ?",
            (session_token,),
        )


initialize_database()
