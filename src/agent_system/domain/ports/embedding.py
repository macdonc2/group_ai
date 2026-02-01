"""Embedding port interface for vector embeddings."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""
    
    text: str
    embedding: list[float]
    model: str
    dimensions: int
    tokens_used: int


class EmbeddingPort(ABC):
    """Abstract interface for embedding generation."""

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
        """Generate an embedding for a single text.
        
        Args:
            text: The text to embed
            
        Returns:
            EmbeddingResult with the embedding vector
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of EmbeddingResults
        """
        ...

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the dimensionality of embeddings from this provider."""
        ...
