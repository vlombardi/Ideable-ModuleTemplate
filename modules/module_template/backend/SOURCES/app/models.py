from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class TemplateItem(Base):
    __versioned__ = {}

    __tablename__ = 'template_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
