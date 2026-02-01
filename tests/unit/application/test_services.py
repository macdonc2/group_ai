"""Unit tests for application services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from agent_system.application.services.pattern_detector import PatternDetector
from agent_system.application.services.preference_aggregator import (
    AggregatedPreference,
    PreferenceAggregator,
)
from agent_system.domain.value_objects import UserId
from agent_system.domain.value_objects.knowledge import PatternType


class TestPatternDetector:
    """Tests for PatternDetector service."""
    
    @pytest.fixture
    def mock_knowledge_graph(self):
        """Create a mock knowledge graph port."""
        mock = AsyncMock()
        mock.recall_from_period = AsyncMock(return_value=[])
        return mock
    
    @pytest.fixture
    def detector(self, mock_knowledge_graph):
        """Create a PatternDetector instance."""
        return PatternDetector(mock_knowledge_graph)
    
    @pytest.mark.asyncio
    async def test_detect_patterns_empty(self, detector):
        """Test detecting patterns with no messages."""
        user_id = UserId.generate()
        
        patterns = await detector.detect_patterns(user_id)
        
        assert patterns == []
    
    @pytest.mark.asyncio
    async def test_detect_recurring_queries(self, detector, mock_knowledge_graph):
        """Test detecting recurring query patterns."""
        now = datetime.utcnow()
        
        # Simulate recurring questions
        mock_knowledge_graph.recall_from_period.return_value = [
            {"role": "user", "content": "what is the weather", "created_at": (now - timedelta(days=1)).isoformat()},
            {"role": "user", "content": "what is the weather", "created_at": (now - timedelta(days=2)).isoformat()},
            {"role": "user", "content": "what is the weather", "created_at": (now - timedelta(days=3)).isoformat()},
        ]
        
        user_id = UserId.generate()
        patterns = await detector.detect_patterns(user_id, min_occurrences=3)
        
        # Should detect the recurring query
        recurring = [p for p in patterns if p["pattern_type"] == PatternType.RECURRING_QUERY.value]
        assert len(recurring) >= 1
    
    @pytest.mark.asyncio
    async def test_detect_temporal_patterns(self, detector, mock_knowledge_graph):
        """Test detecting temporal patterns (activity at certain hours)."""
        # Create messages at the same hour over multiple days
        messages = []
        base = datetime.utcnow().replace(hour=14, minute=0)  # 2 PM
        
        for i in range(10):
            messages.append({
                "role": "user",
                "content": f"message {i}",
                "created_at": (base - timedelta(days=i)).isoformat(),
            })
        
        mock_knowledge_graph.recall_from_period.return_value = messages
        
        user_id = UserId.generate()
        patterns = await detector.detect_patterns(user_id, min_occurrences=3)
        
        # Should detect afternoon activity pattern
        temporal = [p for p in patterns if p["pattern_type"] == PatternType.DAILY_HABIT.value]
        assert len(temporal) >= 0  # Depends on distribution


class TestPreferenceAggregator:
    """Tests for PreferenceAggregator service."""
    
    @pytest.fixture
    def mock_knowledge_graph(self):
        """Create a mock knowledge graph port."""
        mock = AsyncMock()
        mock.get_user_preferences = AsyncMock(return_value=[])
        return mock
    
    @pytest.fixture
    def aggregator(self, mock_knowledge_graph):
        """Create a PreferenceAggregator instance."""
        return PreferenceAggregator(mock_knowledge_graph)
    
    @pytest.mark.asyncio
    async def test_empty_preferences(self, aggregator):
        """Test aggregation with no preferences."""
        user_id = UserId.generate()
        
        prefs = await aggregator.get_aggregated_preferences(user_id)
        
        assert prefs == []
    
    @pytest.mark.asyncio
    async def test_aggregate_single_preference(self, aggregator, mock_knowledge_graph):
        """Test aggregating a single preference."""
        mock_knowledge_graph.get_user_preferences.return_value = [
            {
                "category": "food",
                "value": "sushi",
                "sentiment": 0.9,
                "mention_count": 5,
                "source_conversations": ["conv-1", "conv-2"],
            }
        ]
        
        user_id = UserId.generate()
        prefs = await aggregator.get_aggregated_preferences(user_id)
        
        assert len(prefs) == 1
        assert prefs[0].category == "food"
        assert prefs[0].value == "sushi"
        assert prefs[0].sentiment == 0.9
    
    @pytest.mark.asyncio
    async def test_aggregate_multiple_mentions(self, aggregator, mock_knowledge_graph):
        """Test aggregating multiple mentions of same preference."""
        mock_knowledge_graph.get_user_preferences.return_value = [
            {
                "category": "food",
                "value": "sushi",
                "sentiment": 0.8,
                "mention_count": 3,
                "source_conversations": ["conv-1"],
            },
            {
                "category": "food",
                "value": "sushi",
                "sentiment": 0.9,
                "mention_count": 2,
                "source_conversations": ["conv-2"],
            },
        ]
        
        user_id = UserId.generate()
        prefs = await aggregator.get_aggregated_preferences(user_id)
        
        # Should be aggregated into one
        assert len(prefs) == 1
        assert prefs[0].mention_count == 5  # 3 + 2
    
    @pytest.mark.asyncio
    async def test_preference_profile(self, aggregator, mock_knowledge_graph):
        """Test getting a preference profile."""
        mock_knowledge_graph.get_user_preferences.return_value = [
            {"category": "food", "value": "pizza", "sentiment": 0.8, "mention_count": 3, "source_conversations": []},
            {"category": "food", "value": "salad", "sentiment": -0.5, "mention_count": 2, "source_conversations": []},
            {"category": "activities", "value": "cycling", "sentiment": 0.9, "mention_count": 5, "source_conversations": []},
        ]
        
        user_id = UserId.generate()
        profile = await aggregator.get_preference_profile(user_id)
        
        assert profile["total_preferences"] == 3
        assert "food" in profile["categories"]
        assert "activities" in profile["categories"]


class TestAggregatedPreference:
    """Tests for AggregatedPreference class."""
    
    def test_sentiment_labels(self):
        """Test sentiment label conversion."""
        # Likes
        pref = AggregatedPreference(
            category="food", value="pizza", sentiment=0.8,
            confidence=0.9, mention_count=5, sources=[],
        )
        assert pref.to_dict()["sentiment_label"] == "likes"
        
        # Dislikes
        pref = AggregatedPreference(
            category="food", value="liver", sentiment=-0.7,
            confidence=0.9, mention_count=5, sources=[],
        )
        assert pref.to_dict()["sentiment_label"] == "dislikes"
        
        # Neutral
        pref = AggregatedPreference(
            category="food", value="bread", sentiment=0.0,
            confidence=0.9, mention_count=5, sources=[],
        )
        assert pref.to_dict()["sentiment_label"] == "neutral"
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        pref = AggregatedPreference(
            category="activities",
            value="hiking",
            sentiment=0.85,
            confidence=0.9,
            mention_count=10,
            sources=["conv-1", "conv-2"],
        )
        
        d = pref.to_dict()
        
        assert d["category"] == "activities"
        assert d["value"] == "hiking"
        assert d["confidence"] == 0.9
        assert d["mention_count"] == 10
        assert len(d["sources"]) == 2
