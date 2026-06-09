from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.config import settings
from src.core.exceptions import (
    DuplicateCreatedEvent,
    TicketNotFound,
    B2BIntegrationError,
)
from src.modules.b2b_events.schemas import IncomingB2BEvent
from src.modules.b2b_events.service import B2BEventService

router = APIRouter()


async def verify_service_key(x_service_key: Optional[str] = Header(None, alias="X-Service-Key")):
    if not x_service_key or x_service_key != settings.B2B_TO_MODERATION_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Invalid service key"
            }
        )


@router.post("/events", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(verify_service_key)])
async def receive_b2b_event(
    event: IncomingB2BEvent,
    db: AsyncSession = Depends(get_db),
):
    try:
        await B2BEventService.process_event(db, event)
        return Response(status_code=status.HTTP_202_ACCEPTED)
    except DuplicateCreatedEvent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_EVENT",
                "message": "A ticket for this product already exists and cannot be created again"
            }
        )
    except TicketNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TICKET_NOT_FOUND",
                "message": "Ticket not found for the specified product"
            }
        )
    except B2BIntegrationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "B2B_INTEGRATION_ERROR",
                "message": str(e)
            }
        )
