# Knowledge Graph Enhancement Plan

> **Status**: Planning  
> **Priority**: Medium-High  
> **Created**: January 2026  
> **Last Updated**: January 2026

## Overview

This document outlines planned enhancements to the knowledge graph system to provide richer context, better memory, and proactive intelligence capabilities.

## Current State

The knowledge graph currently supports:
- Conversation history storage with embeddings
- Semantic search across past messages (k=25, min_score=0.7)
- User pattern tracking (interests, preferences, tools used)
- Event extraction from conversations
- Group chat shared context
- Topic recall via `recall_about_topic` and `recall_group_topic` tools

## Planned Features

---

### Phase 1: Relationship & Entity Tracking

#### 1.1 Social Graph
**Priority**: High  
**Complexity**: Medium

Build a graph of people mentioned in conversations and their relationships to the user.

**Implementation**:
- Create `Person` nodes with properties: name, aliases, relationship_type, first_mentioned, last_mentioned
- Create relationship edges: `KNOWS`, `FAMILY_OF`, `WORKS_WITH`, `FRIEND_OF`
- Extract relationships using NLP entity extraction during message processing
- Add tool: `get_person_info(name)` - returns everything known about a person

**Schema**:
```cypher
(p:Person {
  id: uuid,
  name: string,
  aliases: [string],          // "Dom", "Dominique", "my wife"
  relationship_to_user: string,
  context_notes: string,
  first_mentioned: datetime,
  last_mentioned: datetime
})

(u:User)-[:KNOWS {relationship_type: "spouse"}]->(p:Person)
(p:Person)-[:RELATED_TO {type: "friend"}]->(p2:Person)
```

**Use Cases**:
- "Who is Dominique?" → Returns relationship context
- "What do I know about my colleague Jim?" → Returns work-related context
- Automatic pronoun resolution: "his wife" → looks up person's spouse

---

#### 1.2 Pet/Entity Registry
**Priority**: High  
**Complexity**: Low

Structured storage for pets and other important entities with rich attributes.

**Implementation**:
- Create `Pet` nodes: name, species, breed, age, personality traits, food preferences
- Link to conversations where discussed
- Add tool: `get_pet_info(name)` - comprehensive pet profile

**Schema**:
```cypher
(pet:Pet {
  id: uuid,
  name: string,
  aliases: [string],          // "Bo", "Bo Boy", "the dog"
  species: string,            // "dog", "cat"
  breed: string,
  age: int,
  personality: [string],      // ["playful", "food-motivated"]
  food_preferences: [string],
  health_notes: string
})

(u:User)-[:OWNS]->(pet:Pet)
(pet:Pet)-[:MENTIONED_IN]->(m:Message)
```

---

#### 1.3 Location Graph
**Priority**: Medium  
**Complexity**: Medium

Track places mentioned and their associations/context.

**Implementation**:
- Create `Location` nodes: name, type, address, associated_activities, associated_people
- Extract locations from conversations using NER
- Build associations over time

**Schema**:
```cypher
(loc:Location {
  id: uuid,
  name: string,
  aliases: [string],
  type: string,               // "restaurant", "gym", "workplace"
  address: string,
  city: string,
  notes: string
})

(u:User)-[:FREQUENTS {context: "cycling"}]->(loc:Location)
(p:Person)-[:WORKS_AT]->(loc:Location)
(loc:Location)-[:HOSTS]->(e:Event)
```

**Use Cases**:
- "What's that brewery we talked about?" → Under the Radar Brewery
- "Where does the cycling group meet?" → Surfaces location with context

---

#### 1.4 Entity Linking & Coreference Resolution
**Priority**: High  
**Complexity**: High

Connect mentions of the same entity across conversations.

**Implementation**:
- Maintain alias registry for each entity
- Use embedding similarity to detect potential matches
- Merge entities when confidence is high
- Add disambiguation UI for uncertain cases

**Algorithm**:
1. On new message, extract named entities
2. For each entity, compute embedding
3. Search existing entities with similar embeddings (cosine > 0.85)
4. If match found with same type, link to existing node
5. If uncertain, create candidate link for later resolution

---

