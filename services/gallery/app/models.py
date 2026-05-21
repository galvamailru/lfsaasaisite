"""Models in schema gallery. Groups and images."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class GalleryGroup(Base):
    """Группа галереи: название и описание. tenant_id для мультитенантности."""
    __tablename__ = "group"
    __table_args__ = {"schema": "gallery"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    images: Mapped[list["GalleryImage"]] = relationship(
        "GalleryImage", back_populates="group", cascade="all, delete-orphan"
    )


class GalleryImage(Base):
    """Изображение в группе. Хранится в БД: data (бинарные данные) и content_type."""
    __tablename__ = "image"
    __table_args__ = {"schema": "gallery"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gallery.group.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["GalleryGroup"] = relationship("GalleryGroup", back_populates="images")
