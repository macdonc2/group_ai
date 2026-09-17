"""Smart datetime parsing for vague time references in events.

Uses LLM interpretation for intelligent understanding of natural language
time references like "tonight", "next Tuesday", "this weekend", etc.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

import dateparser
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)


class InterpretedDateTime(BaseModel):
    """LLM-interpreted datetime from natural language."""
    
    date: Annotated[str, Field(description="The date in YYYY-MM-DD format")]
    time: Annotated[str, Field(description="The time in HH:MM format (24-hour). Use sensible defaults: 'tonight'->18:00, 'morning'->09:00, 'afternoon'->14:00, 'evening'->18:00. If no time implied, use 09:00.")]
    confidence: Annotated[float, Field(ge=0.0, le=1.0, description="Confidence in interpretation (0.0-1.0)")]
    reasoning: Annotated[str, Field(description="Brief explanation of interpretation")]


DATETIME_INTERPRETATION_PROMPT = """You are a datetime interpreter. Given a natural language time reference and the current date/time, determine the specific date and time being referred to.

RULES:
1. Always interpret relative to the provided current date/time
2. Use sensible time defaults when not specified:
   - "tonight" or "this evening" → 18:00 (6 PM)
   - "morning" → 09:00 (9 AM)  
   - "afternoon" → 14:00 (2 PM)
   - "evening" or "night" → 18:00 (6 PM)
   - No time mentioned → 09:00 (9 AM) as all-day proxy
3. "next week" means 7 days from now
4. "this weekend" means the coming Saturday
5. "next [weekday]" means the next occurrence of that day (could be this week or next)
6. Always prefer future dates unless clearly referring to the past
7. Output date as YYYY-MM-DD and time as HH:MM (24-hour format)

Examples:
- "tonight" on 2026-01-30 → date: 2026-01-30, time: 18:00
- "tomorrow at 3pm" on 2026-01-30 → date: 2026-01-31, time: 15:00
- "next Tuesday" on 2026-01-30 (Thursday) → date: 2026-02-03, time: 09:00
- "this weekend" on 2026-01-30 (Thursday) → date: 2026-02-01 (Saturday), time: 10:00
- "next week" on 2026-01-30 → date: 2026-02-06, time: 09:00
"""


def _get_datetime_interpreter(api_key: str | None = None) -> Agent[None, InterpretedDateTime]:
    """Create an LLM agent for interpreting datetime strings."""
    # Try provided key, then environment, then settings
    key = api_key or os.environ.get("OPENAI_API_KEY")
    
    if not key:
        # Try to get from application settings
        try:
            from agent_system.composition_root.config import get_settings
            key = get_settings().openai_api_key
        except Exception:
            pass
    
    if key:
        model = OpenAIResponsesModel("gpt-5-mini", provider=OpenAIProvider(api_key=key))
    else:
        model = "openai:gpt-5-mini"
    
    return Agent(
        model,
        output_type=InterpretedDateTime,
        system_prompt=DATETIME_INTERPRETATION_PROMPT,
    )


async def parse_vague_datetime(
    datetime_str: str,
    user_timezone: str = "UTC",
    reference_time: datetime | None = None,
    api_key: str | None = None,
) -> datetime | None:
    """Parse a datetime string using LLM interpretation for vague references.
    
    This function uses an LLM to intelligently interpret natural language
    time references like "tonight", "next Tuesday", "this weekend", etc.
    
    Args:
        datetime_str: Natural language datetime string (e.g., "tonight", "tomorrow at 3pm")
        user_timezone: User's timezone name (e.g., "America/Chicago")
        reference_time: Reference time for relative dates (defaults to now)
        
    Returns:
        Parsed datetime in UTC, or None if parsing failed
    """
    if not datetime_str or not datetime_str.strip():
        return None
    
    datetime_str = datetime_str.strip()
    
    try:
        user_tz = ZoneInfo(user_timezone)
    except Exception:
        logger.warning(f"Invalid timezone '{user_timezone}', falling back to UTC")
        user_tz = ZoneInfo("UTC")
    
    now = reference_time or datetime.now(user_tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=user_tz)
    
    # First try dateparser for well-formed dates
    parsed_dt = dateparser.parse(
        datetime_str,
        settings={
            'TIMEZONE': user_timezone,
            'RETURN_AS_TIMEZONE_AWARE': True,
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': now.replace(tzinfo=None),
        }
    )
    
    if parsed_dt is not None:
        # Apply time defaults for vague references
        parsed_dt = _apply_time_defaults(datetime_str, parsed_dt, now)
        utc_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        logger.info(f"Dateparser parsed: '{datetime_str}' -> {parsed_dt} -> UTC: {utc_dt}")
        return utc_dt
    
    # Dateparser failed - use LLM interpretation
    logger.info(f"Dateparser couldn't parse '{datetime_str}', using LLM interpretation")
    
    try:
        interpreter = _get_datetime_interpreter(api_key=api_key)
        
        # Format current time for LLM context
        current_time_str = now.strftime("%Y-%m-%d %H:%M %A")  # e.g., "2026-01-30 15:30 Thursday"
        
        prompt = f"""Current date/time: {current_time_str} ({user_timezone})

