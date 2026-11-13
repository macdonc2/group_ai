# Memory and Knowledge

How the agent remembers things, learns about your life, and recalls information from past conversations.

---

## How Memory Works

The agent doesn't just answer your current message and forget. It builds a persistent picture of you and your world across every conversation. This happens in several ways:

### 1. Conversation Memory

Every message you send is stored and can be recalled later. The agent uses **semantic search** (meaning-based matching, not just keyword matching) to find relevant past conversations when answering new questions. So if you talked about your dog Zane three weeks ago, and you mention "my dog" today, the agent connects the dots.

Journal entries count too. What you save in the **Journal** tab is stored in the same memory, labelled with the day it was written, so you can ask in chat "what did I write about Dana's move?" The assistant's replies in the journal's conversation panel are not memorised; only your saved entries are.

### 2. Knowledge Extraction

After each conversation, the agent automatically extracts and saves:

- **Topics** you discussed
- **People** you mentioned (with names, relationships, and context)
- **Pets** you talked about (with species, breed, personality)
- **Locations** you referenced (restaurants, parks, offices)
- **Preferences** you expressed (favorite foods, activities, dislikes)
- **Patterns** in how you communicate

### 3. Social Graph

The agent builds a **social graph** -- a map of the people, pets, and places in your life. Over time, it learns:

- Who your friends and family are
- What pets you have and their quirks
- Your favorite restaurants and hangout spots
- How all these things connect to each other

---

## The Knowledge Graph

Behind the scenes, all this information is stored in a **knowledge graph** -- a network of connected information. Think of it like a web where each node is a person, pet, place, or topic, and the connections between them show how they relate.

### What Gets Stored

| Type | Examples | How It's Learned |
|---|---|---|
| People | "Zane is my dog", "Bo is my friend" | Mentioned in conversation |
| Pets | "Roxanne is a German Shepherd who loves walks" | Mentioned in conversation |
| Locations | "We go to Underbelly for dinner a lot" | Mentioned in conversation |
| Topics | Cooking, cycling, football | Discussed frequently |
| Preferences | "I prefer spicy food", "I hate mornings" | Expressed in conversation |
| Interactions | What you asked about, which tools were used | Tracked automatically |

### How It Grows

The knowledge graph grows naturally as you chat. You don't need to do anything special -- just talk about your life, and the agent picks up on details. The more specific you are, the better it remembers:

- "My dog" -- The agent knows you have a dog
- "My dog Zane" -- Now it has a name
- "Zane is a hound mix who steals ham off the counter" -- Now it knows breed and personality

---

## Asking About What the Agent Knows

### "What do you know about me?"

Ask the agent to summarize everything it's learned about you. It pulls from your knowledge graph and conversation history to give you an overview of:

- Topics you've discussed
- People and pets in your life
- Your preferences and interests
- How much it's stored

### "What do you know about [person/pet/topic]?"

Ask about a specific entity to get targeted recall. Examples:

- "What do you know about Zane?" -- Everything about your dog Zane
- "Tell me about Bo" -- What it knows about your friend Bo
- "What have we talked about regarding cooking?" -- Topic-specific recall

### "Who do I know?" / "List my pets" / "What are my favorite places?"

Ask for lists of specific categories:

- "Who do I know?" or "List people I've mentioned" -- Shows your social graph
- "List my pets" -- Shows all pets, optionally filtered by species
- "What places do I go to?" -- Shows your frequent locations
- "What are my preferences?" -- Shows learned preferences (food, activities, etc.)

### "What did we talk about last week?"

Recall conversations from a specific time period. The agent searches past messages within the date range and can optionally filter by topic.

---

## Semantic Search

When the agent searches its memory, it uses **semantic search** rather than simple keyword matching. This means:

- Asking about "my puppy" will find conversations where you mentioned "dog" or "Zane"
- Asking about "dinner plans" will find messages about restaurants, food, and eating out
- Asking about "exercise" will find conversations about cycling, walking the dogs, going to the gym

The system converts your messages into mathematical representations (called **embeddings**) that capture meaning. When you ask a question, it converts that into an embedding too and finds the closest matches.

---

## Group Memory

In group chats, the agent builds a separate knowledge base for the group:

- **Group messages** are embedded and searchable within the group context
- **Group topics** are tracked (what the group discusses most)
- **Group consensus** can be queried ("What does the group think about X?")
- **Individual context** is kept separate -- your personal knowledge graph doesn't bleed into group conversations and vice versa

You can ask the agent in a group chat things like:

- "What has the group discussed about the trip?"
- "Recall what we said about the restaurant last week"

---

## Knowledge Graph Visualization and Explorer

You can see and explore your knowledge graph visually:

1. Click the **Knowledge Graph** button (brain icon) in the interface
2. The window shows your graph: each dot is a person, pet, place, topic, preference or past conversation, and the lines show how they relate

What you can do there:

- **Filter** -- the left panel lists every node type and link type with counts. Untick a type to hide it, or click "only" to show just that type.
- **Search** -- type in "Find nodes" to highlight everything whose name or details match.
- **Inspect a node** -- click any node to open the Node panel with its stored details and every link. Click a link to jump to the node on the other end.
- **Focus on a neighbourhood** -- with a node selected, choose 1, 2 or 3 hops to show only what is that close to it.
- **Find a path** -- with a node selected, click "Find path to..." and then click another node to see the shortest chain connecting them.
- **Ask about the graph** -- the Ask panel answers questions from what is stored in your graph, for example "Who do I know, and how?", "Which places do the people I know go to?", "How is June connected to Blue Door Coffee?" or "Show only people and pets". The nodes behind the answer are highlighted in the graph, and you can expand the answer to see which lookups it ran. If you have a node selected, you can say "this" to refer to it.

The Ask panel only reads your graph. It cannot change or delete anything, it only sees your own data, and if the graph does not contain the answer it says so instead of guessing.

**Clear Graph** (the red bin icon) permanently deletes your knowledge graph: topics, past-conversation summaries, people, pets, places and preferences.

## Privacy

- Your knowledge graph is **private to you**. Other users can't see what the agent has learned about you.
- In groups, the agent builds a separate group knowledge base. Your personal graph stays separate.
- You can toggle **sharing_enabled** in group settings to control whether your messages contribute to group AI analysis.
- You can clear your knowledge graph at any time.
- Your journal is private to you as well. Deleting a journal entry removes its text from memory; facts already learned from it (a person, a pet, a preference) stay until you remove them in the Knowledge Graph window.
