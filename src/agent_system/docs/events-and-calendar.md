# Events and Calendar

How events work in the app, including personal events, Houston area events, and Google Calendar sync.

---

## Types of Events

There are two main sources of events in the app:

### 1. Group Chat Events (Personal/Extracted)

These are events the system automatically detects from your group conversations. When someone says "Let's grab dinner at Underbelly on Friday at 7," the agent extracts that as an event with a title, date, time, and location.

You can ask about these events with messages like:

- "What do I have planned this week?"
- "Any upcoming meetings?"
- "What happened last week?"

### 2. Houston Area Events (Discovery)

The app has a curated database of events happening in the Houston area -- concerts, cycling rides, sports, arts, food festivals, comedy shows, and more. This database is powered by the htown_mania event discovery system.

You can search these with messages like:

- "What's happening in Houston this weekend?"
- "Any cycling events coming up?"
- "Show me concerts tonight"
- "What's going on in Montrose?"

---

## Asking About Events

### Personal Events

To ask about your own extracted events, just talk naturally:

| What You Say | What Happens |
|---|---|
| "What do I have planned?" | Shows all upcoming events |
| "What's on my schedule today?" | Shows today's events |
| "Any meetings this week?" | Filters by keyword "meeting" this week |
| "When is my haircut?" | Searches for events matching "haircut" |
| "What did I do last week?" | Shows past events from last week |

The agent understands timeframes like "today", "tomorrow", "this week", "this month", and specific dates like "January 30th."

### Houston Events

For area events, the agent searches the Houston events database:

| What You Say | What Happens |
|---|---|
| "Houston events this weekend" | Searches all upcoming Houston events |
| "Any concerts tonight?" | Filters by music/concert category |
| "Cycling events near me" | Filters by cycling category |
| "What's happening in the Heights?" | Searches by location/neighborhood |

Results come back as a formatted table with event name, date, location, and description.

---

## Google Calendar Sync

You can connect your Google Calendar so that events extracted from group chats automatically sync to your calendar.

### Setting Up Calendar Sync

1. Open the **user menu** (your email address in the top bar)
2. Click **Google Calendar**
3. Click **Connect Calendar**
4. A popup opens asking you to sign in with your Google account
5. Allow the app to access your calendar
6. Once connected, you'll see your Google email and a green "Connected" status

### Calendar Settings

After connecting, you can configure:

- **Enable/Disable sync** -- Master toggle for calendar sync
- **Select calendar** -- Choose which Google Calendar to sync events to (defaults to your primary calendar)
- **Sync confirmed only** -- If enabled, only events you've explicitly confirmed get synced. If disabled, all extracted events sync automatically.

### How Sync Works

When an event is extracted from a group chat:

1. The event appears in the group's event list
2. If you have calendar sync enabled, it gets pushed to your Google Calendar
3. The event includes the title, description, date/time, and location
4. Each group member's calendar syncs independently based on their own settings

### Sync Status

Each event shows a sync status:

- **Pending** -- Not yet synced
- **Synced** -- Successfully added to your Google Calendar
- **Failed** -- Sync attempted but failed (check your calendar connection)
- **Not enabled** -- Calendar sync is turned off

### Manual Sync

You can also manually sync individual events by clicking the sync button next to an event in the group's event list.

### Disconnecting

To disconnect your calendar:

1. Open the **user menu** and click **Google Calendar**
2. Click **Disconnect**

This revokes the app's access to your Google Calendar. Events already synced remain on your calendar.

## Adding Events Yourself

Sync (above) handles events the agent pulled out of group chats. You can also just ask
the agent to put something on your calendar.

| What You Say | What Happens |
|---|---|
| "Put dinner at Underbelly Friday at 7 on my calendar" | Creates that one event, read in your timezone |
| "Add the ones you suggested, as tentative" | Creates all of them, marked tentative |
| "Add the Saturday ride to my calendar" | Matches the Houston event and uses its real date, venue and link |

Things worth knowing:

- **Several at once.** You can add a whole list from the agent's last suggestions in a single message.
- **Tentative.** Ask for them as tentative and they are created unconfirmed, so they show that way in Google Calendar.
- **Houston events.** When the title matches the Houston events database, the real date, venue and link come with it.
- **Missing dates.** In a list, an event with no date becomes an all-day placeholder on the coming Saturday. Ask for a single event with no date and the agent asks you for one rather than guessing.
- **Not connected yet.** If your Google Calendar isn't connected, the agent says so and points you at the user menu.

---

---

## Event Extraction Details

The agent uses AI to detect events in group messages. Here's what it looks for:

### Event Types

- **Meeting** -- Gatherings of people ("Let's meet at the park")
- **Deadline** -- Due dates ("The report is due Friday")
- **Activity** -- Social/fun events ("We should check out that new restaurant")
- **Obligation** -- Tasks or commitments ("Don't forget to bring the cooler")

### Smart Date Parsing

The system understands natural date references:

- "tonight" -- Today at 6 PM
- "tomorrow" -- Tomorrow at 9 AM
- "next Friday" -- The coming Friday
- "this weekend" -- Saturday
- "January 15th" -- Specific date

All times are interpreted in your configured timezone.

### Confidence Scores

Each extracted event has a confidence score. Events below 70% confidence are not saved, reducing false positives. High-confidence events (things like "dinner at 7 at Underbelly on Friday") are saved automatically.

### What Doesn't Get Extracted

- Messages that start with @agent (those are questions to the AI, not event announcements)
- Vague statements without enough detail ("we should hang out sometime")
- Past tense recollections ("we went to the park yesterday") -- these are memories, not future events
