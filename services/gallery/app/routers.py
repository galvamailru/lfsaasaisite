"""
API галереи. Изображения хранятся в БД в бинарном виде.
Команды для чат-бота: LIST_GALLERIES, SHOW_GALLERY, CREATE_GALLERY_GROUP,
ADD_IMAGE_TO_GALLERY, REMOVE_IMAGE_FROM_GALLERY, DELETE_GALLERY_GROUP.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import GalleryGroup, GalleryImage
from app.schemas import (
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    GroupWithImagesResponse,
    ImageResponse,
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

router = APIRouter(prefix="/api/v1", tags=["gallery"])


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(GalleryGroup)
        .where(GalleryGroup.tenant_id == tenant_id)
        .order_by(GalleryGroup.created_at.desc())
    )
    groups = list(r.scalars().all())
    out = []
    for g in groups:
        cnt = await db.execute(select(GalleryImage).where(GalleryImage.group_id == g.id))
        out.append(
            GroupResponse(
                id=g.id,
                tenant_id=g.tenant_id,
                name=g.name,
                description=g.description,
                created_at=g.created_at,
                image_count=len(cnt.scalars().all()),
            )
        )
    return out


@router.get("/groups/{group_id}", response_model=GroupWithImagesResponse)
async def get_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(GalleryGroup).where(GalleryGroup.id == group_id))
    group = r.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    r2 = await db.execute(
        select(GalleryImage)
        .where(GalleryImage.group_id == group_id)
        .order_by(GalleryImage.created_at)
    )
    images = list(r2.scalars().all())
    # url — путь для получения файла (основное приложение подставит свой base)
    image_responses = [
        ImageResponse(
            id=img.id,
            group_id=img.group_id,
            url=f"/api/v1/groups/{group_id}/images/{img.id}/file",
            created_at=img.created_at,
        )
        for img in images
    ]
    return GroupWithImagesResponse(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        image_count=len(images),
        images=image_responses,
    )


@router.post("/groups", response_model=GroupResponse, status_code=201)
async def create_group(body: GroupCreate, db: AsyncSession = Depends(get_db)):
    group = GalleryGroup(
        tenant_id=body.tenant_id,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
    )
    db.add(group)
    await db.flush()
    return GroupResponse(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        image_count=0,
    )


@router.patch("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID, body: GroupUpdate, db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(GalleryGroup).where(GalleryGroup.id == group_id))
    group = r.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if body.name is not None:
        group.name = body.name.strip()
    if body.description is not None:
        group.description = body.description.strip() or None
    await db.flush()
    cnt = await db.execute(select(GalleryImage).where(GalleryImage.group_id == group.id))
    return GroupResponse(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        image_count=len(cnt.scalars().all()),
    )


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(GalleryGroup).where(GalleryGroup.id == group_id))
    group = r.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    await db.delete(group)
    await db.flush()


@router.post("/groups/{group_id}/images", response_model=ImageResponse, status_code=201)
async def add_image(
    group_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(GalleryGroup).where(GalleryGroup.id == group_id))
    if r.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Group not found")
    ct = (file.content_type or "").strip().lower()
    if ct not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Допустимы только изображения: JPEG, PNG, GIF, WebP",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    image = GalleryImage(group_id=group_id, data=data, content_type=ct)
    db.add(image)
    await db.flush()
    return ImageResponse(
        id=image.id,
        group_id=image.group_id,
        url=f"/api/v1/groups/{group_id}/images/{image.id}/file",
        created_at=image.created_at,
    )


@router.get("/groups/{group_id}/images/{image_id}/file")
async def get_image_file(
    group_id: UUID,
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(GalleryImage).where(
            GalleryImage.id == image_id,
            GalleryImage.group_id == group_id,
        )
    )
    image = r.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(content=image.data, media_type=image.content_type)


@router.delete("/groups/{group_id}/images/{image_id}", status_code=204)
async def delete_image(
    group_id: UUID, image_id: UUID, db: AsyncSession = Depends(get_db)
):
    r = await db.execute(
        select(GalleryImage).where(
            GalleryImage.id == image_id, GalleryImage.group_id == group_id
        )
    )
    image = r.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    await db.delete(image)
    await db.flush()
