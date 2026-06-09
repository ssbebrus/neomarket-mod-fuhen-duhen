import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ModeratorAlreadyHasActiveTicket
from src.modules.tickets.models import Ticket
from src.modules.tickets.schemas import TicketClaimRequest


class TicketService:
    @staticmethod
    async def claim_ticket(
        db: AsyncSession,
        moderator_id: uuid.UUID,
        payload: Optional[TicketClaimRequest] = None
    ) -> Optional[Ticket]:
        now = datetime.utcnow()

        # 1. Проверяем, нет ли у модератора уже взятого активного тикета
        active_stmt = select(Ticket).where(
            Ticket.assigned_moderator_id == moderator_id,
            Ticket.status == "IN_REVIEW",
            Ticket.claim_expires_at > now
        )
        active_result = await db.execute(active_stmt)
        if active_result.scalar_one_or_none() is not None:
            raise ModeratorAlreadyHasActiveTicket()

        # 2. Поиск следующего тикета в очереди
        cond = or_(
            Ticket.status == "PENDING",
            and_(
                Ticket.status == "IN_REVIEW",
                Ticket.claim_expires_at < now
            )
        )

        stmt = select(Ticket).where(cond)

        if payload:
            if payload.queue_priority is not None:
                stmt = stmt.where(Ticket.queue_priority == payload.queue_priority)
            if payload.category_ids:
                stmt = stmt.where(Ticket.category_id.in_(payload.category_ids))

        # Приоритет и FIFO, берем первую подходящую строку и блокируем её
        stmt = stmt.order_by(
            Ticket.queue_priority.asc(),
            Ticket.created_at.asc()
        ).limit(1).with_for_update(skip_locked=True)

        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()

        if ticket is None:
            return None

        # 3. Обновляем тикет
        ticket.status = "IN_REVIEW"
        ticket.assigned_moderator_id = moderator_id
        ticket.claimed_at = now
        ticket.claim_expires_at = now + timedelta(minutes=30)

        await db.commit()
        await db.refresh(ticket)
        return ticket