Interpret this time reference: "{datetime_str}"

What specific date and time does this refer to?"""
        
        result = await interpreter.run(prompt)
        interpreted = result.output
        
        logger.info(f"LLM interpreted '{datetime_str}' as {interpreted.date} {interpreted.time} ({interpreted.reasoning})")
        
        # Parse the LLM's response
        try:
            parsed_dt = datetime.strptime(f"{interpreted.date} {interpreted.time}", "%Y-%m-%d %H:%M")
            parsed_dt = parsed_dt.replace(tzinfo=user_tz)
            utc_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
            logger.info(f"Final parsed datetime: '{datetime_str}' -> {parsed_dt} -> UTC: {utc_dt}")
            return utc_dt
        except ValueError as e:
            logger.error(f"Could not parse LLM response '{interpreted.date} {interpreted.time}': {e}")
            return None
            
    except Exception as e:
        logger.error(f"LLM datetime interpretation failed for '{datetime_str}': {e}")
        return None


def _apply_time_defaults(
    datetime_str: str,
    parsed_dt: datetime,
    now: datetime,
) -> datetime:
    """Apply sensible time defaults when no specific time was mentioned.
    
    Args:
        datetime_str: Original datetime string for context
        parsed_dt: Initially parsed datetime
        now: Current reference time
        
    Returns:
        Datetime with appropriate time default applied
    """
    datetime_lower = datetime_str.lower()
    
    # Check if a specific time was mentioned
    specific_time_pattern = re.compile(
        r'(\d{1,2}:\d{2}|\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)|at\s+\d{1,2})',
        re.IGNORECASE
    )
    if specific_time_pattern.search(datetime_str):
        return parsed_dt  # Time was specified, don't override
    
    # Tonight / this evening → 6 PM
    if re.search(r'\btonight\b|\bthis\s+evening\b', datetime_lower):
        return parsed_dt.replace(hour=18, minute=0, second=0, microsecond=0)
    
    # Morning context → 9 AM
    if re.search(r'\bmorning\b', datetime_lower):
        return parsed_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    
    # Afternoon context → 2 PM
    if re.search(r'\bafternoon\b', datetime_lower):
        return parsed_dt.replace(hour=14, minute=0, second=0, microsecond=0)
    
    # Evening/night context → 6 PM
    if re.search(r'\bevening\b|\bnight\b', datetime_lower):
        return parsed_dt.replace(hour=18, minute=0, second=0, microsecond=0)
    
    # Weekend → 10 AM
    if re.search(r'\bweekend\b', datetime_lower):
        return parsed_dt.replace(hour=10, minute=0, second=0, microsecond=0)
    
    # Default for any other vague reference → 9 AM (all-day proxy)
    if parsed_dt.hour == 0 and parsed_dt.minute == 0:
        return parsed_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    
    return parsed_dt


def is_all_day_event(datetime_str: str) -> bool:
    """Check if the datetime string implies an all-day event.
    
    An all-day event is one where no specific time was mentioned.
    
    Args:
        datetime_str: The natural language datetime string
        
    Returns:
        True if this should be treated as an all-day event
    """
    if not datetime_str:
        return True
    
    specific_time_pattern = re.compile(
        r'(\d{1,2}:\d{2}|\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)|at\s+\d{1,2})',
        re.IGNORECASE
    )
    return not bool(specific_time_pattern.search(datetime_str))
