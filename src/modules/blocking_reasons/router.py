import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Response, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.core.exceptions import BlockingReasonAlreadyExists, BlockingReasonNotFound
from src.modules.blocking_reasons.service import BlockingReasonService
from src.modules.blocking_reasons.schemas import (
    BlockingReasonCreateRequest,
    BlockingReasonUpdateRequest,
    BlockingReasonResponse,
)

router = APIRouter()

@router.get("", response_model=List[BlockingReasonResponse])
async def list_blocking_reasons(
    hard_block: Optional[bool] = None,
    is_active: bool = True,
    db: AsyncSession = Depends(get_db),
):
    return await BlockingReasonService.list_reasons(db, hard_block=hard_block, is_active=is_active)

@router.post("", response_model=BlockingReasonResponse, status_code=status.HTTP_201_CREATED)
async def create_blocking_reason(
    payload: BlockingReasonCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await BlockingReasonService.create_reason(db, payload)
    except BlockingReasonAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BLOCKING_REASON_ALREADY_EXISTS",
                "message": f"Blocking reason with code '{payload.code}' already exists",
            },
        )

@router.patch("/{reason_id}", response_model=BlockingReasonResponse)
async def update_blocking_reason(
    reason_id: uuid.UUID,
    payload: BlockingReasonUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await BlockingReasonService.update_reason(db, reason_id, payload)
    except BlockingReasonNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "BLOCKING_REASON_NOT_FOUND",
                "message": f"Blocking reason with ID '{reason_id}' not found",
            },
        )

@router.delete("/{reason_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocking_reason(
    reason_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        await BlockingReasonService.delete_reason(db, reason_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except BlockingReasonNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "BLOCKING_REASON_NOT_FOUND",
                "message": f"Blocking reason with ID '{reason_id}' not found",
            },
        )

