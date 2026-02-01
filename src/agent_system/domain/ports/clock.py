"""Clock port interface for time operations."""

from abc import ABC, abstractmethod
from datetime import datetime


class ClockPort(ABC):
    """Port interface for time operations.
    
    This abstraction allows for deterministic testing
    by injecting a fake clock implementation.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Get the current UTC datetime."""
        ...

    @abstractmethod
    def now_timestamp(self) -> float:
        """Get the current UTC timestamp as float."""
        ...


class SystemClock(ClockPort):
    """Real system clock implementation."""

    def now(self) -> datetime:
        """Get the current UTC datetime."""
        return datetime.utcnow()

    def now_timestamp(self) -> float:
        """Get the current UTC timestamp as float."""
        return datetime.utcnow().timestamp()
