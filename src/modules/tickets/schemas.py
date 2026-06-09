import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class TicketClaimRequest(BaseModel):
    queue_priority: Optional[int] = Field(default=None, ge=1, le=4)
    category_ids: Optional[List[uuid.UUID]] = Field(default=None)


class TicketApproveRequest(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=2000)



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

