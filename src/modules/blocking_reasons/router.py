import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
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
    return await BlockingReasonService.create_reason(db, payload)

@router.patch("/{reason_id}", response_model=BlockingReasonResponse)
async def update_blocking_reason(
    reason_id: uuid.UUID,
    payload: BlockingReasonUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await BlockingReasonService.update_reason(db, reason_id, payload)

@router.delete("/{reason_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocking_reason(
    reason_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    await BlockingReasonService.delete_reason(db, reason_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