### Phase 2: Temporal Intelligence

#### 2.1 Memory Timeline
**Priority**: High  
**Complexity**: Medium

Enable time-based queries over conversation history.

**Implementation**:
- Index all messages by timestamp with granularity (hour, day, week, month)
- Add temporal query support to semantic search
- Create tool: `recall_from_period(start_date, end_date, topic?)`

**Query Examples**:
```cypher
// What was discussed last week about project X?
MATCH (m:Message)-[:ABOUT]->(t:Topic {name: "project X"})
WHERE m.timestamp > datetime() - duration('P7D')
RETURN m.content, m.timestamp
ORDER BY m.timestamp DESC
```

**Use Cases**:
- "What was I focused on last month?"
- "When did I first mention the sourdough starter?"
- "Show me our conversations about the trip from December"

---

#### 2.2 Recurring Pattern Detection
**Priority**: Medium  
**Complexity**: High

Automatically detect habits and recurring behaviors.

**Implementation**:
- Track timestamps of similar queries/topics
- Use statistical analysis to detect periodicity
- Store detected patterns as `Pattern` nodes
- Surface patterns proactively when relevant

**Schema**:
```cypher
(pattern:Pattern {
  id: uuid,
  type: string,               // "recurring_query", "daily_habit", "weekly_event"
  description: string,
  frequency: string,          // "every 4-5 hours", "weekly on Saturday"
  confidence: float,
  last_occurrence: datetime,
  next_expected: datetime
})

(u:User)-[:HAS_PATTERN]->(pattern:Pattern)
(pattern:Pattern)-[:RELATED_TO]->(t:Topic)
```

**Use Cases**:
- "You usually check your sourdough starter every 4-5 hours - it's been 6 hours"
- "You typically plan your week on Sunday evenings"
- Proactive reminders based on detected patterns

---

#### 2.3 Preference Evolution Tracking
**Priority**: Low  
**Complexity**: Medium

Track how user preferences change over time.

**Implementation**:
- Version preference nodes with timestamps
- Create `PreferenceHistory` edges
- Enable queries like "What were my preferences in Q1?"

**Schema**:
```cypher
(pref:Preference {
  id: uuid,
  category: string,
  value: string,
  confidence: float,
  valid_from: datetime,
  valid_until: datetime       // null if current
})

(u:User)-[:HAD_PREFERENCE {period: "2025-Q4"}]->(pref:Preference)
```

---

#### 2.4 Contradiction Detection
**Priority**: Medium  
**Complexity**: High

Flag when new information conflicts with stored knowledge.

**Implementation**:
- On entity updates, compare with existing values
- Use LLM to assess contradiction severity
- Store contradictions for user resolution
- Add tool: `resolve_contradiction(entity, attribute)`

**Detection Algorithm**:
1. Extract facts from new message
2. Query existing facts about same entities
3. Compare using semantic similarity and logical rules
4. If contradiction detected (confidence > 0.8):
   - Flag for user attention
   - Store both versions with timestamps
   - Ask user to clarify if high-importance

**Example**:
- Stored: "Zane is 12 years old"
- New: "Zane turned 10 last month"
- Response: "I noticed you mentioned Zane is 10, but I had recorded he was 12. Which is correct?"

---

### Phase 3: Proactive Intelligence

#### 3.1 Contextual Suggestions
**Priority**: High  
**Complexity**: Medium

Use graph relationships to surface relevant information proactively.

**Implementation**:
- On each query, identify mentioned entities
- Traverse graph to find related context
- Score relevance based on recency, relationship strength, topic similarity
- Include top suggestions in response generation context

**Algorithm**:
```python
def get_contextual_suggestions(message: str, user_id: str) -> list[Suggestion]:
    entities = extract_entities(message)
    suggestions = []
    
    for entity in entities:
        # Find related nodes within 2 hops
        related = graph.query("""
            MATCH (e {name: $name})-[r*1..2]-(related)
            WHERE related:Event OR related:Person OR related:Location
            RETURN related, r, 
                   score(related.last_mentioned, related.mention_count)
            ORDER BY score DESC
            LIMIT 5
        """, name=entity.name)
        
        suggestions.extend(related)
    
    return dedupe_and_rank(suggestions)
```

