import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, Table, Column, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin

ticket_blocking_reasons = Table(
    "ticket_blocking_reasons",
    Base.metadata,
    Column("ticket_id", ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("reason_id", ForeignKey("blocking_reasons.id", ondelete="RESTRICT"), primary_key=True),
)

class BlockingReason(Base, TimestampMixin):
    __tablename__ = "blocking_reasons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    hard_block: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tickets: Mapped[List["Ticket"]] = relationship(
        secondary=ticket_blocking_reasons,
        back_populates="blocking_reasons"
    )

class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    queue_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    assigned_moderator_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    claim_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    json_before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    json_after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    blocking_reasons: Mapped[List[BlockingReason]] = relationship(
        secondary=ticket_blocking_reasons,
        back_populates="tickets"
    )

SEED_REASONS = [
    {
        "id": "a7b8c9d0-1234-5678-ef01-890123456789",
        "code": "WRONG_DESCRIPTION",
        "title": "Описание не соответствует товару",
        "hard_block": False,
    },
    {
        "id": "b8c9d0e1-2345-6789-f012-901234567890",
        "code": "WRONG_IMAGE",
        "title": "Изображение не соответствует товару",
        "hard_block": False,
    },
    {
        "id": "c9d0e1f2-3456-7890-0123-012345678901",
        "code": "WRONG_CATEGORY",
        "title": "Некорректная категория товара",
        "hard_block": False,
    },
    {
        "id": "d0e1f2a3-4567-8901-1234-123456789012",
        "code": "INSUFFICIENT_INFO",
        "title": "Недостаточно информации о товаре",
        "hard_block": False,
    },
    {
        "id": "e1f2a3b4-5678-9012-2345-234567890123",
        "code": "OFFENSIVE_CONTENT",
        "title": "Нецензурные или оскорбительные материалы",
        "hard_block": False,
    },
    {
        "id": "f2a3b4c5-6789-0123-3456-345678901234",
        "code": "DUPLICATE_PRODUCT",
        "title": "Дублирование существующего товара",
        "hard_block": False,
    },
    {
        "id": "a3b4c5d6-7890-1234-4567-456789012345",
        "code": "INCORRECT_PRICE",
        "title": "Некорректная цена",
        "hard_block": False,
    },
    {
        "id": "b4c5d6e7-8901-2345-5678-567890123456",
        "code": "COUNTERFEIT",
        "title": "Контрафактный товар",
        "hard_block": True,
    },
    {
        "id": "c5d6e7f8-9012-3456-6789-678901234567",
        "code": "PROHIBITED_GOODS",
        "title": "Товар запрещён к продаже на территории РФ",
        "hard_block": True,
    },
    {
        "id": "d6e7f8a9-0123-4567-7890-789012345678",
        "code": "COPYRIGHT_VIOLATION",
        "title": "Товар нарушает авторские права",
        "hard_block": True,
    },
]
