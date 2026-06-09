import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, model_validator

class EventProductCreatedPayload(BaseModel):
    product_id: uuid.UUID
    seller_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    queue_priority: int = Field(default=3, ge=1, le=4)
    json_after: Dict[str, Any]

class EventProductEditedPayload(BaseModel):
    product_id: uuid.UUID
    seller_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    queue_priority: int = Field(default=3, ge=1, le=4)
    json_before: Dict[str, Any]
    json_after: Dict[str, Any]

class EventProductDeletedPayload(BaseModel):
    product_id: uuid.UUID

class IncomingB2BEvent(BaseModel):
    event_type: str
    idempotency_key: uuid.UUID
    occurred_at: datetime
    payload: Union[EventProductCreatedPayload, EventProductEditedPayload, EventProductDeletedPayload, Dict[str, Any]]

    @model_validator(mode="after")
    def validate_payload(self) -> "IncomingB2BEvent":
        payload_data = self.payload
        if isinstance(payload_data, dict):
            if self.event_type == "PRODUCT_CREATED":
                self.payload = EventProductCreatedPayload(**payload_data)
            elif self.event_type == "PRODUCT_EDITED":
                self.payload = EventProductEditedPayload(**payload_data)
            elif self.event_type == "PRODUCT_DELETED":
                self.payload = EventProductDeletedPayload(**payload_data)
            else:
                raise ValueError(f"Unknown event_type: {self.event_type}")
        return self
