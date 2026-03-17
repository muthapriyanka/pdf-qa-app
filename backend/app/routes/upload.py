# from fastapi import APIRouter, UploadFile, File, HTTPException
# from app.services.pdf_parser import load_pdf_documents
# from app.services.chunker import split_documents
# from app.services.vector_store import create_vector_store
# from app.storage.memory_store import document_store

# router = APIRouter()

# @router.post("/upload")
# async def upload_pdf(file: UploadFile = File(...)):
#     if not file.filename.lower().endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

#     file_bytes = await file.read()
#     if not file_bytes:
#         raise HTTPException(status_code=400, detail="Uploaded file is empty.")

#     try:
#         documents = load_pdf_documents(file_bytes)
#         chunks = split_documents(documents)

#         chunks = [
#             chunk for chunk in chunks
#             if len(chunk.page_content.strip()) > 120
#             and "Download at WoweBook.Com" not in chunk.page_content
#         ]

#         chunks = chunks[:500]

#         vector_store = create_vector_store(chunks)

#         document_store["filename"] = file.filename
#         document_store["vector_store"] = vector_store

#         return {
#             "message": "PDF processed successfully",
#             "filename": file.filename,
#             "total_pages_extracted": len(documents),
#             "total_chunks": len(chunks)
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.pdf_parser import load_pdf_documents
from app.services.chunker import split_documents
from app.services.vector_store import create_vector_store
from app.storage.memory_store import document_store
import uuid

router = APIRouter()

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        documents = load_pdf_documents(file_bytes)
        chunks = split_documents(documents)

        chunks = [
            chunk for chunk in chunks
            if len(chunk.page_content.strip()) > 120
            and "Download at WoweBook.Com" not in chunk.page_content
        ]

        chunks = chunks[:500]

        document_id = str(uuid.uuid4())

        for chunk in chunks:
            chunk.metadata["document_id"] = document_id
            chunk.metadata["filename"] = file.filename

        create_vector_store(chunks)

        document_store["filename"] = file.filename
        document_store["document_id"] = document_id

        return {
            "message": "PDF processed successfully",
            "filename": file.filename,
            "document_id": document_id,
            "total_pages_extracted": len(documents),
            "total_chunks": len(chunks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")