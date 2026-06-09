import uuid
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class BlockingReasonCreateRequest(BaseModel):
    code: str = Field(..., max_length=64, pattern=r"^[A-Z_]+$", examples=["FORBIDDEN_GOODS"])
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    hard_block: bool

class BlockingReasonUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    is_active: Optional[bool] = None

class BlockingReasonResponse(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    description: Optional[str] = None
    hard_block: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
