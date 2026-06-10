import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.core.security import get_current_user
from src.core.exceptions import (
    ModeratorAlreadyHasActiveTicket,
    TicketNotFound,
    TicketWrongStatus,
    NotAssignedModerator,
    ProductHasNoSKUs,
    B2BIntegrationError,
    BlockingReasonNotFound,
    InvalidFieldReport,
)
from src.modules.tickets.schemas import (
    TicketClaimRequest,
    TicketApproveRequest,
    TicketBlockRequest,
    TicketResponse,
)
from src.modules.tickets.service import TicketService

queue_router = APIRouter()
tickets_router = APIRouter()


@queue_router.post("/claim", response_model=TicketResponse, status_code=status.HTTP_200_OK)
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


@tickets_router.post("/{ticket_id}/approve", response_model=TicketResponse, status_code=status.HTTP_200_OK)
async def approve_moderation_ticket(
    ticket_id: uuid.UUID,
    payload: Optional[TicketApproveRequest] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    moderator_id = uuid.UUID(current_user["sub"])
    comment = payload.comment if payload else None
    try:
        return await TicketService.approve_ticket(db, ticket_id, moderator_id, comment)
    except TicketNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TICKET_NOT_FOUND",
                "message": "Ticket not found"
            }
        )
    except NotAssignedModerator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "NOT_ASSIGNED_MODERATOR",
                "message": "This moderation card is not assigned to you"
            }
        )
    except TicketWrongStatus as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TICKET_WRONG_STATUS",
                "message": e.message
            }
        )
    except ProductHasNoSKUs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRODUCT_HAS_NO_SKUS",
                "message": "Product has no SKUs, cannot approve"
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


@tickets_router.post("/{ticket_id}/block", response_model=TicketResponse, status_code=status.HTTP_200_OK)
async def block_moderation_ticket(
    ticket_id: uuid.UUID,
    payload: TicketBlockRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    moderator_id = uuid.UUID(current_user["sub"])
    try:
        return await TicketService.block_ticket(db, ticket_id, moderator_id, payload)
    except TicketNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TICKET_NOT_FOUND",
                "message": "Ticket not found"
            }
        )
    except NotAssignedModerator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "NOT_ASSIGNED_MODERATOR",
                "message": "This moderation card is not assigned to you"
            }
        )
    except TicketWrongStatus as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TICKET_WRONG_STATUS",
                "message": e.message
            }
        )
    except BlockingReasonNotFound:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "BLOCKING_REASON_NOT_FOUND",
                "message": "Blocking reason not found"
            }
        )
    except InvalidFieldReport as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_FIELD_REPORT",
                "message": e.message
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
