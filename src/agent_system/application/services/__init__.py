"""Application services - Cross-cutting application logic."""

from agent_system.application.services.calendar_sync import CalendarSyncService
from agent_system.application.services.inference_engine import InferenceEngine, InferenceRule
from agent_system.application.services.pattern_detector import PatternDetector
from agent_system.application.services.preference_aggregator import (
    AggregatedPreference,
    PreferenceAggregator,
)

__all__ = [
    "CalendarSyncService",
    # Pattern Detection
    "PatternDetector",
    # Multi-hop Inference
    "InferenceEngine",
    "InferenceRule",
    # Preference Aggregation
    "PreferenceAggregator",
    "AggregatedPreference",
]
