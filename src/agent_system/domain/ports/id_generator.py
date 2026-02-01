"""ID generator port interface."""

from abc import ABC, abstractmethod
from uuid import UUID, uuid4


class IdGeneratorPort(ABC):
    """Port interface for ID generation.
    
    This abstraction allows for deterministic testing
    by injecting a fake ID generator.
    """

    @abstractmethod
    def generate(self) -> UUID:
        """Generate a new unique identifier."""
        ...


class UUIDGenerator(IdGeneratorPort):
    """UUID-based ID generator implementation."""

    def generate(self) -> UUID:
        """Generate a new UUID."""
        return uuid4()


class DeterministicIdGenerator(IdGeneratorPort):
    """Deterministic ID generator for testing.
    
    Generates predictable IDs based on a counter.
    """

    def __init__(self, start: int = 0) -> None:
        """Initialize with a starting counter value."""
        self._counter = start

    def generate(self) -> UUID:
        """Generate a deterministic UUID based on counter."""
        self._counter += 1
        # Create a deterministic UUID from the counter
        hex_str = f"{self._counter:032x}"
        return UUID(hex_str)

    def reset(self, start: int = 0) -> None:
        """Reset the counter."""
        self._counter = start
