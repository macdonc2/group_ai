"""Preference Aggregation Service - Consolidates user preferences from multiple sources."""

import logging
from collections import defaultdict
from typing import Any

from agent_system.domain.value_objects import UserId

logger = logging.getLogger(__name__)


class AggregatedPreference:
    """A preference aggregated from multiple mentions."""
    
    def __init__(
        self,
        category: str,
        value: str,
        sentiment: float,
        confidence: float,
        mention_count: int,
        sources: list[str],
    ):
        self.category = category
        self.value = value
        self.sentiment = sentiment
        self.confidence = confidence
        self.mention_count = mention_count
        self.sources = sources
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "value": self.value,
            "sentiment": self.sentiment,
            "sentiment_label": self._sentiment_label(),
            "confidence": self.confidence,
            "mention_count": self.mention_count,
            "sources": self.sources,
        }
    
    def _sentiment_label(self) -> str:
        """Convert sentiment score to label."""
        if self.sentiment >= 0.5:
            return "likes"
        elif self.sentiment <= -0.5:
            return "dislikes"
        elif self.sentiment >= 0.2:
            return "somewhat likes"
        elif self.sentiment <= -0.2:
            return "somewhat dislikes"
        else:
            return "neutral"


class PreferenceAggregator:
    """Aggregates and consolidates user preferences from scattered mentions.
    
    Combines preferences from:
    - Explicit statements ("I love sushi")
    - Implied preferences (ordering sushi frequently)
    - Behavioral patterns (visiting certain places)
    - Entity relationships (liking a pet's food suggests animal preference)
    """
    
    def __init__(self, knowledge_graph_port: Any):
        """Initialize the aggregator.
        
        Args:
            knowledge_graph_port: The Neo4j adapter
        """
        self.knowledge_graph = knowledge_graph_port
    
    async def get_aggregated_preferences(
        self,
        user_id: UserId,
        category: str | None = None,
        min_confidence: float = 0.3,
    ) -> list[AggregatedPreference]:
        """Get aggregated preferences for a user.
        
        Combines and deduplicates preferences from multiple sources.
        
        Args:
            user_id: The user's ID
            category: Optional category filter
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of aggregated preferences
        """
        # Get raw preferences from knowledge graph
        raw_prefs = await self.knowledge_graph.get_user_preferences(
            user_id=user_id,
            category=category,
            min_confidence=0.0,  # Get all, filter later
        )
        
        # Group by normalized value
        grouped: dict[str, list[dict]] = defaultdict(list)
        for pref in raw_prefs:
            key = self._normalize_preference(
                pref.get("category", ""),
                pref.get("value", ""),
            )
            grouped[key].append(pref)
        
        # Aggregate each group
        aggregated = []
        for key, prefs in grouped.items():
            agg = self._aggregate_group(prefs)
            if agg.confidence >= min_confidence:
                aggregated.append(agg)
        
        # Sort by confidence and mention count
        aggregated.sort(
            key=lambda x: (x.confidence, x.mention_count),
            reverse=True,
        )
        
        return aggregated
    
    def _normalize_preference(self, category: str, value: str) -> str:
        """Normalize a preference for grouping."""
        return f"{category.lower().strip()}:{value.lower().strip()}"
    
    def _aggregate_group(
        self,
        prefs: list[dict[str, Any]],
    ) -> AggregatedPreference:
        """Aggregate a group of related preferences.
        
        Combines multiple mentions of similar preferences into one.
        """
        if not prefs:
            raise ValueError("Cannot aggregate empty group")
        
        # Use the most common category and value
        category = prefs[0].get("category", "general")
        value = prefs[0].get("value", "unknown")
        
        # Weighted average of sentiments
        total_sentiment = 0.0
        total_weight = 0.0
        sources = []
        total_mentions = 0
        
        for pref in prefs:
            mentions = pref.get("mention_count", 1)
            sentiment = pref.get("sentiment", 0.5)
            
            total_sentiment += sentiment * mentions
            total_weight += mentions
            total_mentions += mentions
            
            # Collect source conversations
            for source in pref.get("source_conversations", []):
                if source not in sources:
                    sources.append(source)
        
        avg_sentiment = total_sentiment / total_weight if total_weight > 0 else 0.5
        
        # Confidence increases with more mentions and sources
        base_confidence = min(total_mentions / 5, 0.8)
        source_bonus = min(len(sources) / 3, 0.2)
        confidence = min(base_confidence + source_bonus, 1.0)
        
        return AggregatedPreference(
            category=category,
            value=value,
            sentiment=avg_sentiment,
            confidence=confidence,
            mention_count=total_mentions,
            sources=sources[:10],  # Limit stored sources
        )
    
    async def get_preference_profile(
        self,
        user_id: UserId,
    ) -> dict[str, Any]:
        """Get a comprehensive preference profile for a user.
        
        Organizes preferences by category with summary statistics.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Dict with categorized preferences and summary
        """
        prefs = await self.get_aggregated_preferences(user_id, min_confidence=0.3)
        
        # Organize by category
        by_category: dict[str, list[dict]] = defaultdict(list)
        for pref in prefs:
            by_category[pref.category].append(pref.to_dict())
        
        # Build profile
        profile = {
            "total_preferences": len(prefs),
            "categories": list(by_category.keys()),
            "preferences_by_category": dict(by_category),
            "top_likes": [],
            "top_dislikes": [],
        }
        
        # Extract top likes and dislikes
        sorted_prefs = sorted(prefs, key=lambda x: x.sentiment, reverse=True)
        
        for pref in sorted_prefs[:5]:
            if pref.sentiment >= 0.5:
                profile["top_likes"].append({
                    "category": pref.category,
                    "value": pref.value,
                    "confidence": pref.confidence,
                })
        
        for pref in sorted_prefs[-5:]:
            if pref.sentiment <= -0.3:
                profile["top_dislikes"].append({
                    "category": pref.category,
                    "value": pref.value,
                    "confidence": pref.confidence,
                })
        
        return profile
    
    async def find_related_preferences(
        self,
        user_id: UserId,
        value: str,
    ) -> list[AggregatedPreference]:
        """Find preferences related to a given value.
        
        Useful for finding similar preferences when making recommendations.
        
        Args:
            user_id: The user's ID
            value: The value to find relations for
            
        Returns:
            List of related preferences
        """
        all_prefs = await self.get_aggregated_preferences(user_id)
        
        # Simple keyword matching for now
        # Could be enhanced with embeddings for semantic similarity
        value_lower = value.lower()
        related = []
        
        for pref in all_prefs:
            pref_value = pref.value.lower()
            # Check for overlap
            if value_lower in pref_value or pref_value in value_lower:
                related.append(pref)
            # Check for category match
            elif value_lower == pref.category.lower():
                related.append(pref)
        
        return related
    
    async def suggest_from_preferences(
        self,
        user_id: UserId,
        category: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Suggest items based on user preferences in a category.
        
        Args:
            user_id: The user's ID
            category: Category to suggest from
            limit: Maximum suggestions
            
        Returns:
            List of suggestions with reasoning
        """
        prefs = await self.get_aggregated_preferences(
            user_id,
            category=category,
            min_confidence=0.5,
        )
        
        suggestions = []
        for pref in prefs[:limit]:
            if pref.sentiment >= 0.3:
                suggestions.append({
                    "suggestion": pref.value,
                    "category": pref.category,
                    "reason": f"You've mentioned liking this {pref.mention_count} time(s)",
                    "confidence": pref.confidence,
                })
        
        return suggestions
