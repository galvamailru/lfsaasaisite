"""Загрузка файлов в MinIO для галереи и прочих нужд кабинета."""
import io
from uuid import uuid4

from minio import Minio

from app.config import settings


def get_minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    client = get_minio_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


# Допустимые MIME для изображений галереи
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def upload_gallery_image(tenant_id: str, file_data: bytes, content_type: str, original_filename: str) -> str:
    """Загружает изображение в MinIO, ключ: gallery/{tenant_id}/{uuid}.ext. Возвращает object_key."""
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValueError(f"Недопустимый тип изображения: {content_type}")
    ext = ".jpg"
    for e in ALLOWED_IMAGE_EXTENSIONS:
        if original_filename.lower().endswith(e):
            ext = e
            break
    object_name = f"gallery/{tenant_id}/{uuid4()}{ext}"
    ensure_bucket()
    client = get_minio_client()
    client.put_object(
        settings.minio_bucket,
        object_name,
        io.BytesIO(file_data),
        length=len(file_data),
        content_type=content_type,
    )
    return object_name


def get_object(bucket: str, object_name: str) -> tuple[bytes, str]:
    """Читает объект из MinIO. Возвращает (data, content_type)."""
    client = get_minio_client()
    resp = client.get_object(bucket, object_name)
    try:
        data = resp.read()
        content_type = getattr(resp, "headers", {}).get("Content-Type") or "application/octet-stream"
        return data, content_type
    finally:
        resp.close()
