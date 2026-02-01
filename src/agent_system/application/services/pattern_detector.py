"""Pattern Detection Service - Identifies recurring behaviors and patterns from user interactions."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from agent_system.domain.value_objects import UserId
from agent_system.domain.value_objects.knowledge import PatternType

logger = logging.getLogger(__name__)


class PatternDetector:
    """Detects patterns in user behavior from conversation history and knowledge graph.
    
    Analyzes:
    - Query frequency patterns (recurring questions)
    - Temporal patterns (daily/weekly routines)
    - Topic clustering (related interests)
    - Activity patterns (gym, meals, meetings at regular times)
    """
    
    def __init__(self, knowledge_graph_port: Any):
        """Initialize the pattern detector.
        
        Args:
            knowledge_graph_port: The Neo4j adapter for accessing graph data
        """
        self.knowledge_graph = knowledge_graph_port
    
    async def detect_patterns(
        self,
        user_id: UserId,
        lookback_days: int = 30,
        min_occurrences: int = 3,
    ) -> list[dict[str, Any]]:
        """Detect all patterns for a user.
        
        Args:
            user_id: The user to analyze
            lookback_days: Number of days to analyze
            min_occurrences: Minimum occurrences to consider a pattern
            
        Returns:
            List of detected patterns with metadata
        """
        patterns = []
        
        # Get messages from the lookback period
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=lookback_days)
        
        try:
            messages = await self.knowledge_graph.recall_from_period(
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                limit=500,
            )
        except Exception as e:
            logger.error(f"Failed to fetch messages for pattern detection: {e}")
            return patterns
        
        if not messages:
            return patterns
        
        # Detect recurring query patterns
        query_patterns = await self._detect_recurring_queries(
            messages, min_occurrences
        )
        patterns.extend(query_patterns)
        
        # Detect temporal patterns (time of day activity)
        temporal_patterns = await self._detect_temporal_patterns(
            messages, min_occurrences
        )
        patterns.extend(temporal_patterns)
        
        # Detect weekly patterns
        weekly_patterns = await self._detect_weekly_patterns(
            messages, min_occurrences
        )
        patterns.extend(weekly_patterns)
        
        return patterns
    
    async def _detect_recurring_queries(
        self,
        messages: list[dict[str, Any]],
        min_occurrences: int,
    ) -> list[dict[str, Any]]:
        """Detect recurring query patterns.
        
        Looks for similar questions asked multiple times.
        """
        patterns = []
        
        # Extract user messages only
        user_messages = [
            m for m in messages 
            if m.get("role") == "user" and m.get("content")
        ]
        
        if len(user_messages) < min_occurrences:
            return patterns
        
        # Group by normalized content (simplified - could use embeddings)
        content_groups: dict[str, list[dict]] = defaultdict(list)
        for msg in user_messages:
            content = msg.get("content", "").lower().strip()
            # Simple normalization - remove punctuation and extra spaces
            normalized = " ".join(content.split())[:100]
            content_groups[normalized].append(msg)
        
        # Find recurring patterns
        for normalized, occurrences in content_groups.items():
            if len(occurrences) >= min_occurrences:
                # Calculate average interval between occurrences
                timestamps = []
                for occ in occurrences:
                    ts = occ.get("created_at")
                    if ts:
                        try:
                            if isinstance(ts, str):
                                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                            else:
                                timestamps.append(ts)
                        except Exception:
                            pass
                
                frequency = None
                if len(timestamps) >= 2:
                    timestamps.sort()
                    intervals = [
                        (timestamps[i+1] - timestamps[i]).total_seconds() / 3600
                        for i in range(len(timestamps) - 1)
                    ]
                    avg_hours = sum(intervals) / len(intervals)
                    if avg_hours < 24:
                        frequency = f"every {avg_hours:.1f} hours"
                    elif avg_hours < 168:  # 7 days
                        frequency = f"every {avg_hours/24:.1f} days"
                    else:
                        frequency = f"every {avg_hours/168:.1f} weeks"
                
                patterns.append({
                    "pattern_type": PatternType.RECURRING_QUERY.value,
                    "description": f"Recurring query: '{normalized[:50]}...'",
                    "frequency": frequency,
                    "occurrence_count": len(occurrences),
                    "confidence": min(len(occurrences) / 10, 1.0),
                    "sample_content": normalized[:100],
                })
        
        return patterns
    
    async def _detect_temporal_patterns(
        self,
        messages: list[dict[str, Any]],
        min_occurrences: int,
    ) -> list[dict[str, Any]]:
        """Detect daily temporal patterns (e.g., active at certain hours)."""
        patterns = []
        
        # Group messages by hour of day
        hour_counts: dict[int, int] = defaultdict(int)
        
        for msg in messages:
            ts = msg.get("created_at")
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = ts
                    hour_counts[dt.hour] += 1
                except Exception:
                    pass
        
        if not hour_counts:
            return patterns
        
        # Find peak activity hours
        total_msgs = sum(hour_counts.values())
        avg_per_hour = total_msgs / 24
        
        # Find hours with significantly higher activity (>2x average)
        peak_hours = []
        for hour, count in hour_counts.items():
            if count >= min_occurrences and count > avg_per_hour * 2:
                peak_hours.append((hour, count))
        
        if peak_hours:
            # Group consecutive peak hours
            peak_hours.sort(key=lambda x: x[0])
            
            for hour, count in peak_hours:
                hour_label = f"{hour:02d}:00 - {(hour+1) % 24:02d}:00"
                if 5 <= hour < 12:
                    period = "morning"
                elif 12 <= hour < 17:
                    period = "afternoon"
                elif 17 <= hour < 21:
                    period = "evening"
                else:
                    period = "night"
                
                patterns.append({
                    "pattern_type": PatternType.DAILY_HABIT.value,
                    "description": f"Active in the {period} ({hour_label})",
                    "frequency": "daily",
                    "occurrence_count": count,
                    "confidence": min(count / (min_occurrences * 3), 1.0),
                    "hour": hour,
                })
        
        return patterns
    
    async def _detect_weekly_patterns(
        self,
        messages: list[dict[str, Any]],
        min_occurrences: int,
    ) -> list[dict[str, Any]]:
        """Detect weekly patterns (e.g., more active on certain days)."""
        patterns = []
        
        # Group messages by day of week
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_counts: dict[int, int] = defaultdict(int)
        
        for msg in messages:
            ts = msg.get("created_at")
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = ts
                    day_counts[dt.weekday()] += 1
                except Exception:
                    pass
        
        if not day_counts:
            return patterns
        
        # Find peak activity days
        total_msgs = sum(day_counts.values())
        avg_per_day = total_msgs / 7
        
        for day, count in day_counts.items():
            if count >= min_occurrences and count > avg_per_day * 1.5:
                patterns.append({
                    "pattern_type": PatternType.WEEKLY_EVENT.value,
                    "description": f"More active on {day_names[day]}s",
                    "frequency": "weekly",
                    "occurrence_count": count,
                    "confidence": min(count / (min_occurrences * 2), 1.0),
                    "day_of_week": day,
                    "day_name": day_names[day],
                })
        
        return patterns
    
    async def store_detected_patterns(
        self,
        user_id: UserId,
        patterns: list[dict[str, Any]],
    ) -> int:
        """Store detected patterns in the knowledge graph.
        
        Args:
            user_id: The user whose patterns these are
            patterns: List of detected patterns
            
        Returns:
            Number of patterns stored
        """
        stored = 0
        
        for pattern in patterns:
            try:
                # Store as a Pattern node (using the Thread storage as base)
                await self.knowledge_graph.store_thread(
                    user_id=user_id,
                    name=f"Pattern: {pattern.get('description', 'Unknown')[:50]}",
                    description=f"Detected pattern: {pattern.get('description')}. "
                               f"Frequency: {pattern.get('frequency', 'unknown')}. "
                               f"Confidence: {pattern.get('confidence', 0.5):.0%}",
                    topics=[pattern.get("pattern_type", "pattern")],
                )
                stored += 1
            except Exception as e:
                logger.error(f"Failed to store pattern: {e}")
        
        return stored
    
    async def get_predictions(
        self,
        user_id: UserId,
    ) -> list[dict[str, Any]]:
        """Get predictions based on detected patterns.
        
        Returns predictions like:
        - "Based on your pattern, you might want to ask about X soon"
        - "You usually do Y around this time"
        
        Args:
            user_id: The user to predict for
            
        Returns:
            List of predictions
        """
        predictions = []
        patterns = await self.detect_patterns(user_id, lookback_days=14, min_occurrences=2)
        
        now = datetime.utcnow()
        current_hour = now.hour
        current_day = now.weekday()
        
        for pattern in patterns:
            pattern_type = pattern.get("pattern_type", "")
            
            # Predict based on daily habits
            if pattern_type == PatternType.DAILY_HABIT.value:
                pattern_hour = pattern.get("hour", -1)
                if abs(pattern_hour - current_hour) <= 1:
                    predictions.append({
                        "type": "daily_habit",
                        "message": f"You're typically active around this time. {pattern.get('description', '')}",
                        "confidence": pattern.get("confidence", 0.5),
                    })
            
            # Predict based on weekly patterns
            elif pattern_type == PatternType.WEEKLY_EVENT.value:
                pattern_day = pattern.get("day_of_week", -1)
                if pattern_day == current_day:
                    predictions.append({
                        "type": "weekly_event",
                        "message": f"Today is {pattern.get('day_name', 'a day')} - {pattern.get('description', '')}",
                        "confidence": pattern.get("confidence", 0.5),
                    })
            
            # Predict recurring queries
            elif pattern_type == PatternType.RECURRING_QUERY.value:
                if pattern.get("confidence", 0) >= 0.5:
                    predictions.append({
                        "type": "recurring_query",
                        "message": f"You might want to ask about: {pattern.get('sample_content', '')[:50]}",
                        "confidence": pattern.get("confidence", 0.5),
                    })
        
        # Sort by confidence
        predictions.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return predictions[:5]
