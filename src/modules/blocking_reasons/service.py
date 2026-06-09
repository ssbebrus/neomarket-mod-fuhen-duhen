import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from src.modules.blocking_reasons.models import BlockingReason
from src.modules.blocking_reasons.schemas import (
    BlockingReasonCreateRequest,
    BlockingReasonUpdateRequest,
)

class BlockingReasonService:
    @staticmethod
    async def list_reasons(
        db: AsyncSession,
        hard_block: Optional[bool] = None,
        is_active: bool = True,
    ) -> List[BlockingReason]:
        query = select(BlockingReason)
        if hard_block is not None:
            query = query.where(BlockingReason.hard_block == hard_block)
        query = query.where(BlockingReason.is_active == is_active)

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_reason(
        db: AsyncSession,
        payload: BlockingReasonCreateRequest,
    ) -> BlockingReason:
        # Проверяем уникальность кода причины
        existing = await db.execute(
            select(BlockingReason).where(BlockingReason.code == payload.code)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BLOCKING_REASON_ALREADY_EXISTS",
                    "message": f"Blocking reason with code '{payload.code}' already exists",
                },
            )

        reason = BlockingReason(
            code=payload.code,
            title=payload.title,
            description=payload.description,
            hard_block=payload.hard_block,
            is_active=True,
        )
        db.add(reason)
        await db.commit()
        await db.refresh(reason)
        return reason

    @staticmethod
    async def update_reason(
        db: AsyncSession,
        reason_id: uuid.UUID,
        payload: BlockingReasonUpdateRequest,
    ) -> BlockingReason:
        reason = await db.get(BlockingReason, reason_id)
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "BLOCKING_REASON_NOT_FOUND",
                    "message": f"Blocking reason with ID '{reason_id}' not found",
                },
            )

        if payload.title is not None:
            reason.title = payload.title
        if payload.description is not None:
            reason.description = payload.description
        if payload.is_active is not None:
            reason.is_active = payload.is_active

        await db.commit()
        await db.refresh(reason)
        return reason

    @staticmethod
    async def delete_reason(
        db: AsyncSession,
        reason_id: uuid.UUID,
    ) -> None:
        reason = await db.get(BlockingReason, reason_id)
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "BLOCKING_REASON_NOT_FOUND",
                    "message": f"Blocking reason with ID '{reason_id}' not found",
                },
            )

        # Мягкое удаление (деактивация)
        reason.is_active = False
        await db.commit()
