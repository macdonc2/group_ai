# Evals

The eval harness measures:
- the agent's routing, tool selection, memory retrieval, entity resolution and end-to-end task completion;
- Deep Research source quality and synthesis groundedness;
- latency and cost for all of the above.

Results, failure analyses and a predicate-tree view of every turn are in the **Evals** tab. It is visible to superusers only.

## How it works

```
datasets/*.yaml ──► seed synthetic user (Neo4j + SQL) ──► real FSM (run_agent_workflow)
                                                          │  TurnTrace: spans, predicates,
                                                          │  retrievals, tool I/O, LLM usage
                                                          ▼
        deterministic scorers ◄── trace + reply + KG snapshot ──► rubric judges (OpenAI / Jev)
                  │                                                     │
                  └──────────► eval_case_results ◄──────────────────────┘
                                      │
                   eval_runs.summary + failure_analysis_md ──► Evals tab
```

- **Tracing** (`adapters/outbound/telemetry/trace.py`).
  - Every agent turn, whether it is real traffic or an eval, records a `TurnTrace`. It holds:
    - node visits with timings;
    - the named predicate behind each branch, with its inputs (`AgentDependencies.decide`);
    - retrieval hits, with scores and whether they reached the prompt;
    - tool calls;
    - per-call LLM usage and cost.
  - LLM usage is captured without touching call sites. pydantic-ai's OpenTelemetry instrumentation feeds a private span processor.
  - Real chat turns are saved to `turn_traces`. `messages.token_count` is now populated.
  - Deep Research stores a usage rollup per stage in `research_jobs.progress.usage`.
- **Datasets** (`src/agent_system/evals/datasets/`).
  - Each case seeds a throwaway `eval-…@evals.invalid` user with known people, pets, places, preferences and backdated past messages.
  - It then plays one or more turns in a single conversation and states expectations.
  - The user is deleted from both stores afterwards.
- **Deterministic scorers** (`evals/scorers.py`):
  - intent;
  - route (ordered subsequence, plus forbidden nodes);
  - tool and argument substrings;
  - recall-in-context, recall@5 and MRR of must-recall facts;
  - required and forbidden phrases in the reply;
  - entity-resolution precision and duplicates against the post-turn graph;
  - latency;
  - research source count, diversity and lane coverage.
- **Judges** (`evals/judges.py`, `evals/rubrics/*.md`).
  - Rubrics have 3–5 dimensions scored 1–5, with anchored descriptions at 1, 3 and 5. They are:
    - `memory_retrieval`
    - `agent_flow`
    - `task_completion`
    - `research_sources`
    - `synthesis_groundedness`
  - A case passes when every deterministic check passes and each judge's mean is at least the suite's `pass_threshold` (default 3.5).
  - Any dimension scored 2 or lower is tagged. On a failing case the tag counts as a failure; on a passing case it is shown as a "flag".
- **Failure analysis** (`evals/failure_analysis.py`).
  - Failed cases are grouped by category. Each group gets its cases, where in the code to look, the evidence, and a short LLM write-up of the pattern, likely cause and fix.

## Running

```bash
make eval-list
make eval-suite SUITE=memory_retrieval JUDGE=both REPEATS=3
make eval                      # all agent suites
python -m agent_system.evals run --suite routing --case plan_trip_task --judge none
python -m agent_system.evals run --suite research --judge openai          # slow; Deep Research at depth 1, no narration
python -m agent_system.evals run --suite routing --fail-under 0.8         # exits 1 below 80% (CI gate)
```

You can also start a run from the Evals tab (**Run suite**). It runs inside the API process, like Deep Research.

**Requirements**
- Neo4j and the database from `.env`.
- `EVAL_OPENAI_API_KEY`, falling back to `OPENAI_API_KEY`.
- On SQLite, cases run one at a time because SQLite allows only one writer.

## Judges

| `--judge` | Uses |
|---|---|
| `openai` | `EVAL_JUDGE_MODEL` (default `openai:gpt-6-astra`) through the Responses API |
| `jev` | `JEV_BASE_URL` + `JEV_MODEL` (+ `JEV_API_KEY`), which is any OpenAI-compatible endpoint. The judge asks for JSON in the prompt rather than through function calling. |
| `both` | Both judges. The run reports agreement: exact, within ±1, and quadratic-weighted Cohen's κ. |
| `none` | Deterministic checks only |

Judge tokens and cost are reported separately from the system under test.

## Cost

Prices come from `genai-prices` when it knows the model. Otherwise set `MODEL_PRICING_JSON`, in USD per 1M tokens:

```json
{"gpt-6-astra": {"input": 0, "cached_input": 0, "output": 0}, "gpt-5.6-luna": {"input": 0, "output": 0}}
```

Calls to models with no known price are counted as *unpriced*. The run then labels its cost as a lower bound.

## The predicate tree

Open a case, or a real conversation under **Evals → Conversations**, and each turn is drawn over the FSM:
- **Solid spine:** the node visits in order. ReAct loops unroll into repeated visits. Each node shows its latency, LLM calls, tokens, tool calls, retrieval hits and the predicates it evaluated (✓ or ✗).
- **Edge labels:** the predicate that chose the next node.
- **Grey dashed leaves:** branches the static graph allowed but this turn didn't take.
- **Red dashed leaves:** nodes the case expected that the run never reached.
- **Colours on visited nodes:** green means expected by the case, red means forbidden.

Click a node to inspect its prompts and outputs, retrieval hits with scores, tool arguments and results, and events. With no node selected, the inspector shows a latency waterfall for the turn.

## Adding a case

Append to a suite YAML. Everything under `expect` is optional; only what you assert is scored.

```yaml
- id: friend_allergy_safety
  seed:
    people: [{name: Zane, relationship_type: friend, context_notes: "allergic to shellfish"}]
  turns: ["Zane's coming over for a seafood boil, what should I make?"]
  expect:
    route: [AnalyzeIntent, CheckPlan, ExecutePlan, GenerateResponse]
    forbid_nodes: [CreatePlan]
    tool: none                 # or a tool name / list of acceptable tools
    must_recall: [shellfish]   # must appear in retrieved context the model saw
    must_mention: [shellfish]
    must_not_mention: ["Zane loves shrimp"]
    entities: [{type: person, name: Zane, aliases: [], relationship_type: friend}]
    forbid_entities: [Pixel]
    answer_criteria: "Warns about the allergy and adapts the menu."
```

## API (superuser)

`/api/v1/evals/…`:
- `suites`
- `runs` (GET, and POST to start a run)
- `runs/{id}` and `runs/{id}/cases`
- `cases/{id}`
- `compare?a=&b=`
- `graph` (the static FSM topology)
- `conversations` and `traces/conversation/{id}` (the caller's own traced conversations)
