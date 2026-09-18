# Agent System

A production-ready agentic AI platform built with **Hexagonal Architecture**, featuring multi-agent reasoning, real-time collaboration, and knowledge graph integration.

## Overview

Agent System is an intelligent conversational platform that combines:
- **Multi-Agent Architecture**: Specialized AI agents for intent analysis, planning, and response generation
- **Real-Time Collaboration**: Group chat with WebSocket support and AI assistance
- **Knowledge Management**: Neo4j-backed knowledge graph for context and memory
- **Modern Frontend**: React TypeScript UI with dark mode and real-time updates

## Architecture

The system follows **Hexagonal Architecture** (Ports & Adapters) for clean separation of concerns:

![System Architecture](docs/images/architecture-diagram.png)

### Project Structure

```
src/agent_system/
├── domain/                    # Core business logic (framework-free)
│   ├── entities/              # User, Conversation, Plan, Group, KnowledgeNode
│   ├── value_objects/         # Identifiers, Messages, Plans, Knowledge
│   ├── ports/                 # Repository, LLM, KnowledgeGraph interfaces
│   ├── services/              # Domain services
│   └── events/                # Domain events
├── application/               # Use cases and orchestration
│   ├── services/              # Application services
│   └── dtos/                  # Data transfer objects
├── adapters/
│   ├── inbound/api/           # FastAPI REST + WebSocket endpoints
│   └── outbound/
│       ├── persistence/       # SQLAlchemy repositories
│       ├── llm/               # PydanticAI agents + tools
│       ├── graph/             # Neo4j knowledge graph adapter
│       ├── embedding/         # OpenAI embeddings adapter
│       └── fsm/               # pydantic-graph workflow engine
└── composition_root/          # Dependency injection, config

frontend/
├── src/
│   ├── components/            # React components
│   │   ├── auth/              # Login, registration
│   │   ├── chat/              # Chat interface
│   │   ├── groups/            # Group collaboration
│   │   ├── knowledge/         # Knowledge graph visualization
│   │   ├── settings/          # User settings, API keys
│   │   └── trace/             # FSM workflow trace
│   ├── stores/                # Zustand state management
│   ├── hooks/                 # Custom React hooks
│   └── lib/                   # API client, utilities
```

## Features

### AI Agent System

The platform uses specialized agents powered by **PydanticAI** with structured outputs:

![AI Agent Pipeline](docs/images/agent-pipeline.png)

| Agent | Purpose |
|-------|---------|
| **Intent Agent** | Analyzes user intent, extracts entities, determines tool requirements |
| **ReAct Planning Agent** | Creates reasoning-step plans for complex tasks with visible thought process |
| **Step Execution Agent** | Executes individual reasoning steps with Thought → Action → Observation pattern |
| **Synthesis Agent** | Weaves step results into comprehensive, natural responses |
| **Coordinator Agent** | Generates comprehensive responses using context and tool results |
| **Knowledge Agent** | Extracts facts, topics, and user preferences for learning |

### FSM Workflow Engine

Every conversation flows through a state machine for consistent, traceable processing:

![FSM Workflow](docs/images/fsm-workflow.png)

**Key States:**
- **ReceiveInput** → Captures user message
- **AnalyzeIntent** → Extracts intent, entities, and tool needs
- **UpdateKnowledge** → Records interaction in knowledge graph
- **CheckPlan** → Routes to planning, tool execution, or response (enables ReAct mode for tasks)
- **CreatePlan** → Creates reasoning steps (uses ReAct Planning Agent when `requires_planning` is set or the intent is a task)
- **ExecutePlan** → Iterates through steps with visible reasoning trace (ReAct mode)
- **SelectTool / ExecuteTool** → Tool invocation and result capture
- **GenerateResponse** → Final response synthesis (uses Synthesis Agent in ReAct mode)
- **FinalizeKnowledge** → Stores embeddings and suggestions

### ReAct Reasoning Mode

For complex questions and tasks, the system uses **ReAct (Reasoning + Acting)** — a step-by-step reasoning approach that shows its thinking process:

![ReAct Workflow](docs/images/react-workflow.png)

**How It Works:**

**What triggers it:** `AnalyzeIntent` sets `requires_planning` for open-ended how-to,
troubleshooting, design, and decision-making questions — anything whose answer has several
phases that build on each other. `CheckPlan` then enters ReAct mode (task intents always do).
Simple lookups, clarifications, and chit-chat skip it, and so does anything a tool can answer:
reasoning mode bypasses the tool `AnalyzeIntent` picked, so the two are mutually exclusive.
Run `uv run scripts/test_planning_trigger.py` to check the trigger after changing the prompt.

When you ask a question that qualifies (e.g., "How do I make sourdough starter?"), the system:

1. **Creates a Reasoning Plan** (3-6 steps)
   - Breaks down the question into logical reasoning phases
   - Each step is a distinct aspect of the problem to explore

2. **Executes Each Step with Visible Reasoning**
   - **Thought**: What the agent is considering for this step
   - **Action**: `think` (use knowledge), `search` (needs tool), or `recall` (from context)
   - **Observation**: The conclusion or insight from executing the step

3. **Synthesizes into Final Response**
   - The Synthesis Agent weaves all step insights into a comprehensive, natural response
   - Key insights are extracted and follow-up suggestions generated

**Example ReAct Trace:**

```
Question: "How do I make a sourdough starter?"

Step 1/5: Understand the fundamentals of sourdough fermentation
  Thought: Sourdough relies on wild yeast and lactobacillus bacteria...
  Action: think
  Observation: Sourdough starter is a fermented mixture of flour and water 
               that captures wild yeast from the environment...

Step 2/5: Identify required ingredients and equipment
  Thought: The beauty of sourdough is its simplicity...
  Action: think
  Observation: You need only flour (whole wheat or rye recommended for 
               starting), filtered water, and a glass jar...

Step 3/5: Work through the day-by-day process
  Thought: The process takes about 7-14 days...
  Action: think
  Observation: Day 1: Mix 50g flour with 50g water... Day 2: Discard half...

[... continues through all steps ...]

→ Synthesized Response: [400+ word comprehensive guide]
```

**Benefits of ReAct:**
- **Transparency**: See exactly how the agent reasons through complex questions
- **Thoroughness**: Ensures all aspects of a question are considered
- **Quality**: Step-by-step reasoning produces more accurate, detailed responses
- **Debuggability**: Easy to see where reasoning might go wrong

**Event Types in Workflow Trace:**
| Event | Description |
|-------|-------------|
| `react_plan` | Shows the reasoning approach and planned steps |
| `react_step_start` | Beginning of each reasoning step |
| `react_step_complete` | Shows thought, action, and observation for a step |
| `react_synthesis_start` | Beginning of final response synthesis |
| `react_synthesis_complete` | Synthesis finished with key insights |

### Built-in Tools

#### Core Tools

| Tool | Trigger Keywords | Description |
|------|------------------|-------------|
| `web_search` | "search", "look up", "find online" | Search the web via DuckDuckGo (with context-aware location injection) |
| `calculate` | "calculate", numbers in message | Evaluate math expressions |
| `define_word` | "define", "meaning of" | Look up word definitions |
| `get_current_datetime` | "time", "date", "today" | Get current date/time (in user's timezone) |
| `get_upcoming_events` | "plans", "schedule", "events" | View extracted events from group chats |
| `random_fact` | "interesting", "fun fact" | Get a random fact |
| `add_to_calendar` | "put it on my calendar", "add those as tentative" | Create one or many Google Calendar events, optionally tentative |

#### Knowledge & Memory Tools

| Tool | Trigger Keywords | Description |
|------|------------------|-------------|
| `summarize_user_knowledge` | "what do you know about me" | Summarize all knowledge about the user |
| `recall_about_topic` | "tell me about X", "what about X" | Recall specific topics from past conversations |
| `recall_group_topic` | "what has the group discussed about X" | Search group conversation history |
| `get_user_profile` | "my profile", "my preferences" | View stored preferences |
| `get_conversation_history` | "my conversations", "past chats" | View conversation history |
| `analyze_conversation_patterns` | "analyze", "patterns", "statistics" | Get usage analytics |
| `recall_from_period` | "last week", "in January", "yesterday" | Retrieve messages from a specific time period |
| `get_thread_history` | "about my project", "renovation progress" | Get cross-conversation thread history |

#### Social Graph Tools

| Tool | Trigger Keywords | Description |
|------|------------------|-------------|
| `get_person_info` | "about [name]", "who is [name]" | Get information about a person in your social graph |
| `get_pet_info` | "my dog", "about [pet name]" | Get information about your pets |
| `get_location_info` | "about [place]", "that restaurant" | Get details about a saved location |
| `list_known_people` | "people I know", "who have I mentioned" | List all people you've told the system about |
| `list_pets` | "my pets", "animals I have" | List all your pets |
| `list_locations` | "places I've mentioned", "saved locations" | List all tracked locations |
| `get_user_preferences` | "my preferences", "what I like" | Get your stored preferences by category |

#### Group Intelligence Tools

| Tool | Trigger Keywords | Description |
|------|------------------|-------------|
| `get_shared_interests` | "what do we have in common" | Find topics shared across group members |
| `get_group_consensus` | "what does the group think about X" | Analyze group sentiment on a topic |

**Context-Aware Features:**
- **Pronoun resolution**: "What about his interests?" → automatically resolves "his" to the entity being discussed (e.g., "Zane")
- **Location context**: Searches automatically include location context from conversation (e.g., "Houston") 
- **Entity resolution**: "The brewery" → resolves to "Under the Radar Brewery" from recent context

### Group Collaboration

Real-time group chat with AI assistance:

![Group Collaboration](docs/images/group-collaboration.png)

**Features:**
- Real-time messaging with WebSocket
- AI agent assistance (mention `@agent`)
- Automatic event extraction (meetings, deadlines, activities)
- Member management with owner-only controls
- Privacy controls per member

### Knowledge Graph

Optional Neo4j integration for persistent memory and context:

![Knowledge Graph](docs/images/knowledge-graph.png)

**Capabilities:**
- **Semantic search** using vector embeddings (OpenAI text-embedding-3-small)
- **Context recall** across all conversations (not just current session)
- **Topic relationships** — entities mentioned together are automatically linked
- **User interest tracking** — builds a profile of topics you've discussed
- **Single-node topics** — same topic across conversations becomes one connected node
- **Rich relationship types** — RELATES_TO, INTERESTED_IN, DISCUSSED, LIKES, LOCATED_IN, etc.
- **Interactive visualization** — force-directed graph in frontend with filtering

### Wrestler Themes

The header **Theme** picker dresses the whole app as Macho Man Randy Savage, Hulk Hogan, Bret "The Hitman" Hart, "Mean" Gene Okerlund or The Ultimate Warrior: palette, headshot avatar, welcome copy, and the agent answers **in that wrestler's voice** (persona rules are appended to the response agents' system prompts; substance is unchanged). The choice belongs to the conversation: `Conversation.persona` lives in `metadata.custom_data`, opening a conversation switches the app back to the wrestler it was spoken in, picking one mid-conversation saves it immediately, and themed conversations show the headshot in the sidebar. `PATCH /conversations/{id}` accepts `persona` (`"none"` clears it, unknown keys 422), and list and detail responses expose it. Headshots are CC-licensed crops from Wikimedia Commons (`frontend/public/themes/ATTRIBUTION.md`).

### Deep Research

The **Research** tab runs a durable, multi-lane research job from a plain question and produces an alphaXiv-style overview you can read or listen to.

