from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class TemplateItem(Base):
    __tablename__ = 'template_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    au_creation_timestamp: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    au_last_update_timestamp: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    au_created_by_user: Mapped[str | None] = mapped_column(String(100), nullable=True)
    au_last_updated_by_user: Mapped[str | None] = mapped_column(String(100), nullable=True)
