# Tools and Capabilities

A complete guide to everything the agent can do, including all available tools.

---

## Overview

The agent has a collection of **tools** it can use to answer your questions and complete tasks. When you send a message, the agent figures out which tool (if any) is the best fit and uses it automatically. You don't need to specify which tool to use -- just ask naturally.

---

## Information Tools

### Web Search

Searches the internet for current information. The agent uses this for real-time questions that aren't covered by its built-in tools.

**When it's used:**
- "What's the weather in Houston?"
- "Latest news about SpaceX"
- "How tall is the Eiffel Tower?"

### Word Definitions

Looks up the meaning, pronunciation, and usage of words.

**When it's used:**
- "What does 'serendipity' mean?"
- "Define 'ubiquitous'"

### Calculator

Evaluates math expressions safely.

**When it's used:**
- "What's 15% of 230?"
- "Calculate 1024 / 16"
- "What's 2^10?"

### Random Fact

Returns an interesting piece of trivia.

**When it's used:**
- "Tell me a fun fact"
- "Give me some trivia"

### Date and Time

Gets the current date and time in your configured timezone.

**When it's used:**
- "What time is it?"
- "What day is it?"
- "What's today's date?"

---

## Memory and Recall Tools

### Summarize My Knowledge

Gives you a complete overview of everything the agent has learned about you -- topics, people, pets, places, preferences, and interaction history.

**When it's used:**
- "What do you know about me?"
- "Summarize what you've learned"

### Recall About a Topic

Searches past conversations for information about a specific person, pet, place, or topic. Uses semantic search to find relevant matches even if the exact words don't match.

**When it's used:**
- "What do you know about Zane?"
- "Tell me about Bo"
- "What have we discussed about cooking?"

### Recall Group Topic

Same as above, but searches within a specific group's conversation history.

**When it's used (in group chats):**
- "What has the group discussed about the trip?"
- "Recall what we said about the restaurant"

### Recall From a Time Period

Searches past conversations within a specific date range.

**When it's used:**
- "What did we talk about last week?"
- "What happened in January?"

### Conversation History

Gets summaries of your recent conversations.

**When it's used:**
- "Show me my recent conversations"
- "What have we been talking about?"

### Conversation Patterns

Analyzes patterns in your conversation history -- what topics come up most, how often you chat, and trends over time.

**When it's used:**
- "Analyze my conversation patterns"
- "What do I talk about most?"

### Thread History

Retrieves the history of a topic or project that spans multiple conversations.

**When it's used:**
- "Show me the thread about the kitchen renovation"
- "What's the history of the birthday planning?"

---

## Social Graph Tools

### Person Info

Gets everything the agent knows about a specific person in your social graph.

**When it's used:**
- "Tell me about Bo"
- "What do you know about Sarah?"

### Pet Info

Gets information about a specific pet.

**When it's used:**
- "Tell me about Zane"
- "What do you know about Roxanne?"

### Location Info

Gets information about a place you've mentioned.

**When it's used:**
- "Tell me about Underbelly"
- "What do you know about Buffalo Bayou Park?"

### List People

Lists all people the agent knows about from your conversations, optionally filtered by relationship type (friend, family, colleague, etc.).

**When it's used:**
- "Who do I know?"
- "List my family members"
- "Show me my colleagues"

### List Pets

Lists all pets, optionally filtered by species.

**When it's used:**
- "List my pets"
- "What dogs do I have?"
- "Show me my cats"

### List Locations

Lists all places you've mentioned, optionally filtered by type or city.

**When it's used:**
- "What restaurants do I go to?"
- "List my favorite places"
- "Show me places in Houston"

### User Preferences

Shows preferences the agent has learned from your conversations, optionally filtered by category (food, activities, schedule, etc.).

**When it's used:**
- "What are my preferences?"
- "What food do I like?"
- "What activities do I enjoy?"

---

## Event Tools

### Personal Events

Searches your extracted events (from group chats) with flexible filtering by timeframe, keyword, date, or whether events are past or future.

**When it's used:**
- "What do I have planned today?"
- "Any meetings this week?"
- "When is my haircut?"
- "What did I do last month?"

### Houston Events

Searches the curated Houston area events database for concerts, cycling, sports, arts, food events, and more.

**When it's used:**
- "What's happening in Houston this weekend?"
- "Any concerts tonight?"
- "Cycling events near me"
- "What events are in Montrose?"

---

## Profile and Settings Tools

### User Profile

Shows your profile information and current settings.

**When it's used:**
- "Show me my profile"
- "What are my settings?"

### Update Preferences

Updates your agent preferences (like response temperature, auto-planning, verbose responses).

**When it's used:**
- "Make your responses more creative"
- "Turn on auto-planning"
- "Give me shorter responses"

### Remember About User

Saves a specific observation or pattern the agent has noticed about you.

**When it's used:** This runs automatically when the agent learns something new about you.

---

## Group Tools

### Group Consensus

Gets a summary of what the group has discussed about a specific topic, including different viewpoints.

**When it's used (in group chats):**
- "What does the group think about the restaurant?"
- "What's the consensus on the trip dates?"

---

## Internal Documentation Search

Searches the app's built-in documentation to answer questions about how the app works.

**When it's used:**
- "How does the knowledge graph work?"
- "How do I connect my calendar?"
- "How do groups work?"
- "What is semantic search?"

---

## Automatic vs. On-Demand

Most tools are used **on demand** -- you ask a question and the agent picks the right tool. A few things happen **automatically**:

- **Knowledge extraction** -- After each conversation, the agent saves new facts it learned
- **Event extraction** -- In group chats, events are detected and saved automatically
- **Semantic embedding** -- Your messages are indexed for future recall
- **Preference learning** -- The agent picks up on your likes, dislikes, and patterns over time
