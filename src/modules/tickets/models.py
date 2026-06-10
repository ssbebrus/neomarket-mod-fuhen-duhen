import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, Table, Column, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.modules.blocking_reasons.models import BlockingReason
    from src.modules.tickets.field_report_models import TicketFieldReport

ticket_blocking_reasons = Table(
    "ticket_blocking_reasons",
    Base.metadata,
    Column("ticket_id", ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("reason_id", ForeignKey("blocking_reasons.id", ondelete="RESTRICT"), primary_key=True),
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

    blocking_reasons: Mapped[List["BlockingReason"]] = relationship(
        secondary=ticket_blocking_reasons,
        back_populates="tickets"
    )
    field_reports: Mapped[List["TicketFieldReport"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )
