# Getting Started

A simple guide to getting up and running with the Agent Chat app.

---

## What Is This App?

Agent Chat is a personal AI assistant that remembers your conversations, learns about the people and pets in your life, tracks events, and helps you get things done. Think of it as a smart companion that gets to know you over time.

Unlike a basic chatbot, this assistant:

- **Remembers** what you've told it across conversations
- **Learns** about your friends, family, pets, and favorite places
- **Finds events** happening near you (Houston area)
- **Syncs with Google Calendar** so nothing falls through the cracks
- **Supports group chats** where multiple people can collaborate with AI help

---

## First Login

### If You're the First User (Admin Setup)

The very first person to use the app creates an admin account. You'll see a "Bootstrap" screen where you enter your email and password. This account becomes the superuser who can invite other users later.

### If You've Been Invited

An admin has already created an account for you. Log in with the email and password they gave you. You can change your password from the user menu afterward.

---

## Initial Setup

Once you're logged in, there are a few things to set up:

### 1. Set Your Timezone

Open the **user menu** (your email address in the top bar), click **Timezone**, and pick yours. This affects how event times are displayed and how the agent understands time-related questions like "What do I have today?" The app can auto-detect your browser's timezone, or you can choose from the list.

### 2. Set Up Your API Key (Optional)

The app uses OpenAI's language models. If the admin has configured a system-wide API key, you don't need to do anything -- it just works. If you want to use your own key:

1. Open the user menu and click **API Key Settings**
2. Paste your OpenAI API key (starts with `sk-`)
3. Click Save

Your key is encrypted before being stored. If a system-wide key is available, it takes priority automatically.

### 3. Connect Google Calendar (Optional)

If you want events from your group chats to sync to your Google Calendar:

1. Open the user menu and click **Google Calendar**
2. Click **Connect Calendar**
3. Sign in with your Google account in the popup
4. Allow the app access to your calendar

You can choose which calendar to sync to and whether to only sync confirmed events. See the Events and Calendar guide for more details.

---

## Your First Conversation

Click on **Chats** in the top navigation to start talking to the agent. Type anything -- ask a question, tell it about your day, or request help with something.

Here are some good first messages to try:

- "What can you do?" -- See what the agent is capable of
- "Tell me a random fact" -- Quick way to test that everything works
- "What time is it?" -- Confirms your timezone is set correctly
- "Tell me about my family" -- After a few conversations, the agent will know who's who

The more you chat, the more the agent learns about you. It picks up on names, pets, places, preferences, and interests automatically.

---

## Understanding the Interface

### Chat Area

The main area shows your conversation. Your messages appear on the right, the agent's replies on the left. The agent can format responses with markdown -- tables, bold text, lists, and more.

### Suggestion Chips

After each response, you may see clickable suggestion buttons below the agent's message. These are contextual follow-ups based on what you just talked about. Click one to send it as your next message.

### Workflow Trace

On the right side (desktop) or via a toggle (mobile), you can see the **Workflow Trace**. This shows what the agent is doing behind the scenes -- analyzing your intent, selecting tools, generating a response. Each step shows its status (complete, skipped, in progress) and timing.

### Sidebar

The left sidebar shows your conversation list. Each conversation gets an auto-generated title. You can switch between conversations or start a new one with the **+** button.

---

## Dark Mode

Click the theme toggle (sun/moon icon) in the top bar to switch between light and dark mode.

## Wrestler Themes

The **Theme** picker in the header dresses the app as one of five wrestlers: "Macho Man"
Randy Savage, Hulk Hogan, Bret "The Hitman" Hart, "Mean" Gene Okerlund or The Ultimate
Warrior. It changes the colors, the headshot, the welcome copy, and the voice the agent
answers in.

Only the voice changes. Facts, numbers, tool results and instructions stay exactly the
same whichever wrestler is on, and you can turn themes off entirely.

The choice belongs to the conversation, not to you or your browser. Open an old
conversation and the app switches back to the wrestler it was spoken in. Pick a
different one partway through and it is saved to that conversation straight away.
Themed conversations show the wrestler's headshot in the sidebar so you can tell them
apart at a glance.

---

## Deep Research

The **Research** tab takes a plain question and produces a written report you can read
or listen to. It is built for questions worth waiting on rather than quick answers.

Three lines of research run at once: academic papers, practical sources like the web and
code repositories, and reported numbers pulled out into tables. Those are reconciled
into one report with citations, charts drawn from the extracted numbers, and figures
taken from the most-cited papers.

- **Depth.** *Quick* does one pass. *Standard* and *Deep* go back for one or two more
  rounds, working out what is missing and searching again.
- **Listen.** Once the report is written, a narration is generated and a **Listen**
  button appears.
- **It keeps going.** A run survives reloading the page or switching tabs. Come back
  later and it re-attaches and replays the progress.

---

## Install It on Your Phone

The app installs to your home screen and opens without browser chrome.

On iPhone, open the app in Safari, tap the **Share** button, and choose **Add to Home
Screen**. On Android, open the browser menu and choose **Install app** or **Add to Home
screen**.

Launched from the home screen it runs standalone, in portrait, with its own icon. On a
wide screen the reading columns grow with the window instead of staying narrow.

---

---

## Getting Help

If you're ever unsure about a feature, just ask the agent! Try messages like:

- "How does the knowledge graph work?"
- "How do groups work?"
- "How do I connect my calendar?"
- "What tools do you have?"

The agent has built-in documentation it can search to answer your questions about the app itself.
