# Entity Recognition Fix Plan

> **Status**: Implemented (2026). Kept as design history. Pets are distinguished from
> people in the social graph, and `get_pet_info` / `list_pets` are live tools. The
> problem statement below describes the original bug, not current behaviour.

## Problem Statement

When asking "What should I do for Zane's birthday?", the system treats Zane as a human (suggesting pizza parties, video games, guest lists) instead of recognizing him as the user's dog.

## Root Cause Analysis

### 1. Two Knowledge Systems Not Connected

**Old System (Working):**
- `KnowledgeNode` with text labels like "Zane is my dog"
- `MessageEmbedding` with full conversation text
- Stores unstructured text about entities

**New System (Not Populated):**
- `PetNode`, `PersonNode`, `LocationNode` (typed entities)
- Never gets populated because entity extraction only runs AFTER response generation
- Entity lookup checks new system first, finds nothing

### 2. Entity Extraction Timing Issue

Current flow:
```
1. User asks about Zane
2. Intent analysis extracts "Zane" as entity
3. ReAct planning creates human-appropriate plan (NO LOOKUP HAPPENS)
4. Response generated treating Zane as human
5. FinalizeKnowledge extracts entities and stores them (TOO LATE)
```

The entity extraction and storage happens AFTER the response, so the first question about an entity always fails.

### 3. Missing `recall_about_topic` Method

The fallback in CreatePlan calls `knowledge_graph_port.recall_about_topic()` but this method doesn't exist in `neo4j_adapter.py`. Only `semantic_search()` and `recall_from_period()` exist.

### 4. No Semantic Search in Entity Lookup

The entity lookup in CreatePlan only checks:
- `list_pets()` - checks new PetNode (empty)
- `list_known_people()` - checks new PersonNode (empty)
- `recall_about_topic()` - method doesn't exist, silently fails

It SHOULD use `semantic_search()` to find text like "Zane is my dog" from MessageEmbedding.

## Proposed Solutions

### Option A: Fix Entity Lookup to Use Existing Data (Quick Fix)

1. Add `recall_about_topic()` method to neo4j_adapter that:
   - Does semantic search on MessageEmbedding
   - Also searches KnowledgeNode labels
   - Returns relevant text snippets

2. Use LLM to extract entity type from snippets:
   - Found: "Zane is my dog and he's an old man baby"
   - LLM determines: Zane = dog
   - Inject into planning context

**Pros:** Works with existing data
**Cons:** Requires LLM call for each entity lookup

### Option B: Backfill New Entity Nodes (Migration)

1. Create migration script that:
   - Scans all MessageEmbedding nodes
   - Uses LLM to extract people/pets/locations
   - Creates PetNode, PersonNode, LocationNode

2. Update entity lookup to work with new nodes

**Pros:** Clean architecture, fast lookups
**Cons:** Requires migration, may miss nuances

### Option C: Hybrid Approach (Recommended)

1. **Immediate:** Fix entity lookup to use semantic search on existing MessageEmbedding
2. **Ongoing:** Keep new entity extraction in FinalizeKnowledge to build typed nodes
3. **Lookup order:**
   - Check PetNode/PersonNode first (fast, typed)
   - Fall back to semantic search on MessageEmbedding (slower, but comprehensive)
   - Use LLM to interpret results if needed

## Implementation Steps

### Phase 1: Add recall_about_topic Method

```python
# In neo4j_adapter.py
async def recall_about_topic(
    self,
    user_id: UserId,
    topic: str,
    limit: int = 5,
) -> list[dict]:
    """Search for mentions of a topic in user's conversation history."""
    query = """
    MATCH (m:MessageEmbedding {user_id: $user_id})
    WHERE toLower(m.content) CONTAINS toLower($topic)
    RETURN m.content as content, m.role as role, m.created_at as created_at
    ORDER BY m.created_at DESC
    LIMIT $limit
    """
    # Also search KnowledgeNode labels
    # Return combined results
```

### Phase 2: Add Entity Type Detection

When recall finds text like "Zane is my dog", use quick LLM call to extract:
```python
{
    "entity_name": "Zane",
    "entity_type": "pet",
    "species": "dog",
    "description": "old man baby"
}
```

### Phase 3: Improve Entity Context Injection

In CreatePlan, after entity lookup:
```python
if entity_info_parts:
    entity_context = f"""
IMPORTANT - Known entities mentioned:
{chr(10).join(f'- {p}' for p in entity_info_parts)}

Use this context when planning. A dog's birthday needs dog activities (park, treats, toys), 
not human activities (pizza party, video games).
"""
```

### Phase 4: Consider Pre-Response Entity Check

Add an optional step before ReAct planning:
```
1. Extract entities from user input
2. Look up each entity in knowledge graph
3. If entity type unknown, ASK the user: "Is Zane a person or a pet?"
4. Then proceed with appropriate planning
```

## Testing Checklist

- [ ] "What should I do for Zane's birthday?" → recognizes dog, suggests dog park/treats
- [ ] "Plan dinner with Sarah" → recognizes spouse, suggests restaurants she likes
- [ ] "Tell me about Bo" → returns info about the cat
- [ ] New entity mentioned → properly extracted and stored for future queries
- [ ] Entity mentioned across multiple conversations → correctly linked

## Files to Modify

1. `src/agent_system/adapters/outbound/graph/neo4j_adapter.py`
   - Add `recall_about_topic()` method
   - Ensure it searches both MessageEmbedding and KnowledgeNode

2. `src/agent_system/adapters/outbound/fsm/nodes.py`
   - Update CreatePlan entity lookup to use `recall_about_topic()`
   - Add LLM call to interpret entity type from text
   - Improve entity context injection

3. `src/agent_system/adapters/outbound/llm/knowledge_extractor.py`
   - Add quick entity type detection function

## Priority

**High** - This is a core feature that currently doesn't work. Users expect the system to remember what they've told it about their pets, family, etc.

## Estimated Effort

- Phase 1: 1-2 hours
- Phase 2: 2-3 hours  
- Phase 3: 1 hour
- Phase 4: 2-3 hours (optional)
- Testing: 1-2 hours

Total: 4-6 hours for core fix, 8-10 hours with optional enhancements
