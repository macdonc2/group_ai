"""Application services - Cross-cutting application logic."""

from agent_system.application.services.calendar_sync import CalendarSyncService
from agent_system.application.services.contradiction_detector import (
    BatchContradictionChecker,
    ContradictionAssessment,
    ContradictionDetector,
)
from agent_system.application.services.datetime_parser import (
    is_all_day_event,
    parse_vague_datetime,
)
from agent_system.application.services.expertise_profiler import ExpertiseProfiler
from agent_system.application.services.inference_engine import InferenceEngine, InferenceRule
from agent_system.application.services.pattern_detector import PatternDetector
from agent_system.application.services.preference_aggregator import (
    AggregatedPreference,
    PreferenceAggregator,
)

__all__ = [
    "CalendarSyncService",
    "is_all_day_event",
    "parse_vague_datetime",
    # Pattern Detection
    "PatternDetector",
    # Contradiction Detection
    "ContradictionDetector",
    "ContradictionAssessment",
    "BatchContradictionChecker",
    # Expertise Profiling
    "ExpertiseProfiler",
    # Multi-hop Inference
    "InferenceEngine",
    "InferenceRule",
    # Preference Aggregation
    "PreferenceAggregator",
    "AggregatedPreference",
]
