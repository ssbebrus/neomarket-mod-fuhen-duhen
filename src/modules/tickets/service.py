import uuid
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.exceptions import (
    ModeratorAlreadyHasActiveTicket,
    TicketWrongStatus,
    NotAssignedModerator,
    ProductHasNoSKUs,
    TicketNotFound,
    B2BIntegrationError,
    BlockingReasonNotFound,
    HardBlockReasonNotAllowed,
)
from src.modules.blocking_reasons.models import BlockingReason
from src.modules.tickets.field_path import validate_field_reports
from src.modules.tickets.field_report_models import TicketFieldReport
from src.modules.tickets.models import Ticket
from src.modules.tickets.schemas import TicketBlockRequest, TicketClaimRequest


class TicketService:
    @staticmethod
    async def claim_ticket(
        db: AsyncSession,
        moderator_id: uuid.UUID,
        payload: Optional[TicketClaimRequest] = None
    ) -> Optional[Ticket]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

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

    @staticmethod
    async def approve_ticket(
        db: AsyncSession,
        ticket_id: uuid.UUID,
        moderator_id: uuid.UUID,
        comment: Optional[str] = None
    ) -> Ticket:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Находим тикет по ticket_id с блокировкой строки
        stmt = select(Ticket).options(selectinload(Ticket.blocking_reasons)).where(Ticket.id == ticket_id).with_for_update()
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()

        if ticket is None:
            raise TicketNotFound()

        # 2. Проверяем предусловия
        if ticket.status == "HARD_BLOCKED":
            raise TicketWrongStatus("Product is permanently blocked")
        if ticket.status != "IN_REVIEW":
            raise TicketWrongStatus("Product is not in review")
        if ticket.assigned_moderator_id != moderator_id:
            raise NotAssignedModerator()
        if ticket.claim_expires_at is not None and ticket.claim_expires_at < now:
            raise TicketWrongStatus("Claim has expired")

        # 3. Проверяем товар в B2B (GET /api/v1/products/{product_id})
        url_get = f"{settings.B2B_URL}/api/v1/products/{ticket.product_id}"
        headers = {"X-Service-Key": settings.B2B_TO_MODERATION_KEY}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url_get, headers=headers, timeout=5.0)
                response.raise_for_status()
                product_data = response.json()
            except Exception as e:
                raise B2BIntegrationError(f"Failed to fetch product from B2B for validation: {str(e)}")

        skus = product_data.get("skus", [])
        if not skus:
            raise ProductHasNoSKUs()

        # 4. Отправляем событие MODERATED в B2B (POST /api/v1/moderation/events)
        url_post = f"{settings.B2B_URL}/api/v1/moderation/events"
        event_body = {
            "idempotency_key": str(uuid.uuid4()),
            "product_id": str(ticket.product_id),
            "event_type": "MODERATED",
            "moderator_id": str(moderator_id),
            "moderator_comment": comment,
            "occurred_at": now.isoformat() + "Z"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url_post, headers=headers, json=event_body, timeout=5.0)
                response.raise_for_status()
            except Exception as e:
                raise B2BIntegrationError(f"Failed to notify B2B of product moderation status: {str(e)}")

        # 5. Обновляем статус в БД и сохраняем решение
        ticket.status = "APPROVED"
        ticket.decision_at = now
        ticket.decision_comment = comment
        ticket.blocking_reasons = []

        await db.commit()
        await db.refresh(ticket)
        return ticket

    @staticmethod
    async def block_ticket(
        db: AsyncSession,
        ticket_id: uuid.UUID,
        moderator_id: uuid.UUID,
        payload: TicketBlockRequest,
    ) -> Ticket:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        stmt = (
            select(Ticket)
            .options(
                selectinload(Ticket.blocking_reasons),
                selectinload(Ticket.field_reports),
            )
            .where(Ticket.id == ticket_id)
            .with_for_update()
        )
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()

        if ticket is None:
            raise TicketNotFound()

        if ticket.status == "HARD_BLOCKED":
            raise TicketWrongStatus("Product is permanently blocked")
        if ticket.status != "IN_REVIEW":
            raise TicketWrongStatus("Product is not in review")
        if ticket.assigned_moderator_id != moderator_id:
            raise NotAssignedModerator()
        if ticket.claim_expires_at is not None and ticket.claim_expires_at < now:
            raise TicketWrongStatus("Claim has expired")

        reasons_stmt = select(BlockingReason).where(
            BlockingReason.id.in_(payload.blocking_reason_ids),
            BlockingReason.is_active.is_(True),
        )
        reasons_result = await db.execute(reasons_stmt)
        reasons = list(reasons_result.scalars().all())

        if len(reasons) != len(payload.blocking_reason_ids):
            raise BlockingReasonNotFound()

        for reason in reasons:
            if reason.hard_block:
                raise HardBlockReasonNotAllowed()

        parsed_reports = validate_field_reports(payload.field_reports)

        primary_reason = reasons[0]
        b2b_field_reports = [
            {
                "field_name": report.field_name,
                "sku_id": str(report.sku_id) if report.sku_id else None,
                "comment": report.message,
            }
            for report in parsed_reports
        ]

        url_post = f"{settings.B2B_URL}/api/v1/moderation/events"
        headers = {"X-Service-Key": settings.B2B_TO_MODERATION_KEY}
        event_body = {
            "idempotency_key": str(uuid.uuid4()),
            "product_id": str(ticket.product_id),
            "event_type": "BLOCKED",
            "moderator_id": str(moderator_id),
            "hard_block": False,
            "blocking_reason_id": str(primary_reason.id),
            "moderator_comment": payload.comment,
            "field_reports": b2b_field_reports,
            "occurred_at": now.isoformat() + "Z",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url_post, headers=headers, json=event_body, timeout=5.0
                )
                response.raise_for_status()
            except Exception as e:
                raise B2BIntegrationError(
                    f"Failed to notify B2B of product block status: {str(e)}"
                )

        ticket.status = "BLOCKED"
        ticket.decision_at = now
        ticket.decision_comment = payload.comment
        ticket.blocking_reasons = reasons

        ticket.field_reports.clear()
        for report in parsed_reports:
            ticket.field_reports.append(
                TicketFieldReport(
                    field_path=report.field_path,
                    message=report.message,
                    severity=report.severity,
                    sku_id=report.sku_id,
                )
            )

        await db.commit()
        await db.refresh(ticket)
        return ticket