**Use Cases**:
- User mentions "biking" → surface cycling group info, upcoming rides, Radar Riders
- User asks about "Saturday" → show weekend events, recurring Saturday activities
- User mentions "Brandon" → recall haircut context, salon location

---

#### 3.2 Cross-Conversation Threading
**Priority**: Medium  
**Complexity**: Medium

Link related conversations into coherent narratives/projects.

**Implementation**:
- Detect topic continuity across conversations
- Create `Thread` nodes that span conversations
- Add tool: `get_thread_history(topic)` - full narrative

**Schema**:
```cypher
(thread:Thread {
  id: uuid,
  name: string,               // "Sourdough Project", "Trip Planning"
  created: datetime,
  last_updated: datetime,
  status: string              // "active", "completed", "paused"
})

(c:Conversation)-[:PART_OF]->(thread:Thread)
(m:Message)-[:CONTINUES]->(m2:Message)  // Cross-conversation links
```

**Use Cases**:
- "Catch me up on the sourdough project" → Summarizes all related conversations
- "Where did we leave off on trip planning?" → Finds last state

---

#### 3.3 Expertise Profiling
**Priority**: Low  
**Complexity**: Medium

Build a profile of user's knowledge areas and adjust responses accordingly.

**Implementation**:
- Track topics discussed at depth
- Measure complexity of user's statements per topic
- Build expertise levels: novice, intermediate, expert
- Adjust explanation depth based on detected expertise

**Schema**:
```cypher
(expertise:Expertise {
  topic: string,
  level: string,              // "novice", "intermediate", "expert"
  evidence_count: int,
  confidence: float,
  last_assessed: datetime
})

(u:User)-[:HAS_EXPERTISE]->(expertise:Expertise)
```

**Use Cases**:
- User has expertise in "Python" → Skip basic explanations
- User is novice in "cooking" → Provide more detailed instructions
- "What am I an expert in?" → Lists detected expertise areas

---

### Phase 4: Group/Social Features

#### 4.1 Shared Knowledge Graph
**Priority**: Medium  
**Complexity**: Medium

Build collective memory for group chats.

**Implementation**:
- Extend entity nodes with `group_id` scope
- Track group consensus vs individual opinions
- Add tool: `get_group_knowledge(group_id, topic)`

**Schema**:
```cypher
(gk:GroupKnowledge {
  group_id: uuid,
  topic: string,
  consensus: string,          // null if no consensus
  opinions: [{user_id, opinion, timestamp}],
  decided_at: datetime
})
```

**Use Cases**:
- "What has the group decided about the trip?"
- "Does everyone agree on the restaurant?"
- "What are the different opinions on X?"

---

#### 4.2 Interest Overlap Detection
**Priority**: Low  
**Complexity**: Low

Find common ground between users in groups.

**Implementation**:
- Compare user interest graphs
- Compute overlap scores
- Surface shared interests in group context

**Query**:
```cypher
MATCH (u1:User {id: $user1})-[:INTERESTED_IN]->(t:Topic)<-[:INTERESTED_IN]-(u2:User {id: $user2})
RETURN t.name, 
       u1.interest_strength + u2.interest_strength as combined_strength
ORDER BY combined_strength DESC
```

**Use Cases**:
- "What do Rachel and I both like?"
- "Find common interests in this group"
- Conversation starters based on shared interests

---

### Phase 5: Advanced Reasoning

#### 5.1 Multi-hop Inference
**Priority**: Medium  
**Complexity**: High

Enable reasoning across multiple graph relationships.

**Implementation**:
- Build inference rules based on relationship types
- Use graph traversal for multi-step reasoning
- Cache common inference paths

**Examples**:
```
Rule: (Pet)-[:LIKES]->(Food) AND (Food)-[:IS_A]->(FoodCategory) 
      => (Pet)-[:LIKES]->(FoodCategory)

Application:
- "Roxanne likes carrots" + "Carrots are vegetables"
- => "Roxanne likes vegetables"
- => Can suggest other vegetables as treats
```

