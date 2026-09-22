# Evals and Workflow Tracing

How the app measures the assistant's own quality, speed and cost, and how to read the results.

---

## Evals Tab Overview

The **Evals** tab sits next to Chats, Groups and Research. Only **admins (superusers)** can see it. It answers "how well is the assistant doing?" with numbers you can track over time. It covers:
- whether the assistant picks the right path (answering directly, using a tool, or making a plan);
- whether it picks the right tool, with sensible inputs;
- whether it remembers what it knows about you and uses it correctly;
- whether it records new people, pets and places without duplicating or inventing them;
- whether it actually completes the task;
- for Deep Research, the quality of its sources and whether the report is grounded in them;
- how long each step takes and what each response costs.

The tab has two parts. **Eval runs** holds test suites and their results. **Conversations** holds your real chats, which you can open as diagrams or send for grading.

---

## Running an Eval Suite

1. Open **Evals → Eval runs**.
2. Pick a **suite**, a **judge** and a number of **repeats**, then press **Run suite**. Repeats run each test more than once, to show how consistent the assistant is.
3. The run appears in **History** and updates as each test case finishes.

Each test case creates a temporary user with known memories, such as a spouse named Rachel who dislikes cilantro. It then chats with the real assistant and checks the result, and the temporary user is deleted afterwards. Runs use real model calls, so they take a few minutes and cost a small amount.

Administrators can also run evals from the command line with `python -m agent_system.evals` or `make eval`.

---

## Eval Suites and What They Test

- **routing**: does the assistant take the right path? A greeting is answered directly, math goes to the calculator, and a multi-day trip gets a plan. The "Auto-plan" setting is also respected.
- **tool_selection**: does it choose the right tool, and give it good inputs? For example, it should resolve "his hobbies" to "Zane" before searching memory.
- **memory_retrieval**: does it recall and use what it knows? For example, warning that a friend is allergic to shellfish, or not making up a brother it has never heard of.
- **entity_resolution**: after a conversation, is the knowledge graph right? That means no duplicate people, nicknames linked to the right person or pet, and no pets created from hypotheticals like "if I had a cat I'd name it Pixel".
- **e2e_tasks**: full multi-turn and planning tasks, graded on whether the job actually got done.
- **research**: Deep Research source quality, and whether the report's claims are supported by its citations.

---

## Evaluating Your Own Conversations

You can grade real chats, not just test cases:

1. Open **Evals → Conversations**.
2. Tick the conversations you want (up to 50), or use **Select for eval** to tick them all.
3. Choose a judge and press **Evaluate**.

Each conversation is graded on three things:
- **agent flow**: did it route well and use the right tools;
- **task completion**: did it actually help;
- **memory use**: were its claims about you backed by what it actually retrieved.

Real conversations have no answer key, so the memory grader counts any "remembered" detail as a possible fabrication unless it's supported by retrieved memory or something said earlier in the chat.

Conversations from before tracing was added are graded on their transcript and the tools that were called.

You can only see and evaluate your own conversations.

---

## Reading Eval Results

Open a run from **History** to see:
- **Pass rate, latency, cost per case and token usage** at the top.
- **Deterministic checks**: exact tests such as "was the right tool used" or "did the answer mention the allergy", each averaged from 0 to 1.
- **LLM judge scores**: a grader model scores each quality dimension from 1 to 5. When two judges ran, their agreement is shown as well.
- **Node latency**: which workflow steps are slowest.
- **Failure categories**: click one to filter the cases. Examples:
  - `wrong_tool`: the wrong tool was used;
  - `missed_retrieval`: a memory it should have used never reached it;
  - `entity_dup`: a person or pet was saved twice;
  - `judge:agent_flow.efficiency`: a judge gave a low efficiency score.
- **Failure analysis**: a written summary of each failure pattern, where in the system it likely comes from, and a suggested fix.
- **Compare with an earlier run**: which tests newly fail (regressions), which newly pass (fixes), and how each score moved.

Click any case to open its predicate tree, its scores with the judges' reasoning, and, for test cases, what was seeded and what the knowledge graph looked like afterwards.

---

## The Predicate Tree

The predicate tree draws one response as a path through the assistant's workflow:
**ReceiveInput → AnalyzeIntent → UpdateKnowledge → CheckPlan → (CreatePlan) → ExecutePlan → (SelectTool → ExecuteTool → EvaluateResult) → GenerateResponse → FinalizeKnowledge**.

- **Solid boxes** are the steps that ran, in order. Each shows how long it took, how many model calls it made, and the checks it evaluated, with ✓ or ✗ (for example `auto_plan ∧ (requires_planning ∨ intent = task)`).
- **Edge labels** show which check decided the next step.
- **Grey dashed boxes** are paths the workflow could have taken but didn't.
- **Red dashed boxes** are steps a test expected that never happened.
- **Click a step** to see the prompt and output of each model call, the memories retrieved with their similarity scores, and each tool's inputs and results.
- **With no step selected**, a waterfall chart shows where the time went.

---

## Workflow Traces and Cost Tracking

Every chat response is recorded as a trace: the steps it took, the checks behind each decision, what memory returned, which tools ran, and how many tokens each model call used. This powers the predicate tree for real conversations, and it's why each message now carries a token count.

Costs are calculated per model call from known model prices. If a model has no known price, the cost is shown as a **lower bound**, and an administrator can supply prices with the `MODEL_PRICING_JSON` setting.

---

## Eval Judges (OpenAI and Jev)

Quality scores come from a **judge** model that grades against a written rubric. Each score from 1 to 5 has a described meaning, so the scores stay consistent.

- **OpenAI**: the default judge.
- **Jev**: an alternative judge served from its own OpenAI-compatible endpoint. An administrator configures it with `JEV_BASE_URL` and `JEV_MODEL`.
- **Both**: runs both judges and shows how often they agree, as a sanity check on the scores.

Judge costs are reported separately from the assistant's own costs.

---

## Eval Troubleshooting

- **I don't see the Evals tab.** Only admins (superusers) can see it.
- **A run shows "interrupted".** The server restarted while the run was going. Start it again.
- **Costs show "unpriced" or "lower bound".** Some models have no known price; an administrator can add prices with `MODEL_PRICING_JSON`.
- **The Jev judge fails.** Jev needs `JEV_BASE_URL` to be configured.
- **A conversation has no diagram.** Older conversations have no trace. They can still be evaluated from their transcript.
