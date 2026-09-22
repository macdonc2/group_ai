---
name: task_completion
title: End-to-end task completion
applies_to: agent
dimensions:
  goal_achieved:
    1: The user's goal is not met.
    3: Partly met; the user must follow up for the core of it.
    5: Fully met in this reply.
  correctness:
    1: Contains factual or logical errors that matter.
    3: Minor inaccuracies.
    5: Correct throughout.
  helpfulness:
    1: Unhelpful, evasive or off-topic.
    3: Adequate but generic.
    5: Specific, well organised and personalised where memory allows.
---
You are grading whether an assistant completed the user's task.

CONVERSATION (final assistant reply last):
$transcript

KNOWN FACTS ABOUT THE USER (ground truth):
$seed

TOOLS THAT RAN AND THEIR OUTPUT:
$tool_outputs

WHAT DONE LOOKS LIKE:
$criteria
