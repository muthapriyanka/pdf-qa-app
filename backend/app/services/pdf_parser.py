import os
import tempfile
from langchain_community.document_loaders import PyPDFLoader


def load_pdf_documents(file_bytes: bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
        temp_file.write(file_bytes)
        temp_path = temp_file.name

    try:
        loader = PyPDFLoader(temp_path)
        documents = loader.load()
        return documents
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)



