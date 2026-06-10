import uuid
from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class TicketClaimRequest(BaseModel):
    queue_priority: Optional[int] = Field(default=None, ge=1, le=4)
    category_ids: Optional[List[uuid.UUID]] = Field(default=None)


class TicketApproveRequest(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=2000)


class FieldReportInput(BaseModel):
    field_path: str = Field(..., max_length=256)
    message: str = Field(..., max_length=1000)
    severity: Literal["INFO", "WARNING", "ERROR"] = "ERROR"


class TicketBlockRequest(BaseModel):
    blocking_reason_ids: List[uuid.UUID] = Field(..., min_length=1)
    comment: Optional[str] = Field(default=None, max_length=2000)
    field_reports: List[FieldReportInput] = Field(default_factory=list)


class TicketResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    seller_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    kind: str
    status: str
    queue_priority: int
    assigned_moderator_id: Optional[uuid.UUID] = None
    claimed_at: Optional[datetime] = None
    claim_expires_at: Optional[datetime] = None
    decision_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

