from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    tenant_id: UUID
    name: str = Field(..., max_length=256)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(None, max_length=256)
    description: str | None = None


class GroupResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    created_at: datetime
    image_count: int = 0

    class Config:
        from_attributes = True


class ImageResponse(BaseModel):
    id: UUID
    group_id: UUID
    url: str
    created_at: datetime

    class Config:
        from_attributes = True


class GroupWithImagesResponse(GroupResponse):
    images: list[ImageResponse] = []
