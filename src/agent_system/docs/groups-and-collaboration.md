# Groups and Collaboration

How to use group chats for real-time collaboration with other people and the AI agent.

---

## What Are Groups?

Groups let multiple users chat together in real time, with the AI agent available to help the whole group. Group conversations are great for:

- Planning events with friends or family
- Coordinating schedules
- Having group discussions where the agent can look things up or recall past conversations
- Extracting and tracking events mentioned in chat

---

## Creating a Group

1. Click **Groups** in the top navigation
2. Click the **+** button or **Create Group**
3. Enter a group name (e.g., "Family Plans", "Weekend Crew")
4. Optionally add a description
5. Click **Create**

You become the group **owner**, which gives you admin controls over the group.

---

## Adding Members

Only the group owner can add new members:

1. Open the group
2. Click the members panel (right sidebar on desktop)
3. Click **Add Member**
4. Search for a user by email
5. Click to add them

Members can only be added if they already have an account in the app.

---

## Real-Time Messaging

Group chat works in real time -- messages appear instantly for all members who are online. You'll see:

- Who sent each message
- Online status indicators for members
- The group member list in the right sidebar

---

## Using the AI Agent in Groups

To get the agent's help in a group chat, mention it by typing **@agent** or **@assistant** in your message. For example:

- "@agent what's the weather this weekend?"
- "@agent tell me a joke"
- "@agent what events are happening in Houston?"

The agent responds in the group chat where everyone can see. It has access to the same tools as in individual chats (web search, events, knowledge graph, etc.).

When you don't mention the agent, your message is just a regular group message between the human members.

---

## Event Extraction

One of the most powerful group features is **automatic event extraction**. When someone mentions an event in a group message, the agent automatically detects and saves it.

For example, if someone types "Let's meet at Buffalo Bayou Park tomorrow at 3pm," the system will:

1. Detect that this is an event
2. Extract the title, location, date, and time
3. Save it as a group event
4. Notify group members via a real-time update

### What Gets Extracted

The system looks for:

- **Meetings** -- "Let's meet at..."
- **Deadlines** -- "The report is due Friday"
- **Activities** -- "We should go to the concert Saturday night"
- **Obligations** -- "Don't forget to pick up the cake"

Each extracted event includes:

- Title
- Date and time (interpreted from phrases like "tomorrow", "next Friday", "tonight at 7")
- Location (if mentioned)
- Event type (meeting, deadline, activity, obligation)
- Confidence score

### Managing Events

View extracted events in the group's events panel. You can:

- **Confirm** -- Mark an event as confirmed
- **Edit** -- Update the title, time, or details
- **Delete** -- Remove events that were incorrectly detected
- **Sync to Calendar** -- Push confirmed events to your Google Calendar

---

## Group Summaries

Each group has a summary feature that aggregates what the group has been talking about. This includes:

- Key themes and topics discussed
- Activity patterns
- Social suggestions based on group interests

---

## Privacy Controls

Each group member has a **sharing_enabled** toggle that controls whether their messages are included in group summaries and AI analysis.

- **Sharing enabled** (default) -- Your messages contribute to group summaries and the agent's understanding of group discussions
- **Sharing disabled** -- Your messages are still visible to other members but won't be included in AI summaries

To toggle this:

1. Open the group
2. Go to the members panel
3. Find your name and toggle the sharing switch

---

## Member Management

### Owner Controls

The group owner can:

- Add new members
- Remove any member
- Update group name and description
- Delete the group entirely

### Member Controls

Regular members can:

- Leave the group (click your name in the members list)
- Toggle their privacy/sharing settings
- View all group conversations and events

### Ownership

The group owner cannot leave the group. To step away, they need to delete the group or (in future) transfer ownership.

---

## Group Conversations

Within a group, you can have multiple conversation threads. Each conversation is a separate chat history within the same group. This keeps different topics organized.

- **Create a new conversation** to start a fresh topic
- **Switch between conversations** in the group sidebar
- **Delete conversations** you no longer need
