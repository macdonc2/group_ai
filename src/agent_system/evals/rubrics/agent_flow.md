---
name: agent_flow
title: Agent flow & tool use
applies_to: agent
dimensions:
  routing:
    1: The workflow took a clearly wrong path (e.g. planned a trivial question, skipped a needed tool).
    3: Reasonable path with a questionable branch.
    5: Every branch decision fits the request.
  tool_choice:
    1: Wrong tool, or no tool when one was plainly needed.
    3: A workable but not ideal tool.
    5: The best available tool (or correctly none).
  argument_quality:
    1: Tool arguments are wrong, empty or unresolved ("his", "it").
    3: Arguments work but lose specifics from the request.
    5: Arguments carry exactly the resolved entities, dates and terms needed.
  efficiency:
    1: Many wasted LLM calls/steps or loops.
    3: Some redundant steps.
    5: Minimal steps for the job.
  recovery:
    1: An error or empty result was ignored or papered over.
    3: Partial handling of a failure.
    5: Failures (if any) were handled and surfaced honestly; score 5 when nothing failed.
---
You are grading the control flow of an agent built as a finite-state machine.
FSM nodes: ReceiveInput → AnalyzeIntent → UpdateKnowledge → CheckPlan → (CreatePlan) → ExecutePlan → (SelectTool → ExecuteTool → EvaluateResult)* → GenerateResponse → FinalizeKnowledge.

AVAILABLE TOOLS (names): $tools

USER REQUEST (final turn) and prior turns:
$transcript

EXECUTION TRACE (node path, branch predicates with inputs, tool calls, LLM call counts):
$flow

WHAT A GOOD RUN DOES:
$criteria
