---
name: memory_retrieval
title: Memory retrieval
applies_to: agent
dimensions:
  accuracy:
    1: States memories that contradict the ground-truth memories.
    3: Mostly correct, with one wrong or muddled detail.
    5: Every remembered detail matches the ground-truth memories exactly.
  relevance:
    1: Retrieved/used memories have nothing to do with the question.
    3: Uses some relevant memories alongside irrelevant ones.
    5: Uses exactly the memories the question calls for.
  completeness:
    1: Misses the memories the question depends on.
    3: Recalls some required facts; omits others that were available.
    5: Recalls every required fact that exists in memory.
  no_fabrication:
    1: Invents people, pets, events or details not in memory.
    3: Hedges vaguely or pads with generic filler that reads like memory.
    5: Nothing presented as remembered is absent from memory; says so when it doesn't know.
  context_noise:
    1: Retrieved context is dominated by irrelevant or duplicate items.
    3: Useful items are present but buried in noise.
    5: Retrieved context is tight and ranked well.
---
You are grading how well an assistant used its long-term memory of a user.

GROUND-TRUTH MEMORIES (what the system actually stored about this user before the conversation):
$seed

CONVERSATION (user turns, final assistant reply last):
$transcript

RETRIEVED CONTEXT (what the memory system surfaced for the final turn, with scores/ranks):
$retrieved

WHAT A GOOD ANSWER DOES:
$criteria
