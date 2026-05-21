"""
API RAG. Документы: загрузка PDF → docling → markdown в БД.
Команды для чат-бота: RAG_LIST_DOCUMENTS, RAG_GET_DOCUMENT, RAG_SEARCH.
"""
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document
from app.pdf_service import pdf_to_markdown
from app.schemas import DocumentListItem, DocumentResponse, DocumentSaveBody

router = APIRouter(prefix="/api/v1", tags=["rag"])


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Document)
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc())
    )
    return [DocumentListItem.model_validate(d) for d in r.scalars().all()]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Document).where(Document.id == document_id))
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.get("/documents/search", response_model=list[DocumentListItem])
async def search_documents(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{q.strip()}%"
    r = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.content_md.ilike(pattern),
        )
        .order_by(Document.created_at.desc())
    )
    return [DocumentListItem.model_validate(d) for d in r.scalars().all()]


async def _convert_pdf_to_markdown(file: UploadFile) -> str:
    """Сохраняет PDF во временный файл, конвертирует в markdown, возвращает текст."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename).suffix or ".pdf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir=settings.upload_dir
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
        return pdf_to_markdown(tmp_path)
    except Exception as e:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"PDF conversion failed: {e}")
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@router.post("/documents/preview")
async def preview_document(
    file: UploadFile = File(...),
):
    """Преобразует PDF в markdown и возвращает текст без сохранения в БД."""
    md = await _convert_pdf_to_markdown(file)
    suggested_name = (Path(file.filename or "document").stem or "document").strip()[:512]
    return {"markdown": md, "suggested_name": suggested_name}


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    name: str = Query(..., min_length=1, max_length=512),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    md = await _convert_pdf_to_markdown(file)
    doc = Document(
        tenant_id=tenant_id,
        name=name.strip(),
        content_md=md,
        source_file_name=file.filename,
    )
    db.add(doc)
    await db.flush()
    return DocumentResponse.model_validate(doc)


@router.post("/documents/save", response_model=DocumentResponse, status_code=201)
async def save_document_from_markdown(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    body: DocumentSaveBody = ...,
    db: AsyncSession = Depends(get_db),
):
    """Сохраняет документ в БД из уже преобразованного markdown (после предпросмотра)."""
    doc = Document(
        tenant_id=tenant_id,
        name=body.name.strip(),
        content_md=body.content_md,
        source_file_name=body.source_file_name.strip() if body.source_file_name else None,
    )
    db.add(doc)
    await db.flush()
    return DocumentResponse.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Document).where(Document.id == document_id))
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.flush()
