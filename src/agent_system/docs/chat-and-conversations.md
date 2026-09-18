# Chat and Conversations

Everything about talking to the agent and managing your conversations.

---

## How Chat Works

When you send a message, the agent goes through several steps behind the scenes:

1. **Analyze Intent** -- Figures out what you're asking (a question, a task, a joke, etc.) and identifies any people, pets, or topics you mentioned.
2. **Check Knowledge** -- Searches its memory for relevant context from past conversations.
3. **Select a Tool** -- Decides if it needs to use a tool (web search, calculator, event lookup, etc.).
4. **Execute the Tool** -- Runs the chosen tool and gets results.
5. **Generate Response** -- Writes a thoughtful reply using everything it knows.
6. **Learn** -- Saves any new facts, people, or preferences it picked up from your message.

You can watch this process in real time via the **Workflow Trace** panel.

---

## What You Can Ask

### General Conversation

Just chat naturally. The agent handles casual conversation, jokes, stories, opinions, and more. It remembers context within and across conversations.

### Questions

- "What's the weather like?" -- Searches the web
- "What does 'serendipity' mean?" -- Looks up the definition
- "What's 15% of 230?" -- Uses the calculator
- "What time is it?" -- Shows your current time

### About People and Pets You Know

- "Tell me about Zane" -- Recalls everything it knows about Zane
- "What are my dogs' names?" -- Lists pets from your social graph
- "Who do I know?" -- Lists people in your social graph

### About Your Schedule

- "What do I have planned today?" -- Checks your events
- "Any meetings this week?" -- Looks at upcoming events
- "What happened last week?" -- Recalls past events

### About Houston Events

- "What's happening in Houston this weekend?" -- Searches the Houston events database
- "Any concerts tonight?" -- Filters by category and time
- "Cycling events near me" -- Category-specific search

### About the App Itself

- "What can you do?" -- Lists capabilities
- "How does the knowledge graph work?" -- Searches internal docs
- "How do groups work?" -- Explains the feature

---

## Conversations

### Starting a New Conversation

Click the **+** button in the sidebar to start a fresh conversation. The agent still remembers things from past conversations -- a new conversation just starts a clean thread.

### Conversation Titles

Each conversation gets an auto-generated title based on what you talked about (e.g., "Zane's Birthday Plans" or "Houston Events This Week"). These appear in the sidebar so you can find old conversations easily.

### Switching Conversations

Click any conversation in the sidebar to switch to it. Your message history is preserved.

### The Wrestler a Conversation Was Spoken In

If you are using a wrestler theme, the conversation remembers it. Reopening a
conversation switches the app back to that wrestler, and choosing a different one
partway through saves it to that conversation. Conversations with a theme show the
wrestler's headshot in the sidebar. Clearing the theme sets the conversation back to
the plain voice.

### Deleting Conversations

Hover over a conversation in the sidebar and click the delete icon. This removes the conversation and its messages, but knowledge the agent learned from it stays in the knowledge graph.

### Archiving Conversations

You can archive conversations you want to keep but don't need cluttering your sidebar.

---

## Suggestion Chips

After the agent responds, you may see small clickable buttons below the message. These are **suggestions** -- contextual follow-ups the agent thinks you might want to ask next.

For example, after asking about Houston events, you might see:

- "Filter by category"
- "What's happening this weekend?"

After asking about a person, you might see:

- "More about Zane"
- "What do you know about Roxanne?"

Click any suggestion to send it as your next message. They're shortcuts, not required -- you can always type your own message instead.

---

## Workflow Trace

The **Workflow Trace** panel shows what the agent is doing step by step as it processes your message. Each step shows:

- **Name** -- What the step is (e.g., "Analyze Intent", "Execute Tool", "Generate Response")
- **Status** -- Whether it completed, was skipped, or is still running
- **Timing** -- How long each step took
- **Details** -- Key data like the detected intent type, which tool was selected, confidence scores, and extracted entities

This is useful for understanding why the agent responded the way it did. For example, if it used web search instead of checking your events, you can see that decision in the trace.

On desktop, the trace panel lives on the right side of the screen. On mobile, you can toggle it via a button.

---

## Streaming Responses

The agent streams its response as it generates it, so you see words appear in real time rather than waiting for the full reply. This makes long responses feel faster.

---

## Markdown Formatting

The agent formats its responses with markdown, which means you'll see:

- **Bold text** for emphasis
- *Italic text* for nuance
- Tables for structured data (like event listings)
- Bulleted and numbered lists
- Code blocks for technical content
- Links to external resources

Everything is rendered nicely in the chat interface.
