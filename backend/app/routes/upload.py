import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.chunker import split_documents
from app.services.pdf_parser import load_pdf_documents
from app.services.vector_store import create_vector_store
from app.storage.memory_store import save_collection_metadata


router = APIRouter()

MAX_CHUNKS_PER_DOCUMENT = 500
MIN_CHUNK_CHARACTERS = 120


def _page_number_from_metadata(metadata: dict) -> int | str:
    page = metadata.get("page")

    if isinstance(page, int):
        return page + 1

    if isinstance(page, str) and page.isdigit():
        return int(page) + 1

    return page or "unknown"


def _validate_pdf(file: UploadFile) -> None:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one PDF.")

    for file in files:
        _validate_pdf(file)

    collection_id = str(uuid.uuid4())
    all_chunks = []
    all_chunk_ids = []
    document_metadata = []

    try:
        for file in files:
            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename} is empty.",
                )

            documents = load_pdf_documents(file_bytes)
            chunks = split_documents(documents)
            chunks = [
                chunk
                for chunk in chunks
                if len(chunk.page_content.strip()) > MIN_CHUNK_CHARACTERS
                and "Download at WoweBook.Com" not in chunk.page_content
            ][:MAX_CHUNKS_PER_DOCUMENT]

            if not chunks:
                raise HTTPException(
                    status_code=400,
                    detail=f"No readable text was found in {file.filename}.",
                )

            document_id = str(uuid.uuid4())

            for index, chunk in enumerate(chunks):
                chunk_id = f"{collection_id}:{document_id}:{index}"
                chunk.metadata.update(
                    {
                        "collection_id": collection_id,
                        "document_id": document_id,
                        "filename": file.filename,
                        "page": _page_number_from_metadata(chunk.metadata),
                        "chunk_id": chunk_id,
                    }
                )
                all_chunks.append(chunk)
                all_chunk_ids.append(chunk_id)

            document_metadata.append(
                {
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "filename": file.filename,
                    "total_pages_extracted": len(documents),
                    "total_chunks": len(chunks),
                }
            )

        create_vector_store(all_chunks, ids=all_chunk_ids)
        metadata = save_collection_metadata(collection_id, document_metadata)

        return {
            "message": "PDF collection processed successfully",
            **metadata,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDFs: {str(e)}",
        )
