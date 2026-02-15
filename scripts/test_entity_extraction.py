#!/usr/bin/env -S uv run python
"""Quick test of entity extraction - run locally to verify person/pet/location extraction.

Usage:
    uv run scripts/test_entity_extraction.py
    # Or with explicit text:
    uv run scripts/test_entity_extraction.py "I have a dog named Zane and my friend Sarah has a cat named Bo"
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load .env from project root
_project_root = os.path.join(os.path.dirname(__file__), "..")
load_dotenv(os.path.join(_project_root, ".env"))

# Add src to path
sys.path.insert(0, os.path.join(_project_root, "src"))

from agent_system.adapters.outbound.llm.knowledge_extractor import (
    extract_knowledge_from_text,
)


async def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "I have a dog named Zane. He's an old man baby."
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env. Add it to test extraction.")
        sys.exit(1)

    print(f"Testing extraction with text: {text[:100]}...")
    print()

    result = await extract_knowledge_from_text(text, api_key=api_key)

    print("=== Result ===")
    print(f"Persons: {len(result.persons)}")
    for p in result.persons:
        print(f"  - {p.name} (confidence={p.confidence:.2f}) relationship={p.relationship_type}")

    print(f"Pets: {len(result.pets)}")
    for p in result.pets:
        print(f"  - {p.name} (confidence={p.confidence:.2f}) species={p.species}")

    print(f"Locations: {len(result.locations)}")
    for loc in result.locations:
        print(f"  - {loc.name} (confidence={loc.confidence:.2f}) type={loc.location_type}")

    print(f"\nReasoning: {result.reasoning}")

    stored = [p for p in result.pets if p.confidence >= 0.7] + [p for p in result.persons if p.confidence >= 0.7]
    print(f"\nWould store {len(stored)} entities (confidence >= 0.7)")


if __name__ == "__main__":
    asyncio.run(main())
