# Knowledge Graph Reference

A comprehensive technical reference for how the agent system builds, queries, and uses the knowledge graph during conversations. Use this document for searching, onboarding, or making it available in-app so users can ask about how the system remembers and recalls information.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Node Types](#node-types)
3. [Relationship Types (Edges)](#relationship-types-edges)
4. [When Nodes and Edges Are Created](#when-nodes-and-edges-are-created)
5. [Message Embedding Flow](#message-embedding-flow)
6. [Entity Extraction Flow](#entity-extraction-flow)
7. [How Information Is Fetched](#how-information-is-fetched)
8. [Tools That Query the Graph](#tools-that-query-the-graph)
9. [Graph Visualization API](#graph-visualization-api)
10. [Group vs Individual Context](#group-vs-individual-context)
11. [Indexes and Performance](#indexes-and-performance)
12. [Deduplication Strategies](#deduplication-strategies)
13. [Glossary](#glossary)

---

## Architecture Overview

The knowledge graph is backed by **Neo4j** and stores:

- **Structured nodes**: People, pets, locations, topics, intents, tools, interactions
- **Unstructured embeddings**: Raw conversation messages with vector embeddings for semantic search
- **Relationships**: How entities connect to each other and to the user

The graph serves two primary purposes:

1. **Write path**: Every conversation updates the graph (embeddings, entities, intents, interactions)
2. **Read path**: Every response benefits from the graph (semantic search, entity recall, contextual suggestions)

The system supports both **individual** (1:1 agent chat) and **group** (group chat) contexts. Group messages use `GroupMessageEmbedding` nodes; individual messages use `MessageEmbedding` nodes.

The **graph visualization** exposes a single master graph that unifies `KnowledgeNode` types (user, topic, tool, interaction, suggestion) with social graph nodes (`PersonNode`, `PetNode`, `LocationNode`). Users can ask the agent "how does the knowledge graph work?" and receive answers from this reference document via the `search_internal_docs` tool.

---

## Node Types

### Neo4j Labels

| Label | Description | Key Properties | Created By |
|-------|-------------|----------------|------------|
| `KnowledgeNode` | Base label for user, intent, topic, tool, interaction nodes | `id`, `node_type`, `label`, `properties_json`, `user_id` (when applicable) | `record_interaction()` |
| `MessageEmbedding` | Individual user messages with vector embedding | `id`, `user_id`, `conversation_id`, `message_id`, `content`, `role`, `embedding`, `created_at` | `store_message_embedding()` |
| `GroupMessageEmbedding` | Group chat messages with vector embedding | `id`, `group_id`, `user_id`, `user_email`, `content`, `role`, `embedding`, `created_at` | `store_group_message_embedding()` |
| `PersonNode` | People in the user's social graph | `id`, `user_id`, `name`, `name_lower`, `aliases`, `relationship_type`, `context_notes`, `mention_count`, `last_mentioned` | `store_person()` |
| `PetNode` | Pets in the user's household | `id`, `user_id`, `name`, `name_lower`, `species`, `breed`, `personality`, `food_preferences`, `health_notes`, `mention_count` | `store_pet()` |
| `LocationNode` | Places the user frequents | `id`, `user_id`, `name`, `name_lower`, `location_type`, `address`, `city`, `associated_activities`, `mention_count` | `store_location()` |
| `PreferenceNode` | User preferences (likes/dislikes) | `id`, `user_id`, `category`, `value`, `sentiment`, `confidence`, `mention_count`, `source_conversations` | `store_preference()` |
| `ThreadNode` | Cross-conversation threads/projects | `id`, `user_id`, `name`, `description`, `status`, `conversation_ids`, `related_topics` | `store_thread()` |

### KnowledgeNode `node_type` Values

When a node has label `KnowledgeNode`, its `node_type` property determines its role:

- `user` — The user (scoped by `user_id`)
- `intent` — User intent (question, task, exploration, etc.)
- `topic` — Topics or entities discussed (used with MERGE for deduplication)
- `tool` — Tools the agent has used
- `interaction` — A recorded conversation turn (summary + conversation_id)
- `suggestion` — Proactive suggestions
- `entity` — Generic extracted entity
- `person`, `pet`, `location` — Social graph (also have dedicated labels)
- `pattern`, `thread`, `expertise`, `preference`, `contradiction` — Intelligence node types

---

## Relationship Types (Edges)

### Structural Relationships

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| `FOLLOWED_BY` | User → Interaction | User had this interaction | `(User)-[:FOLLOWED_BY]->(Interaction)` |
| `HAS_INTENT` | Interaction → Topic | Interaction expressed this intent | `(Interaction)-[:HAS_INTENT]->(Topic)` |
| `MENTIONED_IN` | Entity → Interaction | Entity was mentioned in this interaction | `(Topic)-[:MENTIONED_IN]->(Interaction)` |
| `INTERESTED_IN` | User → Topic | User is interested in this topic/entity | `(User)-[:INTERESTED_IN]->(Topic)` |
| `RELATES_TO` | Topic ↔ Topic | Co-mentioned entities | `(Topic)-[:RELATES_TO]->(Topic)` |
| `USED_TOOL` | Interaction → Tool | Tool was used in this interaction | `(Interaction)-[:USED_TOOL]->(Tool)` |
| `DISCUSSED` | User → MessageEmbedding | User discussed this message | `(User)-[:DISCUSSED]->(MessageEmbedding)` |

### Social Graph Relationships

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| `KNOWS` | User → PersonNode | User knows this person | `(User)-[:KNOWS]->(PersonNode)` |
| `OWNS` | User → PetNode | User owns/has this pet | `(User)-[:OWNS]->(PetNode)` |
| `FREQUENTS` | User → LocationNode | User frequents this location | `(User)-[:FREQUENTS]->(LocationNode)` |
| `HAS_PREFERENCE` | User → PreferenceNode | User has this preference | `(User)-[:HAS_PREFERENCE]->(PreferenceNode)` |
| `HAS_THREAD` | User → ThreadNode | User has this thread | `(User)-[:HAS_THREAD]->(ThreadNode)` |

### Entity-to-Entity Relationships

Created by `link_entities()` when the LLM extracts relationships between entities:

- `WORKS_AT` — Person works at location
- `FRIEND_OF` / `RELATED_TO` — Person knows person
- `LIVES_IN` — Person lives in location
- `OWNS` — Person owns pet (or user owns pet)
- Custom relationship names (e.g. `FRIEND_OF`, `COLLEAGUE_OF`) — sanitized and created dynamically

---

## When Nodes and Edges Are Created

### 1. Intent Analysis (Every Agent Turn)

**Where**: FSM node `AnalyzeIntent` → `UpdateKnowledge`

**Flow**:

1. User sends a message
2. LLM analyzes intent and extracts entities
3. `record_interaction()` is called with:
   - `user_id`, `conversation_id`, summary (first 200 chars of input)
   - `intents` (e.g. `["question"]`), `entities` (e.g. `["Zane", "birthday"]`), `tools_used` (e.g. `["recall_about_topic"]`)

**Nodes created**:

- `KnowledgeNode` (user) — MERGE by `user_id`
- `KnowledgeNode` (interaction) — CREATE
- `KnowledgeNode` (topic) — MERGE by label for each intent and entity
- `KnowledgeNode` (tool) — MERGE by label for each tool

**Edges created**:

- `(User)-[:FOLLOWED_BY]->(Interaction)`
- `(Interaction)-[:HAS_INTENT]->(IntentTopic)` for each intent
- `(Interaction)-[:MENTIONED_IN]->(EntityTopic)` for each entity
- `(User)-[:INTERESTED_IN]->(EntityTopic)` for each entity
- `(Entity1)-[:RELATES_TO]->(Entity2)` for co-mentioned entities
- `(Interaction)-[:USED_TOOL]->(Tool)` for each tool

### 2. Message Embedding Storage

**Where**: 
- Individual: After each message in the agent API (background task)
- Group: After each group WebSocket message (background task)

**Flow**:

1. Message content is embedded via OpenAI (or user's API key)
2. `store_message_embedding()` (individual) or `store_group_message_embedding()` (group) is called
3. A `MessageEmbedding` or `GroupMessageEmbedding` node is created with the embedding vector
4. If a user node exists: `(User)-[:DISCUSSED]->(MessageEmbedding)`

**Properties stored**: `id`, `user_id`, `conversation_id`, `message_id`, `content`, `role`, `embedding`, `metadata_json`, `created_at`

### 3. Entity Extraction (Group and Individual)

**Where**: 
- Group: WebSocket handler in `groups.py`, after message save (async, fire-and-forget)
- Individual: Same `record_interaction()` entities; no separate LLM entity extraction for 1:1 (entities come from intent agent)

**Flow (Group)**:

1. After a user message is saved, `extract_knowledge_from_text()` is called (LLM)
2. LLM returns: `persons`, `pets`, `locations`, `relationships`, `preferences`
3. For each extracted entity with confidence ≥ 0.7:
   - `store_person()`, `store_pet()`, `store_location()`, `store_preference()`
4. For each extracted relationship: `link_entities()`

**Nodes created**:

- `PersonNode` — MERGE by `user_id` + `name_lower`
- `PetNode` — MERGE by `user_id` + `name_lower`
- `LocationNode` — MERGE by `user_id` + `name_lower`
- `PreferenceNode` — MERGE by `user_id` + `category_lower` + `value_lower`

**Edges created**:

- `(User)-[:KNOWS]->(PersonNode)`
- `(User)-[:OWNS]->(PetNode)`
- `(User)-[:FREQUENTS]->(LocationNode)`
- `(User)-[:HAS_PREFERENCE]->(PreferenceNode)`
- Dynamic edges from `link_entities()` (e.g. `(PersonNode)-[:WORKS_AT]->(LocationNode)`)

---

## Message Embedding Flow

### Individual Chat

1. User sends message via API
2. Message is saved to PostgreSQL (conversation)
3. Background task:
   - Embed content via `embedding_port.embed(content)`
   - Call `knowledge_graph_port.store_message_embedding(user_id, conversation_id, message_id, content, role, embedding)`
4. Neo4j creates `MessageEmbedding` node and `(User)-[:DISCUSSED]->(MessageEmbedding)` if user exists

### Group Chat

1. User sends message via WebSocket
2. Message is saved to PostgreSQL (group conversation)
3. Background task:
   - Embed content via OpenAI
   - Call `knowledge_graph_port.store_group_message_embedding(group_id, conversation_id, message_id, user_id, user_email, content, role, embedding)`
4. Neo4j creates `GroupMessageEmbedding` node (no DISCUSSED edge; group messages are scoped by `group_id`)

### Vector Index

- Index name: `message_embeddings`
- Type: Vector index on `MessageEmbedding.embedding`
- Dimensions: 1536 (OpenAI default)
- Similarity: cosine

---

## Entity Extraction Flow

### LLM Extraction (`knowledge_extractor.py`)

The `extract_knowledge_from_text()` function uses a PydanticAI agent to extract:

- **ExtractedPerson**: `name`, `aliases`, `relationship_type`, `context_notes`, `confidence`
- **ExtractedPet**: `name`, `aliases`, `species`, `breed`, `traits`, `food_preferences`, `confidence`
- **ExtractedLocation**: `name`, `aliases`, `location_type`, `address`, `city`, `associated_activity`, `confidence`
- **ExtractedRelationship**: `source_name`, `source_type`, `target_name`, `target_type`, `relationship`, `confidence`
- **ExtractedPreference**: `category`, `subcategory`, `value`, `sentiment`, `confidence`

**Context**: The extractor receives:
- Recent conversation messages (last 10) for coreference resolution
- Existing person/pet/location names for reference resolution (e.g. "his wife" → lookup spouse)

**Threshold**: Only entities with `confidence >= 0.7` are stored.

### Coreference Resolution

The system prompt instructs the LLM to resolve references like:
- "his wife" → look for who "his" refers to
- "the dog" → match to known pet
- "that restaurant" → match to known location

---

## How Information Is Fetched

### 1. Semantic Search

**Method**: `semantic_search(user_id, query_embedding, limit=10, min_score=0.5)`

**Flow**:
1. Query is embedded
2. Neo4j vector index `message_embeddings` is queried
3. Returns `MessageEmbedding` nodes where `user_id` matches and `score >= min_score`
4. Results sorted by score descending

**Used in**:
- `GenerateResponse` node: retrieve semantically similar past messages for context (limit=25, min_score=0.7)
- `recall_about_topic` tool: primary source when embedding port is available

**Fallback**: If vector index fails, `_brute_force_semantic_search()` computes cosine similarity in Python.

### 2. Keyword Recall (`recall_about_topic`)

**Method**: `recall_about_topic(user_id, topic, limit=5)`

**Flow**:
1. Search `MessageEmbedding` where `content CONTAINS topic` (case-insensitive)
2. Search `KnowledgeNode` where `label CONTAINS topic`
3. Prioritize: (a) user messages over assistant, (b) nodes with defining keywords (dog, pet, spouse, "is my", etc.)
4. Deduplicate and return combined results

**Used in**:
- `recall_about_topic` tool (combined with semantic search)
- `CreatePlan` node: entity context injection before planning (e.g. "Zane is the user's dog")

### 3. Contextual Suggestions

**Method**: `get_contextual_suggestions(user_id, mentioned_entities, limit=5)`

**Flow**:
1. Extract capitalized words from user input as potential entity names
2. Match against `PersonNode`, `PetNode`, `LocationNode` (by name or alias)
3. Traverse graph 1–2 hops from matched entities to find related nodes
4. Score by connection strength and recency (`last_mentioned`)
5. Return related entities with relevance scores

**Used in**: `GenerateResponse` node — inject related context (e.g. when user mentions "Zane", suggest "Bo" if they're related)

### 4. Typed Entity Lookup

**Methods**:
- `get_person(user_id, name)` — exact match on `PersonNode`
- `get_pet(user_id, name)` — exact match on `PetNode`
- `get_location(user_id, name)` — exact match on `LocationNode`
- `find_person_by_alias(user_id, alias)` — match by alias or name
- `resolve_entity_by_alias(user_id, alias)` — search Person, Pet, Location
- `list_known_people(user_id, relationship_type?)` — list all PersonNodes
- `list_pets(user_id, species?)` — list all PetNodes
- `list_locations(user_id, location_type?, city?)` — list all LocationNodes

**Used in**: Tools `get_person_info`, `get_pet_info`, `get_location_info`, `list_known_people`, `list_pets`, `list_locations`

### 5. Entity Relationships

**Method**: `get_entity_relationships(user_id, entity_type, entity_name, max_depth=2)`

**Flow**: Traverse graph from the entity node up to `max_depth` hops, return related nodes and relationship path.

**Used in**: `get_person_info` tool — show "Related: Person → WORKS_AT → Location"

### 6. Temporal Recall

**Method**: `recall_from_period(user_id, start_date, end_date, topic?, limit=20)`

**Flow**: Query `MessageEmbedding` where `created_at` is in range, optionally filter by `content CONTAINS topic`.

**Used in**: `recall_from_period` tool

### 7. Preferences

**Method**: `get_user_preferences(user_id, category?, min_confidence?)`

**Flow**: Query `PreferenceNode` where `user_id` matches, optionally filter by category and confidence.

**Used in**: `get_user_preferences` tool

### 8. Thread History

**Method**: `get_thread_history(user_id, thread_name)`

**Flow**: Query `ThreadNode` by `user_id` and `name_lower`, return thread with `conversation_ids`, `related_topics`, etc.

**Used in**: `get_thread_history` tool

### 9. Group Consensus

**Method**: `get_group_consensus(group_id, topic)`

**Flow**: Query `GroupMessageEmbedding` where `group_id` matches and `content CONTAINS topic`, return mentions with user and timestamp.

**Used in**: `get_group_consensus` tool

---

## Tools That Query the Graph

| Tool | Graph Methods Used | Purpose |
|------|--------------------|---------|
| `summarize_user_knowledge` | `get_user_nodes()` | Summarize topics, interactions, tools used |
| `recall_about_topic` | `semantic_search()`, `recall_about_topic()`, `get_user_nodes()` | Recall what's known about a topic/person/pet |
| `recall_group_topic` | `group_semantic_search()`, `get_group_knowledge()` | Recall group discussions about a topic |
| `get_person_info` | `get_person()`, `find_person_by_alias()`, `get_entity_relationships()` | Get full profile of a person |
| `get_pet_info` | `get_pet()` | Get full profile of a pet |
| `get_location_info` | `get_location()` | Get full profile of a location |
| `list_known_people` | `list_known_people()` | List people in social graph |
| `list_pets` | `list_pets()` | List pets |
| `list_locations` | `list_locations()` | List locations |
| `get_user_preferences` | `get_user_preferences()` | Get learned preferences |
| `recall_from_period` | `recall_from_period()` | Recall messages from a date range |
| `get_thread_history` | `get_thread_history()` | Get cross-conversation thread |
| `get_group_consensus` | `get_group_consensus()` | Get group consensus on a topic |
| `search_internal_docs` | Bundled markdown search | Answer "how does X work?" using this reference |

---

## Graph Visualization API

**Endpoint**: `GET /knowledge/graph`

Returns the full knowledge graph for the current user as a single unified graph suitable for visualization. All node types are combined into one response.

### Node Types Returned

| Type | Source | Color (UI) |
|------|--------|------------|
| `user` | KnowledgeNode | Blue |
| `interaction` | KnowledgeNode | Green |
| `topic` | KnowledgeNode | Amber |
| `tool` | KnowledgeNode | Purple |
| `suggestion` | KnowledgeNode | Pink |
| `person` | PersonNode | Cyan |
| `pet` | PetNode | Lime |
| `location` | LocationNode | Orange |

### Response Shape

- **nodes**: List of `{id, label, fullLabel, type, color, properties}` — includes both KnowledgeNodes and PersonNode/PetNode/LocationNode
- **links**: List of `{source, target, type, label}` — structural edges (FOLLOWED_BY, HAS_INTENT, etc.) plus social edges (KNOWS, OWNS, FREQUENTS) and entity-to-entity edges from `link_entities()`
- **stats**: `{total_nodes, total_links, node_types: {type: count}}`

### Data Sources

- KnowledgeNodes: `get_user_nodes(user_id, node_type=None)` — traverses 1–3 hops from the user node
- Social graph: `list_known_people()`, `list_pets()`, `list_locations()` — PersonNode, PetNode, LocationNode for the user
- Relationships: `get_relationships(node_id)` for each node — includes KNOWS, OWNS, FREQUENTS from User to social nodes

**Implementation**: `src/agent_system/adapters/inbound/api/routes/knowledge.py`

---

## Group vs Individual Context

| Aspect | Individual | Group |
|--------|------------|-------|
| Message storage | `MessageEmbedding` + `user_id` | `GroupMessageEmbedding` + `group_id` |
| Semantic search | `semantic_search(user_id, ...)` | `group_semantic_search(group_id, ...)` |
| Entity extraction | Via intent agent entities only | Full LLM extraction (persons, pets, locations, preferences) |
| Entity storage | Shared (PersonNode, PetNode, LocationNode are per-user) | Same nodes; group messages can mention same user's entities |
| Recall tools | `recall_about_topic` (user-scoped) | `recall_group_topic`, `get_group_consensus` |

---

## Indexes and Performance

### Vector Index

- **Name**: `message_embeddings`
- **Label**: `MessageEmbedding`
- **Property**: `embedding`
- **Dimensions**: 1536
- **Similarity**: cosine

### Temporal Indexes

- `MessageEmbedding.created_at`
- `GroupMessageEmbedding.created_at`
- `PersonNode.last_mentioned`
- `PetNode.last_mentioned`
- `LocationNode.last_mentioned`

Ensured by `ensure_temporal_index()` on adapter initialization (best-effort).

---

## Deduplication Strategies

### MERGE by Label + Key

- **User**: `MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})`
- **Topic/Entity**: `MERGE (e:KnowledgeNode {node_type: 'topic', label: $label})` — same topic string = same node across conversations
- **Tool**: `MERGE (t:KnowledgeNode {node_type: 'tool', label: $label})`
- **PersonNode**: `MERGE (p:PersonNode {user_id: $user_id, name_lower: toLower($name)})`
- **PetNode**: `MERGE (p:PetNode {user_id: $user_id, name_lower: toLower($name)})`
- **LocationNode**: `MERGE (l:LocationNode {user_id: $user_id, name_lower: toLower($name)})`
- **PreferenceNode**: `MERGE (p:PreferenceNode {user_id: $user_id, category_lower: toLower($category), value_lower: toLower($value)})`

### Relationship MERGE

- `_create_relationship_by_id()` uses `MERGE (a)-[r:REL_TYPE]->(b)` to avoid duplicate edges

---

## Glossary

| Term | Definition |
|------|------------|
| **Knowledge graph** | Neo4j-backed graph storing entities, messages, and relationships |
| **Node** | A vertex in the graph (e.g. User, Person, MessageEmbedding) |
| **Edge / Relationship** | A directed connection between two nodes (e.g. KNOWS, DISCUSSED) |
| **Message embedding** | Vector representation of a message for semantic search |
| **Entity extraction** | LLM process that identifies people, pets, locations, preferences from text |
| **Semantic search** | Vector similarity search over message embeddings |
| **Keyword recall** | Text containment search (CONTAINS) over message content and node labels |
| **Contextual suggestions** | Related entities discovered by traversing the graph from mentioned entities |
| **MERGE** | Cypher operation that creates a node if it doesn't exist, or matches it if it does |
| **Intent** | LLM-classified user intent (question, task, exploration, etc.) |
| **Interaction** | A single recorded turn (summary + conversation_id) in the graph |

---

## File References

- **Neo4j adapter**: `src/agent_system/adapters/outbound/graph/neo4j_adapter.py`
- **Knowledge value objects**: `src/agent_system/domain/value_objects/knowledge.py`
- **Knowledge entities**: `src/agent_system/domain/entities/knowledge.py`
- **Entity extractor**: `src/agent_system/adapters/outbound/llm/knowledge_extractor.py`
- **Tools**: `src/agent_system/adapters/outbound/llm/tools.py`
- **Internal docs search**: `src/agent_system/docs/internal_docs.py` (bundled with package)
- **FSM nodes**: `src/agent_system/adapters/outbound/fsm/nodes.py`
- **Knowledge graph API**: `src/agent_system/adapters/inbound/api/routes/knowledge.py`
- **Group routes / WebSocket**: `src/agent_system/adapters/inbound/api/routes/groups.py`
