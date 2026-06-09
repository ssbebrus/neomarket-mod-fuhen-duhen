import uuid
import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.exceptions import (
    DuplicateCreatedEvent,
    TicketNotFound,
    B2BIntegrationError,
)
from src.modules.tickets.models import Ticket
from src.modules.b2b_events.models import EventIdempotencyKey
from src.modules.b2b_events.schemas import IncomingB2BEvent


class B2BEventService:
    @staticmethod
    async def process_event(db: AsyncSession, event: IncomingB2BEvent) -> None:
        # 1. Проверяем идемпотентность
        stmt = select(EventIdempotencyKey).where(EventIdempotencyKey.key == event.idempotency_key)
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return

        # 2. Обработка события в зависимости от event_type
        if event.event_type == "PRODUCT_CREATED":
            # Ищем существующий тикет
            stmt = select(Ticket).options(selectinload(Ticket.blocking_reasons)).where(Ticket.product_id == event.payload.product_id)
            result = await db.execute(stmt)
            ticket = result.scalar_one_or_none()

            if ticket is not None:
                if ticket.status == "HARD_BLOCKED":
                    # Игнорируем
                    pass
                else:
                    raise DuplicateCreatedEvent()
            else:
                # Получаем снапшот товара из B2B
                product_data = await B2BEventService._fetch_product_from_b2b(event.payload.product_id)

                # Создаем новый тикет
                new_ticket = Ticket(
                    product_id=event.payload.product_id,
                    seller_id=event.payload.seller_id,
                    category_id=event.payload.category_id,
                    kind="CREATE",
                    status="PENDING",
                    queue_priority=event.payload.queue_priority,
                    json_before=None,
                    json_after=product_data,
                )
                db.add(new_ticket)

        elif event.event_type == "PRODUCT_EDITED":
            # Ищем существующий тикет
            stmt = select(Ticket).options(selectinload(Ticket.blocking_reasons)).where(Ticket.product_id == event.payload.product_id)
            result = await db.execute(stmt)
            ticket = result.scalar_one_or_none()

            if ticket is None:
                raise TicketNotFound()

            if ticket.status == "HARD_BLOCKED":
                # Игнорируем
                pass
            else:
                old_status = ticket.status

                # Получаем снапшот товара из B2B
                product_data = await B2BEventService._fetch_product_from_b2b(event.payload.product_id)

                # Вычисляем новый приоритет
                new_priority = ticket.queue_priority
                if old_status == "BLOCKED":
                    new_priority = 2
                elif old_status in ("APPROVED", "MODERATED"):
                    active_stock = sum(
                        sku.get("active_quantity", 0)
                        for sku in product_data.get("skus", [])
                    )
                    if active_stock > 0:
                        new_priority = 3
                    else:
                        new_priority = 4

                # Сбрасываем и обновляем тикет
                ticket.status = "PENDING"
                ticket.assigned_moderator_id = None
                ticket.claimed_at = None
                ticket.claim_expires_at = None
                ticket.decision_at = None
                ticket.decision_comment = None
                ticket.json_before = ticket.json_after
                ticket.json_after = product_data
                ticket.queue_priority = new_priority
                ticket.blocking_reasons = []

        elif event.event_type == "PRODUCT_DELETED":
            # Ищем существующий тикет
            stmt = select(Ticket).options(selectinload(Ticket.blocking_reasons)).where(Ticket.product_id == event.payload.product_id)
            result = await db.execute(stmt)
            ticket = result.scalar_one_or_none()

            if ticket is not None:
                await db.delete(ticket)

        # 3. Сохраняем ключ идемпотентности
        idempotency = EventIdempotencyKey(key=event.idempotency_key)
        db.add(idempotency)
        await db.commit()

    @staticmethod
    async def _fetch_product_from_b2b(product_id: uuid.UUID) -> dict:
        url = f"{settings.B2B_URL}/api/v1/products/{product_id}"
        headers = {"X-Service-Key": settings.B2B_TO_MODERATION_KEY}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=5.0)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                raise B2BIntegrationError(f"Failed to fetch product from B2B: {str(e)}")