- **Three lanes in parallel.** *Academic* searches arXiv and Semantic Scholar; *Practical* searches the web and GitHub and reads the pages; *Empirical* mines both for reported numbers and extracts them into data tables with the quoted source span kept for provenance. A lane failing degrades the report instead of killing the run.
- **Synthesis, figures, write-up.** The lanes are reconciled into one section plan, the best tables are charted server-side with matplotlib, and the overview is written in an explanatory academic register with numbered citations and inline figures.
- **Narration.** After the report is saved, an OpenAI text-to-speech narration (default voice `marin`) is generated and a **Listen** button appears.
- **Depth.** *Quick* is one pass per lane. *Standard* and *Deep* add one or two recursive rounds: each lane summarises what it has, names the gaps, plans gap-driven queries, searches again and extracts more findings; the round summaries feed the synthesis.
- **Figures from the papers.** The most-cited arXiv sources are downloaded and their best figures (matched to the paper's own captions with PyMuPDF) are placed in the report with a link back to the paper, alongside charts drawn from extracted numbers.
- **Durable jobs.** Each run is a `research_jobs` row executed by an in-process background task. Every progress event is persisted, so reloading or switching tabs re-attaches and replays. A backend restart marks in-flight runs `interrupted`; figures and audio live in Postgres.

Endpoints: `POST /api/v1/research`, `GET /api/v1/research`, `GET /api/v1/research/{id}`, `GET /api/v1/research/{id}/stream` (SSE, `?token=`), `GET /api/v1/research/{id}/figures/{n}`, `GET /api/v1/research/{id}/audio`, `POST /api/v1/research/{id}/narrate`, `DELETE /api/v1/research/{id}`.

Settings: `DEFAULT_MODEL` (lanes, synthesis, writing), `FALLBACK_MODEL` (query planning), `TTS_MODEL`, `TTS_VOICE`, and optional `SEMANTIC_SCHOLAR_API_KEY` / `GITHUB_TOKEN` for higher rate limits. All agents use the OpenAI Responses API, which the GPT-5.6 and GPT-6 models require for tool use.

### Calendar

Google Calendar is connected per user from the user menu, and drives two different paths.

- **Sync.** Events the agent extracts from group chats are pushed to the user's calendar. Each member syncs independently, with a master toggle, a calendar selector, and a confirmed-only option. Events carry a sync status, and a failed one can be retried by hand.
- **The `add_to_calendar` tool.** The agent creates events directly on request, one or many in a single message. `status="tentative"` creates them unconfirmed. A title matching the Houston events database picks up that event's real date, venue and link; otherwise `when` is parsed in the user's timezone. In a multi-event list an undated item becomes an all-day placeholder on the coming Saturday, while a single undated event gets a question instead of a guess.

Endpoints: `GET /api/v1/calendar/status`, `POST /api/v1/calendar/connect`, `POST /api/v1/calendar/disconnect`, `PATCH /api/v1/calendar/settings`, `GET /api/v1/calendar/list`.

### Installable App

The frontend ships a web app manifest (`frontend/public/manifest.webmanifest`) with maskable icons, so it installs to a phone home screen and launches standalone in portrait, without browser chrome. On iOS that is Safari's **Share > Add to Home Screen**; the layout accounts for the standalone viewport and safe areas. On wide screens the reading columns scale with the viewport rather than staying fixed.

## Memory & Context Architecture

The Agent System uses a **multi-layer memory architecture** to maintain conversational context, learn user preferences, and enable intelligent recall across sessions. This section explains how PostgreSQL, Neo4j, and vector embeddings work together.

### Overview

![Memory Architecture](docs/images/memory-architecture.png)

**How They Work Together:**

1. **PostgreSQL** stores the authoritative record of all messages, conversations, users, and groups
2. **Neo4j** maintains a semantic graph of extracted knowledge (facts, topics, preferences, relationships)
3. **Vector Embeddings** enable similarity search to find relevant past context

When processing a user message, the system:
1. Loads recent messages from PostgreSQL (immediate context)
2. Queries Neo4j for relevant facts and user preferences (learned context)
3. Performs vector similarity search to find related past discussions (semantic context)
4. Assembles all context for the AI agents to generate informed responses

---

### PostgreSQL: Structured Data Storage

PostgreSQL (or SQLite for local development) serves as the **primary database** for all structured data.

#### What It Stores

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `users` | User accounts | email, hashed_password, encrypted_openai_api_key |
| `conversations` | Chat sessions | user_id, title, active_plan_id, metadata |
| `messages` | All chat messages | conversation_id, role, content, tool_calls |
| `plans` | Multi-step task plans | goal_description, steps, status |
| `groups` | Collaboration groups | name, description, owner_id |
| `group_conversations` | Group chat sessions | group_id, title |
| `group_messages` | Messages in groups | conversation_id, user_id, content |
| `extracted_events` | Events from group chats | group_id, title, event_datetime, confidence |

#### How It Helps Context

```python
# When loading a conversation, recent messages provide immediate context
conversation = await conv_repo.get(conversation_id)
recent_messages = conversation.messages[-20:]  # Last 20 messages

# This context is passed to the AI agents
state = WorkflowState(
    user=user,
    conversation=conversation,  # Includes message history
    current_plan=active_plan,
)
```

**Benefits:**
- ✅ Fast, indexed lookups for recent messages
- ✅ ACID compliance for data integrity
- ✅ Efficient storage of structured metadata
- ✅ Supports complex queries (e.g., "all conversations mentioning X")

---

### Neo4j Knowledge Graph: Semantic Memory

Neo4j stores **extracted knowledge** as a graph of interconnected nodes and relationships. The graph is designed to be **interconnected** — topics mentioned across different conversations link together, and entities mentioned together in the same message form relationships.

#### Node Types

**Core Nodes:**

| Node Type | Label | Purpose | Example |
|-----------|-------|---------|---------|
| **User** | `KnowledgeNode` (node_type: 'user') | Anchors all user-specific knowledge | The logged-in user |
| **Topic** | `KnowledgeNode` (node_type: 'topic') | Entities, subjects, people, places | "Zane", "Houston", "Python" |
| **Interaction** | `KnowledgeNode` (node_type: 'interaction') | Conversation turn summary | "Asked about restaurants" |
| **Tool** | `KnowledgeNode` (node_type: 'tool') | Tools that were used | "web_search", "calculate" |
| **MessageEmbedding** | `MessageEmbedding` | Vector-embedded messages for semantic search | Stored user/assistant messages |
| **Group** | `KnowledgeNode` (node_type: 'group') | Group conversation anchor | "Cycling Group" |

**Social Graph Nodes (New):**

| Node Type | Label | Purpose | Key Properties |
|-----------|-------|---------|----------------|
| **Person** | `PersonNode` | People in your social graph | name, relationship_type, aliases, context_notes |
| **Pet** | `PetNode` | Your pets | name, species, breed, personality, food_preferences |
| **Location** | `LocationNode` | Places you mention | name, location_type, city, activities |
| **Preference** | `PreferenceNode` | Your likes/dislikes | category, value, sentiment, confidence |

**Intelligence Nodes (New):**

| Node Type | Label | Purpose | Key Properties |
|-----------|-------|---------|----------------|
| **Pattern** | `PatternNode` | Detected behavioral patterns | pattern_type, frequency, confidence, next_expected |
| **Thread** | `ThreadNode` | Cross-conversation topics | name, description, related_conversations |
| **Expertise** | `ExpertiseNode` | User skill levels | topic, level (novice→expert), evidence_count |
| **Contradiction** | `ContradictionNode` | Conflicting information | old_value, new_value, severity, resolved |

#### Relationship Types

The system uses meaningful relationships to create a rich, traversable graph:

**Core Relationships:**

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| **FOLLOWED_BY** | User → Interaction | User had this interaction | `(User)-[:FOLLOWED_BY]->(Interaction)` |
| **INTERESTED_IN** | User → Topic | User has discussed this topic | `(User)-[:INTERESTED_IN]->(Zane)` |
| **DISCUSSED** | User → MessageEmbedding | User's conversation messages | `(User)-[:DISCUSSED]->(Message)` |
| **MENTIONED_IN** | Interaction → Topic | Topic appeared in this interaction | `(Interaction)-[:MENTIONED_IN]->(Houston)` |
| **RELATES_TO** | Topic ↔ Topic | Topics co-mentioned together | `(Zane)-[:RELATES_TO]->(ham bones)` |
| **HAS_INTENT** | Interaction → Topic | Intent extracted from message | `(Interaction)-[:HAS_INTENT]->(question)` |
| **USED_TOOL** | Interaction → Tool | Tool was invoked | `(Interaction)-[:USED_TOOL]->(web_search)` |
| **SIMILAR_TO** | Topic ↔ Topic | Semantically related topics | `(Python)-[:SIMILAR_TO]->(Programming)` |

**Social Graph Relationships (New):**

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| **KNOWS** | User → Person | User knows this person | `(User)-[:KNOWS]->(Rachel)` |
| **OWNS** | User → Pet | User owns this pet | `(User)-[:OWNS]->(Zane)` |
| **FREQUENTS** | Person → Location | Person visits this location | `(Sarah)-[:FREQUENTS]->(Uchi)` |
| **WORKS_AT** | Person → Location | Person works at this place | `(Jake)-[:WORKS_AT]->(Acme Corp)` |
| **LIVES_IN** | Person → Location | Person lives here | `(Rachel)-[:LIVES_IN]->(Austin)` |
| **LOCATED_IN** | Location → Location | Location is within another | `(Uchi)-[:LOCATED_IN]->(Houston)` |

**Preference & Pattern Relationships (New):**

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| **LIKES** | Entity → Object | Positive preference | `(Sarah)-[:LIKES]->(omakase)` |
| **DISLIKES** | Entity → Object | Negative preference | `(User)-[:DISLIKES]->(cilantro)` |
| **HAS_PREFERENCE** | User → Preference | User has this preference | `(User)-[:HAS_PREFERENCE]->(sushi_preference)` |
| **HAS_PATTERN** | User → Pattern | User exhibits this behavior | `(User)-[:HAS_PATTERN]->(daily_weather_check)` |
| **HAS_EXPERTISE** | User → Expertise | User's skill level in topic | `(User)-[:HAS_EXPERTISE]->(Python: intermediate)` |

**Threading & Grouping (New):**

| Relationship | Direction | Meaning | Example |
|--------------|-----------|---------|---------|
| **PART_OF_THREAD** | Message → Thread | Message belongs to topic thread | `(Msg)-[:PART_OF_THREAD]->(kitchen_renovation)` |
| **MEMBER_OF** | User → Group | User is in this group | `(User)-[:MEMBER_OF]->(Cycling Club)` |
| **SHARES_INTEREST** | User ↔ User | Users share common interests | `(Alice)-[:SHARES_INTEREST]->(Bob)` |

#### Key Design Principles

**1. Single Node Per Topic (MERGE Strategy)**

Topics are stored using `MERGE` rather than `CREATE`, meaning the same topic mentioned across different conversations becomes a **single node** with multiple connections:

```cypher
// When user mentions "Zane" in multiple conversations, 
// it's always the same node
MERGE (t:KnowledgeNode {node_type: 'topic', label: 'Zane'})
ON CREATE SET t.id = $id, t.created_at = $now
ON MATCH SET t.updated_at = $now
```

This enables powerful queries like "Show me everything related to Zane" that span all conversations.

**2. Co-Mentioned Entities Are Related**

When multiple entities are mentioned in the same message, they're automatically linked with `RELATES_TO` relationships:

```
User says: "Zane loves eating ham bones"
                    │
                    ▼
         Extracted entities: ["Zane", "ham bones"]
                    │
                    ▼
         Creates:
         • (User)-[:INTERESTED_IN]->(Zane)
         • (User)-[:INTERESTED_IN]->(ham bones)
         • (Zane)-[:RELATES_TO]->(ham bones)  ← Auto-linked!
```

**3. User Connects to Topics**

Every topic extracted from a conversation is linked to the user with `INTERESTED_IN`, enabling "What do you know about me?" queries:

```cypher
// Find all topics a user has discussed
MATCH (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
      -[:INTERESTED_IN]->(t:KnowledgeNode {node_type: 'topic'})
RETURN t.label as topic, count(*) as mentions
ORDER BY mentions DESC
```

**4. Messages Connect to Users**

`MessageEmbedding` nodes (used for semantic search) now connect to User nodes with `DISCUSSED` relationships, making the graph traversable from user to their conversation history:

```cypher
// Find user's semantically similar past discussions
MATCH (u:KnowledgeNode {user_id: $user_id})-[:DISCUSSED]->(m:MessageEmbedding)
WITH m, gds.similarity.cosine(m.embedding, $query_embedding) AS score
WHERE score > 0.7
RETURN m.content, score
ORDER BY score DESC
```

#### Knowledge Extraction Flow

```
User says: "I'm going to Under the Radar Brewery in Houston with Rachel"
                    │
                    ▼
         ┌─────────────────────────────┐
         │     Knowledge Agent         │
         │  (LLM entity extraction)    │
         └─────────────────────────────┘
                    │
                    ▼
         Extracted: ["Under the Radar Brewery", "Houston", "Rachel"]
                    │
                    ▼
         ┌─────────────────────────────┐
         │   record_interaction()      │
         │   (Neo4j MERGE operations)  │
         └─────────────────────────────┘
                    │
         Creates/Updates graph:
         
         (User)
           │
           ├──[:FOLLOWED_BY]──→ (Interaction: "Going to brewery...")
           │                          │
           │                          ├──[:MENTIONED_IN]──→ (Under the Radar Brewery)
           │                          ├──[:MENTIONED_IN]──→ (Houston)
           │                          └──[:MENTIONED_IN]──→ (Rachel)
           │
           ├──[:INTERESTED_IN]──→ (Under the Radar Brewery)
           ├──[:INTERESTED_IN]──→ (Houston)
           └──[:INTERESTED_IN]──→ (Rachel)
           
         Plus topic-to-topic relationships:
         (Under the Radar Brewery)──[:RELATES_TO]──→ (Houston)
         (Under the Radar Brewery)──[:RELATES_TO]──→ (Rachel)
         (Houston)──[:RELATES_TO]──→ (Rachel)
```

#### Example Graph Queries

**Find everything related to a topic:**
```cypher
MATCH (t:KnowledgeNode {label: 'Zane'})-[r]-(connected)
RETURN t, r, connected
```

**Find topics that often appear together:**
```cypher
MATCH (t1:KnowledgeNode {node_type: 'topic'})-[:RELATES_TO]-(t2:KnowledgeNode {node_type: 'topic'})
WHERE t1.label < t2.label  // Avoid duplicates
RETURN t1.label, t2.label, count(*) as co_occurrences
ORDER BY co_occurrences DESC
LIMIT 10
```

**Build a user's interest profile:**
```cypher
MATCH (u:KnowledgeNode {user_id: $user_id})-[:INTERESTED_IN]->(t:KnowledgeNode)
WITH t.label as topic, count(*) as mentions
ORDER BY mentions DESC
LIMIT 20
RETURN collect({topic: topic, mentions: mentions}) as interests
```

**Find conversation threads about a topic:**
```cypher
MATCH (t:KnowledgeNode {label: 'Houston'})<-[:MENTIONED_IN]-(i:KnowledgeNode {node_type: 'interaction'})
RETURN i.label as interaction, i.created_at as when
ORDER BY i.created_at DESC
```

#### Context Recall Example

When the user later asks "What should I do this weekend?", the system:

```cypher
// Query user's interests and related topics
MATCH (u:KnowledgeNode {user_id: $user_id})-[:INTERESTED_IN]->(t:KnowledgeNode)
OPTIONAL MATCH (t)-[:RELATES_TO]-(related:KnowledgeNode)
RETURN t.label as topic, collect(DISTINCT related.label) as related_topics
ORDER BY t.updated_at DESC
LIMIT 10
```

Returns:
- Under the Radar Brewery → related: [Houston, Rachel]
- Zane → related: [ham bones, dog, fetch]
- Houston → related: [Under the Radar Brewery, Montrose, restaurants]

The AI can then suggest: *"You mentioned Under the Radar Brewery with Rachel recently — maybe check if they have any events this weekend? Or take Zane to the park since he loves fetch!"*

#### Visualization

The frontend's Knowledge Graph view (accessible from the sidebar) renders this graph interactively:

- **Nodes** are colored by type (User = blue, Topic = green, Interaction = orange, Tool = purple)
- **Relationships** are shown as labeled edges
- **Click** a node to see its connections
- **Filter** by node type to focus on specific aspects

The graph grows richer over time as you have more conversations, building a personal knowledge base that helps the AI remember and connect information across all your interactions.

---

### Enhanced Knowledge Graph: Social Intelligence & Reasoning

Beyond basic topic tracking, the knowledge graph now supports **rich social intelligence**, **temporal awareness**, and **advanced reasoning** capabilities.

#### Social Graph: People, Pets & Locations

The system automatically extracts and tracks people, pets, and locations mentioned in your conversations, building a comprehensive social graph.

**New Node Types:**

| Node Type | Purpose | Extracted Properties |
|-----------|---------|---------------------|
| **PersonNode** | People in your life | name, aliases, relationship_type (spouse, friend, colleague, etc.), context_notes, email, phone |
| **PetNode** | Your pets | name, species, breed, age, personality traits, food preferences, health notes |
| **LocationNode** | Places you mention | name, location_type (restaurant, gym, office, etc.), address, city, neighborhood, activities |
| **PreferenceNode** | Your preferences | category, value, sentiment (-1 to +1), confidence, mention count |

**Automatic Entity Extraction:**

When you say something like:
```
"Had dinner with my wife Sarah at Uchi last night. She loved the omakase!"
```

The system extracts:
- **Person**: Sarah (relationship: spouse, context: "loved the omakase")
- **Location**: Uchi (type: restaurant, activity: dinner)
- **Preference**: Sarah likes omakase (sentiment: positive)
- **Relationship**: `(Sarah)-[:FREQUENTS]->(Uchi)`

**Example Queries Using Social Graph:**

```
User: "What restaurants has Sarah been to?"
Agent: Uses get_person_info and graph traversal to find:
       → Sarah has been to Uchi, Roka Akor, and Underbelly

User: "What does Zane like to eat?"
Agent: Uses get_pet_info to retrieve:
       → Zane (Golden Retriever) loves ham bones, chicken treats, and carrots

User: "Where do we usually go on date nights?"
Agent: Traverses (User)-[:KNOWS]->(Sarah)-[:FREQUENTS]->(Location)
       → You and Sarah frequent Uchi, Mastro's, and The Pass
```

**New Social Graph Tools:**

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `get_person_info` | Get details about someone in your social graph | "What do you know about my friend Jake?" |
| `get_pet_info` | Get information about your pets | "Tell me about my dog" |
| `get_location_info` | Get details about a saved location | "What do you know about Uchi?" |
| `list_known_people` | List all people you've mentioned | "Who have I told you about?" |
| `list_pets` | List all your pets | "What pets do I have?" |
| `list_locations` | List all tracked locations | "What places have I mentioned?" |
| `get_user_preferences` | Get your stored preferences | "What are my food preferences?" |

#### Temporal Intelligence: Time-Based Recall & Patterns

The system tracks when things happen and detects behavioral patterns over time.

**Time-Based Recall:**

```
User: "What did I talk about last week?"
Agent: Uses recall_from_period to search messages from the past 7 days
       → Returns relevant conversations grouped by topic

User: "What happened on Christmas?"
Agent: Recalls messages around December 25th
       → "You mentioned having dinner at your parents' house with Sarah"
```

**Pattern Detection:**

The `PatternDetector` service identifies recurring behaviors:

| Pattern Type | Example | How It's Detected |
|-------------|---------|-------------------|
| **RECURRING_QUERY** | "What's the weather?" asked daily | Same/similar questions asked 3+ times |
| **DAILY_HABIT** | Active at 2 PM most days | Message clustering by hour across days |
| **WEEKLY_EVENT** | "Team meeting" every Monday | Weekly recurrence detection |
| **TOPIC_CYCLE** | Monthly budget review | Longer-term cyclical patterns |

**Contradiction Detection:**

When you provide conflicting information, the system detects it:

```
Past: "My favorite color is blue"
New: "I love red, it's my favorite color"

→ Contradiction detected: favorite_color changed from "blue" to "red"
→ System can ask for clarification or update based on recency
```

**New Tool:**

| Tool | Description | Example |
|------|-------------|---------|
| `recall_from_period` | Search messages within a date range | "What did we discuss in January?" |

#### Proactive Intelligence: Suggestions & Expertise

**Contextual Suggestions:**

As you chat, the system proactively retrieves related context from your knowledge graph:

```
User: "I'm planning a birthday party"

Background graph traversal finds:
→ Sarah's birthday is in March (from past mention)
→ You've hosted parties at home before
→ Sarah likes Italian food
→ Jake and Emily are close friends

This context enriches the response with personalized suggestions.
```

**Cross-Conversation Threading:**

Track ongoing projects or topics across multiple conversations:

```cypher
// Threads connect related conversations
(Thread: "Kitchen renovation")-[:INCLUDES]->(Conv1)
(Thread: "Kitchen renovation")-[:INCLUDES]->(Conv2)
(Thread: "Kitchen renovation")-[:RELATES_TO]->(Topic: "contractors")
```

| Tool | Description | Example |
|------|-------------|---------|
| `get_thread_history` | Get conversation history for an ongoing project | "What have we discussed about my renovation?" |

**Expertise Profiling:**

The system tracks your expertise level in different topics to tailor responses:

```
User has discussed Python → assessed as "intermediate"
User has discussed cooking → assessed as "novice"
User has discussed cycling → assessed as "expert"

When explaining Python:
→ Skip basic syntax explanations
→ Use technical terms freely
→ Assume knowledge of common libraries

When explaining cooking:
→ Define culinary terms
→ Provide step-by-step instructions
→ Suggest beginner-friendly approaches
```

#### Group Intelligence: Shared Knowledge

For group chats, the knowledge graph enables social intelligence across members.

**Shared Interests:**

```
Group: Cycling Club

Alice → INTERESTED_IN → cycling, gravel bikes, Strava
Bob → INTERESTED_IN → cycling, road bikes, nutrition
Carol → INTERESTED_IN → cycling, bikepacking, camping

Overlap: All members share interest in cycling
Alice & Carol: Both interested in off-road cycling
```

**Group Consensus:**

| Tool | Description | Example |
|------|-------------|---------|
| `get_shared_interests` | Find topics all/most group members care about | "What does our group have in common?" |
| `get_group_consensus` | Analyze group sentiment on a topic | "What does the team think about remote work?" |

**Example:**

```
User in group: "@agent what should we do for the team outing?"

Agent queries:
1. Shared interests across group members
2. Past group activities mentioned
3. Location preferences of members
4. Any scheduling constraints mentioned

Response: "Based on everyone's interests, you might enjoy:
- A group bike ride (3 members are cyclists)
- Visiting Top Golf (Jake and Sarah mentioned it)
- Dinner at a steakhouse (most popular cuisine preference)"
```

#### Advanced Reasoning: Inference & Aggregation

**Multi-Hop Inference:**

The inference engine derives new facts by traversing the graph:

```
Known: Sarah → FREQUENTS → Uchi
Known: Uchi → SERVES → Japanese cuisine
Known: Sarah → IS_SPOUSE_OF → User

Inferred: User might enjoy Japanese cuisine
         (via spouse's restaurant preferences)
```

**Inference Rules:**

| Rule | Pattern | Inference |
|------|---------|-----------|
| `category_preference` | Person likes X, X is in category Y | Person may like category Y |
| `location_via_person` | Person frequents Location | User may want to visit Location |
| `activity_suggestion` | Person enjoys Activity at Location | Suggest Activity at Location |

**Preference Aggregation:**

Scattered mentions are consolidated into a coherent preference profile:

```
Mentions:
- "I love sushi" (3 times, positive)
- "Hate cilantro" (2 times, negative)  
- "That Thai place was okay" (1 time, neutral)

Aggregated Profile:
├── Food
│   ├── sushi: likes (confidence: 0.9, mentions: 3)
│   ├── cilantro: dislikes (confidence: 0.85, mentions: 2)
│   └── Thai food: neutral (confidence: 0.5, mentions: 1)
```

**Example: Preference-Based Recommendations:**

```
User: "Where should I eat tonight?"

System:
1. Aggregates food preferences (likes: sushi, Italian, steak)
2. Checks location graph (restaurants near home/work)
3. Cross-references with people (Sarah likes Uchi, you went there together)
4. Applies inference (liked omakase at Uchi → may like other high-end Japanese)

Response: "Based on your preferences, I'd suggest:
- Uchi (you and Sarah loved the omakase)
- Kata Robata (similar to Uchi, highly rated)
- Or Mastro's if you're in the mood for steak"
```

---

### Vector Embeddings: Semantic Search

Vector embeddings enable **similarity-based retrieval** of past conversations and knowledge.

#### How Embeddings Work

```
Text: "I'm learning Python for data science"
                    │
                    ▼
         ┌─────────────────────┐
         │  OpenAI Embeddings  │
         │ text-embedding-3-small │
         └─────────────────────┘
                    │
                    ▼
         Vector: [0.023, -0.156, 0.089, ..., 0.042]
                 (1536 dimensions)
                    │
                    ▼
         Stored in Neo4j with message metadata
```

#### Semantic Search Process

When processing a new message, the system finds related past discussions:

```
New message: "How do I create a pandas DataFrame?"
                    │
                    ▼
         1. Generate embedding for new message
                    │
                    ▼
         2. Vector similarity search in Neo4j
         
         MATCH (m:Message)
         WHERE m.embedding IS NOT NULL
         WITH m, gds.similarity.cosine(m.embedding, $query_embedding) AS score
         WHERE score > 0.7
         RETURN m.content, score
         ORDER BY score DESC
         LIMIT 5
                    │
                    ▼
         3. Returns semantically similar messages:
         • "I'm learning Python for data science" (score: 0.89)
         • "Working with CSV files in Python" (score: 0.82)
         • "Data analysis project setup" (score: 0.76)
```

#### Why Vector Search Matters

| Scenario | Keyword Search | Vector Search |
|----------|----------------|---------------|
| Query: "DataFrame" | Finds exact matches only | Finds related: "pandas", "data tables", "CSV" |
| Query: "my pet" | Misses "Zane", "dog" | Finds: "Zane loves fetch", "dog named Zane" |
| Query: "weekend plans" | Limited matches | Finds: activities, hobbies, preferences |

---

### Context Assembly: Putting It All Together

When generating a response, the system assembles context from all sources:

```python
async def assemble_context(user_id: str, message: str) -> AssembledContext:
    # 1. Immediate context: Recent conversation messages
    recent_messages = await get_recent_messages(conversation_id, limit=20)
    
    # 2. Learned context: Facts and preferences from Neo4j
    user_knowledge = await knowledge_graph.get_user_knowledge(user_id)
    # Returns: facts, preferences, frequently discussed topics
    
    # 3. Semantic context: Related past discussions via embeddings
    message_embedding = await embedding_adapter.embed(message)
    related_messages = await knowledge_graph.semantic_search(
        user_id=user_id,
        embedding=message_embedding,
        limit=5,
    )
    
    # 4. Active plan context (if any)
    active_plan = await get_active_plan(user_id)
    
    return AssembledContext(
        recent_messages=recent_messages,
        user_facts=user_knowledge.facts,
        user_preferences=user_knowledge.preferences,
        related_history=related_messages,
        active_plan=active_plan,
    )
```

This assembled context is then provided to the AI agents, enabling responses that:
- Reference recent conversation naturally
- Remember user-specific facts ("your dog Zane")
- Connect to related past discussions
- Continue multi-step plans seamlessly

---

### Group Chat Context

Group conversations have additional context layers:

| Layer | Source | Purpose |
|-------|--------|---------|
| **Group Messages** | PostgreSQL | Recent group chat history |
| **Member Context** | Neo4j | What the system knows about each participant |
| **Extracted Events** | PostgreSQL | Upcoming events, deadlines, meetings |
| **Social Suggestions** | LLM Analysis | AI-generated activity suggestions |

When the AI assistant is mentioned in a group (`@agent`), it:
1. Loads recent group messages for conversational context
2. Identifies which users are involved
3. Recalls relevant facts about those users
4. Generates responses that consider group dynamics

---

### Performance Considerations

| Storage | Latency | Best For |
|---------|---------|----------|
| PostgreSQL | ~1-5ms | Recent messages, structured queries |
| Neo4j (graph queries) | ~10-50ms | Relationship traversal, fact lookup |
| Neo4j (vector search) | ~50-200ms | Semantic similarity, context recall |

The system prioritizes:
1. **Immediate context** (always fast, from PostgreSQL)
2. **User facts** (cached, from Neo4j)
3. **Semantic search** (async/background when possible)

For group messages, embedding storage runs in the background (fire-and-forget) to avoid blocking the real-time WebSocket connection.

## Documentation

Two sets of docs ship with this repository:

- **This README** is the engineering account: architecture, the agent roster, the FSM, memory, API reference and setup.
- **`src/agent_system/docs/`** is written for people using the app, and it is also loaded into the agent itself. `search_internal_docs` serves it, and the response agents route questions like "what tools do you have" or "how do I connect my calendar" to that tool, so the agent answers from these files. Anything shipped but missing there is a feature the agent will not know it has.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Docker (optional, for Neo4j)

### Installation

```bash
# Clone and enter directory
cd pydantic_ai_state

# Setup using Makefile
make setup
```

Or manually:

```bash
# Create Python virtual environment
uv venv .venv
source .venv/bin/activate

# Install Python dependencies
uv pip install -e ".[dev]"

# Install frontend dependencies
cd frontend && npm install && cd ..

# Create environment file
cp .env.example .env
```

### Configuration

Edit `.env` with your settings:

```bash
# Required
OPENAI_API_KEY=sk-your-key-here
SECRET_KEY=your-secret-key-for-jwt

# Database (SQLite default, or PostgreSQL)
DATABASE_URL=sqlite+aiosqlite:///./agent_system.db
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/dbname

# Optional: Neo4j Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Optional: Encryption key for user API keys
ENCRYPTION_KEY=your-fernet-key
```

### Running the Application

**Using Makefile:**

```bash
# Start backend (terminal 1)
make backend

# Start frontend (terminal 2)
make frontend
```

**Or manually:**

```bash
# Backend
source .venv/bin/activate
uvicorn agent_system.adapters.inbound.api.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm run dev
```

**Access the application:**
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs
- API ReDoc: http://localhost:8000/redoc

## User Setup

### First-Time Setup (Bootstrap)

When no users exist, create the admin account:

![Bootstrap Flow](docs/images/bootstrap-flow.png)

1. Open http://localhost:3000
2. Click "Create Admin Account"
3. Enter email and password
4. You're now logged in as superuser

### User Management (Admin)

Admins can manage users from the dropdown menu → "Manage Users":

- **Create users**: Add new users with email/password
- **Verify users**: Approve pending users
- **Deactivate users**: Disable user access
- **Delete users**: Remove users permanently

### Per-User API Keys

Users can set their own OpenAI API key:

1. Click your email in the header → "API Key Settings"
2. Enter your OpenAI API key (starts with `sk-`)
3. Your key is encrypted and stored securely
4. The system falls back to the global key if none set

## API Reference

### Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password"}'

# Get current user
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

### Agent Chat

```bash
# Send message
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the capital of France?"}'

# Stream response with FSM trace
curl -N http://localhost:8000/api/v1/agent/chat/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for Python tutorials"}'
```

### Conversations

```bash
# List conversations
curl http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer <token>"

# Create conversation
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "My Chat"}'

# Get conversation with messages
curl http://localhost:8000/api/v1/conversations/<id> \
  -H "Authorization: Bearer <token>"
```

### Groups

```bash
# Create group
curl -X POST http://localhost:8000/api/v1/groups \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Team Chat", "description": "Our team discussions"}'

# Add member (owner only)
curl -X POST http://localhost:8000/api/v1/groups/<id>/members \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<user-id>"}'

# Get extracted events
curl http://localhost:8000/api/v1/groups/<id>/events \
  -H "Authorization: Bearer <token>"
```

### Plans

```bash
# Create plan
curl -X POST http://localhost:8000/api/v1/plans \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "goal_description": "Build a web scraper",
    "success_criteria": ["Scraper works", "Data is saved"],
    "steps": [
      {"description": "Design the scraper"},
      {"description": "Implement parsing"},
      {"description": "Test with sample sites"}
    ]
  }'

# Activate plan
curl -X POST http://localhost:8000/api/v1/plans/<id>/activate \
  -H "Authorization: Bearer <token>"
```

### Knowledge Graph

```bash
# Get user's knowledge graph
curl http://localhost:8000/api/v1/knowledge/graph \
  -H "Authorization: Bearer <token>"

# Clear knowledge graph
curl -X DELETE http://localhost:8000/api/v1/knowledge/graph \
  -H "Authorization: Bearer <token>"
```

### Direct Tool Access

```bash
# List all tools
curl http://localhost:8000/api/v1/tools \
  -H "Authorization: Bearer <token>"

# Search the web
curl "http://localhost:8000/api/v1/tools/search?query=python+tutorials" \
  -H "Authorization: Bearer <token>"

# Calculate
curl "http://localhost:8000/api/v1/tools/calculate?expression=2**10" \
  -H "Authorization: Bearer <token>"

# Get current time
curl http://localhost:8000/api/v1/tools/datetime \
  -H "Authorization: Bearer <token>"

# Define a word
curl http://localhost:8000/api/v1/tools/define/serendipity \
  -H "Authorization: Bearer <token>"
```

## Neo4j Setup (Optional)

For knowledge graph features, run Neo4j:

```bash
# Using Docker
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest

# Or using Makefile
make neo4j
```

Then update `.env`:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

Access Neo4j Browser: http://localhost:7474

## Testing

```bash
# Run all tests
make test

# Or manually
pytest

# Run by category
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests
pytest -m e2e           # End-to-end tests

# With coverage
pytest --cov=agent_system --cov-report=term-missing
```

## Development

### Makefile Commands

```bash
make setup      # Full setup (install + create .env)
make install    # Install all dependencies
make backend    # Run backend server
make frontend   # Run frontend dev server
make test       # Run tests
make lint       # Run linters
make clean      # Clean build artifacts
make neo4j      # Start Neo4j container
```

### Code Style

- **Python**: Formatted with Black, linted with Ruff
- **TypeScript**: ESLint + Prettier
- **Architecture**: Hexagonal/Ports & Adapters
- **Testing**: pytest with unit/integration/e2e markers

## Frontend Features

### Individual Chat
- Conversation management
- Real-time FSM trace visualization
- Suggestion chips for quick actions
- Dark/light mode

### Group Collaboration
- Real-time messaging via WebSocket
- AI agent assistance (`@agent` mentions)
- Automatic event extraction
- Member management (owner controls)
- Online presence indicators

### Knowledge Graph
- Interactive force-directed visualization
- Node filtering by type
- Relationship exploration

### Settings
- API key management (per-user)
- Password change
- User management (admin)
- Theme preferences

## Security

- **Authentication**: JWT tokens with bcrypt password hashing
- **Authorization**: Role-based (user, superuser)
- **API Keys**: Fernet encryption for stored keys
- **Privacy**: Per-member sharing controls in groups

## License

MIT
