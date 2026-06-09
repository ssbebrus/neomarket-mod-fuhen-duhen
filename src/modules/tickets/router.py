import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.core.security import get_current_user
from src.core.exceptions import ModeratorAlreadyHasActiveTicket
from src.modules.tickets.schemas import TicketClaimRequest, TicketResponse
from src.modules.tickets.service import TicketService

router = APIRouter()


@router.post("/claim", response_model=TicketResponse, status_code=status.HTTP_200_OK)
async def claim_next_ticket(
    payload: Optional[TicketClaimRequest] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    moderator_id = uuid.UUID(current_user["sub"])
    try:
        ticket = await TicketService.claim_ticket(db, moderator_id, payload)
        if ticket is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return ticket
    except ModeratorAlreadyHasActiveTicket:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MODERATOR_ALREADY_HAS_ACTIVE_TICKET",
                "message": "Moderator already has an active ticket in review"
            }
        )
