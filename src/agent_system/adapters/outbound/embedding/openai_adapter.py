"""OpenAI embedding adapter implementing the EmbeddingPort."""

import time

from openai import AsyncOpenAI

from agent_system.adapters.outbound.telemetry import current_trace
from agent_system.domain.ports.embedding import EmbeddingPort, EmbeddingResult


def _record(model: str, tokens: int, t0: float) -> None:
    trace = current_trace()
    if trace is not None:
        trace.add_embedding_call(model, tokens, (time.perf_counter() - t0) * 1000)


class OpenAIEmbeddingAdapter(EmbeddingPort):
    """OpenAI implementation of the EmbeddingPort using text-embedding-3-small."""

    # text-embedding-3-small: 1536 dimensions, $0.00002/1K tokens
    DEFAULT_MODEL = "text-embedding-3-small"
    DEFAULT_DIMENSIONS = 1536

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        """Initialize the OpenAI embedding adapter.
        
        Args:
            api_key: OpenAI API key
            model: Embedding model to use (default: text-embedding-3-small)
            dimensions: Number of dimensions (default: 1536)
        """
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    async def embed(self, text: str) -> EmbeddingResult:
        """Generate an embedding for a single text.
        
        Args:
            text: The text to embed
            
        Returns:
            EmbeddingResult with the embedding vector
        """
        # Truncate very long texts to avoid API limits
        # text-embedding-3-small max is 8191 tokens
        truncated_text = text[:30000]  # Rough char limit
        
        t0 = time.perf_counter()
        response = await self._client.embeddings.create(
            model=self._model,
            input=truncated_text,
            dimensions=self._dimensions,
        )
        _record(self._model, response.usage.total_tokens, t0)
        
        embedding_data = response.data[0]
        
        return EmbeddingResult(
            text=truncated_text,
            embedding=embedding_data.embedding,
            model=self._model,
            dimensions=self._dimensions,
            tokens_used=response.usage.total_tokens,
        )

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of EmbeddingResults
        """
        if not texts:
            return []
        
        # Truncate texts
        truncated_texts = [t[:30000] for t in texts]
        
        t0 = time.perf_counter()
        response = await self._client.embeddings.create(
            model=self._model,
            input=truncated_texts,
            dimensions=self._dimensions,
        )
        _record(self._model, response.usage.total_tokens, t0)
        
        results = []
        tokens_per_text = response.usage.total_tokens // len(texts)
        
        for i, embedding_data in enumerate(response.data):
            results.append(
                EmbeddingResult(
                    text=truncated_texts[i],
                    embedding=embedding_data.embedding,
                    model=self._model,
                    dimensions=self._dimensions,
                    tokens_used=tokens_per_text,
                )
            )
        
        return results

    def get_dimensions(self) -> int:
        """Get the dimensionality of embeddings from this provider."""
        return self._dimensions
