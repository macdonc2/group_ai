# Settings and Account

How to manage your account, API keys, timezone, calendar, and other settings.

---

## Accessing Settings

Click your **email address** in the top bar to open the user menu. Each setting opens
from there as its own panel: Change Password, API Key Settings, Timezone and Google
Calendar, plus Manage Users if you are an admin. There is no combined settings page.

---

## API Key

### What Is the API Key For?

The app uses OpenAI's language models to power the AI agent. These models require an API key to access. There are two ways the app can get an API key:

1. **System-wide key** -- The administrator configures a shared API key for everyone. If this is set up, you don't need to do anything.
2. **Personal key** -- You provide your own OpenAI API key. This is useful if the admin hasn't set up a system key, or if you want to use your own account for billing purposes.

If both exist, the system-wide key is used by default.

### Setting Your API Key

1. Open the user menu and click **API Key Settings**
2. Paste your OpenAI API key (it starts with `sk-`)
3. Click **Save**

Your key is encrypted before being stored in the database. Nobody -- not even administrators -- can see your raw key.

### Checking API Key Status

The settings page shows whether:
- A system-wide key is configured (you don't need your own)
- You have a personal key saved
- No key is configured (you need to add one)

### Removing Your API Key

If you want to switch back to the system-wide key, click **Remove** in the API Key settings.

---

## Timezone

### Why Timezone Matters

Your timezone affects:
- How the agent interprets time references ("tonight", "tomorrow", "this weekend")
- How event times are displayed
- The output of "what time is it?" queries

### Setting Your Timezone

1. Open the user menu and click **Timezone**
2. Choose from the list of common timezones (organized by region: US, Europe, Asia, Oceania)
3. Or click **Auto-detect** to use your browser's timezone

A live preview shows the current time in your selected timezone so you can verify it's correct.

### Default

If you haven't set a timezone, the app defaults to UTC.

---

## Google Calendar

### Connecting Your Calendar

1. Open the user menu and click **Google Calendar**
2. Click **Connect Calendar**
3. Sign in with your Google account in the popup window
4. Grant the app permission to access your calendar
5. You'll see a green "Connected" status with your Google email

### Calendar Settings

Once connected, you can configure:

- **Enable/disable calendar sync** -- Master on/off toggle. When off, no events sync even if you're connected.
- **Select calendar** -- Choose which of your Google Calendars to sync events to. Defaults to your primary calendar. The dropdown shows all calendars you have access to.
- **Sync confirmed only** -- When enabled, only events you've explicitly confirmed in the group events list get synced. When disabled, all extracted events sync automatically.

### Disconnecting

Click **Disconnect** to revoke the app's access to your Google account. Events already on your calendar are not removed.

---

## Password

### Changing Your Password

1. Open the user menu and click **Change Password**
2. Enter your current password
3. Enter your new password
4. Confirm the new password
5. Click **Change Password**

---

## User Management (Admin Only)

If you're a superuser (administrator), you have additional controls:

### Viewing Users

The User Management section shows all registered users with their email, verification status, and account status.

### Managing Users

- **Verify** -- Approve a new user account
- **Deactivate** -- Temporarily disable a user's access without deleting their data
- **Delete** -- Permanently remove a user account and their data

### Searching Users

Use the search function to find users by email. This is also used when adding members to groups.

### Creating Users

As an admin, you can register new user accounts via the **Register** option. New users receive the email and password you set for them.

---

## Agent Preferences

Some settings affect how the agent behaves. You can adjust these by asking the agent directly:

- **Temperature** -- Controls how creative vs. predictable the agent's responses are. Higher values mean more creative, lower values mean more focused.
- **Auto-plan** -- When enabled, the agent automatically creates step-by-step plans for complex tasks instead of answering directly.
- **Verbose responses** -- Controls how detailed the agent's responses are.
- **Default model** -- Which AI model the agent uses for responses.

To change these, just ask the agent:
- "Make your responses more creative" (increases temperature)
- "Give me shorter answers" (adjusts verbosity)
- "Turn on auto-planning" (enables auto-plan)