**Use Cases**:
- "What healthy snacks would Roxanne like?" → Infers from food preferences
- "Who might know about X?" → Traverses social + expertise graphs

---

#### 5.2 Preference Aggregation
**Priority**: Medium  
**Complexity**: Medium

Build comprehensive preference profiles from scattered mentions.

**Implementation**:
- Collect preference signals from conversations
- Aggregate by category (food, activities, communication style)
- Weight by recency and explicitness
- Expose via tool: `get_user_preferences(category?)`

**Schema**:
```cypher
(pref:AggregatedPreference {
  category: string,           // "food", "activities", "schedule"
  subcategory: string,
  preferences: [
    {item: string, sentiment: float, mentions: int, last_mentioned: datetime}
  ]
})
```

**Use Cases**:
- "What are my food preferences?" → Comprehensive list
- "Schedule a dinner I'd enjoy" → Uses food + schedule + social preferences
- "What activities do I avoid?" → Negative preferences

---

## Implementation Roadmap

### Milestone 1: Entity Foundation (2-3 weeks)
- [ ] Social Graph (1.1) - Person nodes and relationships
- [ ] Pet Registry (1.2) - Structured pet storage
- [ ] Entity Linking (1.4) - Basic alias resolution

### Milestone 2: Temporal Features (2 weeks)
- [ ] Memory Timeline (2.1) - Time-based queries
- [ ] Contradiction Detection (2.4) - Basic fact checking

### Milestone 3: Proactive Intelligence (2-3 weeks)
- [ ] Contextual Suggestions (3.1) - Graph-based context
- [ ] Cross-Conversation Threading (3.2) - Topic continuity

### Milestone 4: Location & Patterns (2 weeks)
- [ ] Location Graph (1.3) - Place tracking
- [ ] Recurring Pattern Detection (2.2) - Habit detection

### Milestone 5: Group & Advanced (3-4 weeks)
- [ ] Shared Knowledge Graph (4.1) - Group memory
- [ ] Interest Overlap (4.2) - Social features
- [ ] Multi-hop Inference (5.1) - Reasoning chains
- [ ] Preference Aggregation (5.2) - Rich profiles

### Milestone 6: Polish & Optimization (1-2 weeks)
- [ ] Expertise Profiling (3.3)
- [ ] Preference Evolution (2.3)
- [ ] Performance optimization
- [ ] UI for knowledge graph exploration

---

## Technical Considerations

### Neo4j Schema Evolution
- Use APOC procedures for schema migrations
- Version all schema changes
- Maintain backwards compatibility

### Performance
- Index frequently queried properties
- Use query caching for common patterns
- Batch entity extraction to avoid per-message overhead
- Consider read replicas for heavy query loads

### Privacy & Security
- All data scoped to user_id
- Group data only accessible to members
- Encryption for sensitive entities (PII)
- Implement data retention policies

### Testing Strategy
- Unit tests for extraction logic
- Integration tests for graph queries
- Property-based tests for inference rules
- E2E tests for tool responses

---

## Success Metrics

| Feature | Metric | Target |
|---------|--------|--------|
| Entity Linking | Accuracy of alias resolution | > 90% |
| Contextual Suggestions | User engagement with suggestions | > 30% click-through |
| Contradiction Detection | False positive rate | < 10% |
| Pattern Detection | Patterns correctly identified | > 80% precision |
| Memory Timeline | Query response time | < 500ms |
| Social Graph | Relationship accuracy | > 85% |

---

## Open Questions

1. **Entity Extraction Model**: Use existing LLM or specialized NER model?
2. **Contradiction Resolution**: Automatic or always ask user?
3. **Pattern Sensitivity**: How many occurrences before detecting a pattern?
4. **Privacy Controls**: Should users be able to "forget" specific entities?
5. **Group Permissions**: Can users hide personal entities from group context?

---

## References

- Current Neo4j adapter: `src/agent_system/adapters/outbound/graph/neo4j_adapter.py`
- Knowledge domain entities: `src/agent_system/domain/entities/knowledge.py`
- Embedding adapter: `src/agent_system/adapters/outbound/embedding/openai_adapter.py`
- Recall tools: `src/agent_system/adapters/outbound/llm/tools.py`
