"""Base domain event classes."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Base class for all domain events."""

    event_id: Annotated[UUID, Field(default_factory=uuid4)]
    event_type: str
    occurred_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    def __init__(self, **data: Any) -> None:
        if "event_type" not in data:
            data["event_type"] = self.__class__.__name__
        super().__init__(**data)
