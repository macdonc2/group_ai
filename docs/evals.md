# Evals and tracing

The eval harness measures how the agent behaves. It covers:
- routing, tool selection, memory retrieval and entity resolution;
- end-to-end task completion;
- Deep Research source quality and synthesis groundedness;
- latency and cost for all of the above.

It runs two ways: against **seeded synthetic users**, where the right answer is known, and against **your real conversations**, which are judged with rubrics only. Results, failure analyses and a predicate-tree view of every turn are in the **Evals** tab. The tab is visible to superusers only.

Contents:
- [How it fits together](#how-it-fits-together)
- [Turn tracing](#turn-tracing)
- [Suites and cases](#suites-and-cases)
- [Scoring](#scoring)
- [Judges and rubrics](#judges-and-rubrics)
- [Evaluating real conversations](#evaluating-real-conversations)
- [Failure analysis](#failure-analysis)
- [Running evals](#running-evals)
- [The Evals tab](#the-evals-tab)
- [Latency and cost](#latency-and-cost)
- [Configuration](#configuration)
- [Storage](#storage)
- [API](#api)
- [Extending](#extending)
- [Operations and known issues](#operations-and-known-issues)
- [Testing the harness](#testing-the-harness)

---

## How it fits together

```
                ┌──────────────────── dataset suites (YAML) ─────────────────────┐
                │                                                                │
  seed synthetic user (Neo4j + SQL) ──► real FSM: run_agent_workflow ──► TurnTrace
                                                                            │
  your real conversations (messages + turn_traces) ─────────────────────────┤
                                                                            ▼
        deterministic scorers ◄── trace, reply, KG snapshot ──► rubric judges (OpenAI / Jev / both)
                  │                                                         │
                  └────────────────► eval_case_results ◄────────────────────┘
                                             │
                     eval_runs.summary + failure_analysis_md ──► Evals tab / CLI
```

| Piece | Where |
|---|---|
| Turn tracing | `adapters/outbound/telemetry/trace.py`, `fsm/workflow.py`, `fsm/state.py` |
| Datasets | `src/agent_system/evals/datasets/*.yaml`, schema in `evals/schema.py` |
| Seeding and teardown | `evals/seed.py` |
| Runner (suites and conversations) | `evals/runner.py` |
| Real-conversation loader | `evals/conversations.py` |
| Deterministic scorers | `evals/scorers.py` |
| Judges and rubrics | `evals/judges.py`, `evals/rubrics/*.md` |
| Failure analysis | `evals/failure_analysis.py` |
| CLI | `evals/__main__.py` (`python -m agent_system.evals`) |
| API | `adapters/inbound/api/routes/evals.py` (`/api/v1/evals`) |
| Tables | `adapters/outbound/persistence/eval_models.py` |
| UI | `frontend/src/components/evals/`, `frontend/src/stores/evalStore.ts` |

---

## Turn tracing

Every agent turn records a `TurnTrace`, whether it comes from a chat, a group chat or an eval. `run_agent_workflow` drives the graph with `agent_workflow.iter(...)`. That lets it open a timed span for each node visit and bind the trace and the current node to context variables.

| Field | What it holds |
|---|---|
| `path`, `spans` | Every node visit in order, with start, end and duration. ReAct loops appear as repeated visits. Each span also carries the tokens, LLM time and cost of that visit. |
| `decisions` | The **named predicate** behind each branch, with its result, the next node and its inputs. Recorded with `AgentDependencies.decide(...)`. |
| `retrievals` | Hits from `semantic_search`, `graph_suggestions`, `entity_lookup` and the recall tools, with scores and `used_in_prompt`. |
| `tool_calls` | Tool name, arguments, result, success and duration. |
| `llm_calls` | Per model request: agent, model, input/output/cached tokens, duration, cost, a preview of the prompt and output, and `role` (`system` or `judge`). |
| `embedding_calls` | Embedding model, tokens, duration and cost. |
| `usage` / `judge_usage` | Rollups, including the number of `unpriced_calls`. |

**How LLM calls are captured.** pydantic-ai's OpenTelemetry instrumentation is switched on for every `Agent` with a private tracer provider (`install_llm_capture()`). Its only span processor turns `chat` spans into `LLMCall` records on whichever trace is bound. Nothing is exported, and no call site had to change.
- Model-request spans are identified by `gen_ai.operation.name == "chat"`.
- The processor subclasses the SDK's `SpanProcessor` and never raises.

**Predicates currently recorded:**

| Node | Predicate |
|---|---|
| `AnalyzeIntent` | intent from primary / fallback model / keyword heuristics |
| `CheckPlan` | `active_plan ∧ plan.is_active` |
| `CheckPlan` | `auto_plan ∧ (requires_planning ∨ intent = task)` |
| `ExecutePlan` | `react_mode ∧ plan` |
| `ExecutePlan` | `step N: needs_tool ∧ tool_suggestion` |
| `ExecutePlan` | `requires_tool ∧ tool_name` |
| `ExecutePlan` | `plan.current_step.tool_required` |
| `EvaluateResult` | `¬plan.is_complete` |
| `GenerateResponse` | `react_mode ∧ step_results` |
| `GenerateResponse` | structured-data and markdown-table bypasses |

**Where traces are stored.**
- **Chat turns:** written to `turn_traces` inside the same transaction as the turn's messages.
- **Group chat turns:** written in a short session of their own.
- **Deep Research:** stores a per-stage rollup (`lane:*`, `synthesis`, `writer`, …) in `research_jobs.progress.usage`.
- **Messages:** `messages.token_count` is now filled in.

To add a branch to the tree, wrap the condition in `ctx.deps.decide(node, "readable predicate", result, next_node, **inputs)`. It returns `result`, so it drops straight into an `if`.

---

## Suites and cases

| Suite | Kind | Cases | Rubrics | What it covers |
|---|---|---|---|---|
| `routing` | agent | 15 | agent_flow | Intent and the FSM path it drives: direct answer, tool, or plan. Also covers `auto_plan` off and clarifications that shouldn't re-run a tool. |
| `tool_selection` | agent | 16 | agent_flow | Right tool, plus usable arguments with pronouns and references resolved (math, definitions, docs, web, recall, time). |
| `memory_retrieval` | agent | 16 | memory_retrieval, task_completion | Recalling seeded people, pets, places, preferences and backdated messages. Includes aliases, multi-hop links, temporal recall, no fabrication, and no false links. |
| `entity_resolution` | agent | 15 | none (deterministic) | Knowledge-graph state after `FinalizeKnowledge`: new vs. existing entities, aliases, nicknames, relationship changes, no duplicates, no spurious entities. |
| `e2e_tasks` | agent | 10 | task_completion, agent_flow | Multi-turn and planning tasks judged end to end, including honesty about what it can't do. |
| `research` | research | 4 | research_sources, synthesis_groundedness | Deep Research at depth 1 with narration off. |

**Case schema** (`evals/schema.py`). Every `expect` field is optional; only what a case asserts is scored.

```yaml
- id: friend_allergy_safety              # unique within the suite
  description: optional
  seed:                                  # what the throwaway user "already knows"
    people:      [{name: Zane, relationship_type: friend, aliases: [], context_notes: "allergic to shellfish"}]
    pets:        [{name: Roxanne, species: dog, breed: boxer, personality: [goofy], food_preferences: [ham bones]}]
    locations:   [{name: "Winnie's", location_type: bar, city: Houston, neighborhood: Midtown}]
    preferences: [{category: drinks, value: IPAs, sentiment: -0.8}]
    messages:    [{content: "I started drinking cold brew after 3pm", role: user, days_ago: 10}]   # embedded + backdated
    links:       [{source_type: person, source_name: Zane, relationship: lives_in, target_type: location, target_name: Montrose}]
    auto_plan: true
  turns: ["Zane's coming over for a seafood boil, what should I make?"]   # played in one conversation
  expect:                                # applies to the last turn (entities: final graph state)
    intent: question                     # or a list of acceptable intents
    route: [AnalyzeIntent, CheckPlan, ExecutePlan, GenerateResponse]      # ordered subsequence of the path
    route_exact: false
    forbid_nodes: [CreatePlan]
    tool: none                           # a tool, a list of acceptable tools, or "none"
    tool_args: {query: shellfish}        # case-insensitive substring per argument
    must_recall: [shellfish]             # must appear in context the model actually saw
    must_mention: [shellfish]            # must appear in the reply
    must_not_mention: ["Zane loves shrimp"]
    entities: [{type: person, name: Zane, aliases: [], relationship_type: friend}]
    forbid_entities: [Pixel]
    no_duplicate_entities: true
    answer_criteria: "Warns about the allergy and adapts the menu."   # given to the judge
    max_latency_ms: 60000
  rubrics: [memory_retrieval]            # optional override of the suite's rubrics
```

Research cases take `question`, `depth`, `min_sources`, `expect_lanes` and `answer_criteria`.

**Seeding and isolation.**
- Each case gets a user `eval-<run>-<rand>@evals.invalid`.
- People, pets, places, preferences and links are written with the normal `Neo4jAdapter` methods.
- Past messages are embedded and saved as backdated `MessageEmbedding`s.
- The user is removed afterwards: in Neo4j by `user_id`, and in SQL by deleting the user, which cascades.
- Every write is scoped by user, so evals can safely run against the production database.

---

## Scoring

**Deterministic scorers** (`evals/scorers.py`). Each score is between 0 and 1 and carries a failure tag.

| Score | Passes when | Tag |
|---|---|---|
| `intent` | The detected intent is one of the expected intents | `wrong_intent` |
| `route` | The expected nodes appear in order and no forbidden node was visited | `wrong_route` |
| `tool` | An expected tool ran, or no tool ran when the case expects `none` | `wrong_tool` |
| `tool_args` | Each expected argument substring is present | `bad_args` |
| `recall` | Every `must_recall` fact reached the model's context. Also reports `recall@5` and MRR. | `missed_retrieval` |
| `mentions` | The reply contains every `must_mention` | `incomplete_answer` |
| `no_hallucination` | The reply contains no `must_not_mention` | `hallucinated_memory` |
| `entity_resolution` | Each expected entity exists with its aliases linked and the right relationship or species | `entity_miss` |
| `entity_dedup` | No expected entity is split across several nodes | `entity_dup` |
| `no_spurious_entities` | No forbidden entity was created | `entity_spurious` |
| `latency` | The turn is within `max_latency_ms` | `slow` |
| research: `source_count`, `source_diversity`, `lane_coverage`, `citable_sources` | minimum sources met, ≥50% distinct domains, every expected lane produced findings, every source has a URL | `thin_sources`, `low_diversity`, `lane_empty`, `uncitable_source` |

**Pass rule.** A case passes when all of these hold:
- every deterministic score passes;
- each judge's mean across the rubrics is at least the suite's `pass_threshold` (default 3.5);
- no turn raised an error.

**Tags from judges.** A judge dimension scored 2 or lower adds the tag `judge:<rubric>.<dimension>`. On a failing case it counts as a failure; on a passing case it is reported as a **flag**.

---

## Judges and rubrics

**Rubrics** live in `evals/rubrics/*.md`. Each file has YAML front matter giving the dimensions, with anchor descriptions at 1, 3 and 5, and a `string.Template` body with `$placeholders`. Every dimension is scored as an integer from 1 to 5.

| Rubric | Dimensions | Sees |
|---|---|---|
| `memory_retrieval` | accuracy, relevance, completeness, no_fabrication, context_noise | ground-truth memories, transcript, retrieved context with scores |
| `agent_flow` | routing, tool_choice, argument_quality, efficiency, recovery | the transcript and the execution trace: path, predicates with inputs, tool calls, LLM calls per node |
| `task_completion` | goal_achieved, correctness, helpfulness | transcript, known facts, tool outputs |
| `research_sources` | relevance, authority, recency, diversity | the question and the sources |
| `synthesis_groundedness` | claims_supported, citation_accuracy, coverage | numbered sources and the report |

**Judges** (`evals/judges.py`) share the `JudgePort.score(rubric, context)` interface:

| `--judge` | Model |
|---|---|
| `openai` | `EVAL_JUDGE_MODEL` (default `openai:gpt-6-astra`), through the Responses API with tool-based structured output |
| `jev` | `JEV_MODEL` at `JEV_BASE_URL`, with `JEV_API_KEY` if needed. Any OpenAI-compatible server works. It uses **prompted JSON output** (`PromptedOutput`) rather than function calling, because compatible servers vary. |
| `both` | Runs both. The run reports **agreement**: exact match, within ±1, and quadratic-weighted Cohen's κ. |
| `none` | Deterministic checks only |

Judge calls run under `llm_role("judge")`, so their tokens and cost are reported separately from the system under test.

---

## Evaluating real conversations

Under **Evals → Conversations**, tick any of your conversations (up to 50) and press **Evaluate**. You can also send `POST /api/v1/evals/runs` with `conversation_ids`.

**Turns.** Each conversation is rebuilt from its stored messages, pairing each user message with the assistant reply that follows it. A turn's `TurnTrace` is attached when there is one, matched by the user's text.
- **Conversations from before tracing** are judged on the transcript plus the tool calls stored on the assistant's messages.
- **With traces**, the judge also sees the path, predicates, retrievals and tool I/O of every turn.

**Rubrics.** The defaults are `agent_flow`, `task_completion` and `memory_retrieval`; you can override them with `rubrics`.

**No ground truth.** Real conversations have no known-correct answers, so the memory judge is told to count a remembered detail as a possible fabrication unless it's supported by the retrieved context or earlier turns.

**What you can pick.** Only the caller's own conversations can be listed or evaluated.

**Results.** They appear as a run of the `conversations` suite, with one case per conversation, named by its title. There are no deterministic checks, only judge scores; the pass rule is the same judge-mean threshold.

---

## Failure analysis

After a run, failed cases are grouped by category, and a case with several tags in one category is counted once. Each group gets:
- the cases in it;
- **Where to look**: a pointer into the code, taken from the map in `failure_analysis.py`;
- the evidence: user message, reply, path, predicates, tool calls, failing scores, and low judge scores with rationales;
- a short LLM write-up covering **Pattern**, **Likely cause** and **Suggested fix**, generated by the judge model from that evidence only.

The analysis is stored as markdown on `eval_runs.failure_analysis_md`. It's shown in the tab and with `--show-analysis`.

---

## Running evals

```bash
make eval-list                                            # suites, case counts, rubrics
make eval                                                 # all agent suites, OpenAI judge
make eval-suite SUITE=memory_retrieval JUDGE=both REPEATS=3
python -m agent_system.evals run --suite routing --case plan_trip_task --case greeting --judge none
python -m agent_system.evals run --suite research --judge openai          # slow (minutes per case)
python -m agent_system.evals run --suite routing --fail-under 0.8         # exit 1 below 80% (CI gate)
```

| Flag | Meaning |
|---|---|
| `--suite` | Suite name. Repeat the flag to run several suites in sequence. |
| `--case` | Only these case ids. Repeatable. |
| `--judge` | `openai`, `jev`, `both` or `none` |
| `--repeats` | Run each case N times to measure variance |
| `--concurrency` | Parallel cases (default 2; forced to 1 on SQLite) |
| `--no-analysis` / `--show-analysis` | Skip, or print, the failure write-up |
| `--fail-under` | Pass-rate threshold for the exit code |

**What it needs:**
- Neo4j and the database configured in `.env`;
- `EVAL_OPENAI_API_KEY`, falling back to `OPENAI_API_KEY`.

**In production** you can run it inside the backend pod:

```bash
kubectl exec -n agent-system deploy/agent-system-backend -- \
  python -m agent_system.evals run --suite routing --judge openai
```

**From the tab:** pick a suite, a judge and a repeat count, then press **Run suite**. The run executes inside the API process, like Deep Research. Its row is created before the request returns, and the view refreshes every few seconds until the run finishes.

---

## The Evals tab

**Eval runs**
- **History.** Each run shows its suite, judge, pass rate and status: `running`, `complete`, `failed` or `interrupted`.
- **Scorecard:**
  - pass rate, turn latency (p50 and p95), cost per case, tokens;
  - deterministic check means;
  - judge means per `rubric.dimension`, per judge, plus agreement when `both` ran;
  - node latency (p95);
  - failure categories and flags, which you can click to filter the case table.
- **Cases.** Result, failure tags, judge mean, latency and cost. Click one to open it:
  - **Predicate tree:** see below;
  - **Scores & judges:** every deterministic check with its detail, and every judge dimension with its rationale;
  - **Seed & knowledge graph:** what was seeded, the expectations, and the social graph after the run. Not shown for real conversations or research cases.
- **Failure analysis:** the markdown write-up.
- **Compare with an earlier run** of the same suite: metric deltas, regressions (passed before, fails now) and fixes.

**Conversations**
- The list of your conversations, each showing how many turns were traced.
- Click a conversation to see each turn as a predicate tree.
- Tick conversations and press **Evaluate** to judge them.

**Reading the predicate tree**

| Element | Meaning |
|---|---|
| Solid spine | Node visits in order. Each node shows its latency, LLM calls and tokens, tools, retrieval hits, and the predicates it evaluated (✓ or ✗). |
| Edge label | The predicate that chose the next node, with its result |
| Grey dashed leaf | A branch the static FSM allows that this turn didn't take. The leaf shows the static edge label. |
| Red dashed leaf, marked "expected" | A node the case expected that the run never reached |
| Green border / red border | The visit was expected by the case, or forbidden by it |
| Click a node | Opens that node's predicates with their inputs, LLM calls with prompt and output previews, retrieval hits with scores, and tool arguments and results |
| No node selected | The inspector shows the whole turn: latency, cost, tokens, and a waterfall of node timings |

---

## Latency and cost

- **Latency.** Each span's wall time, LLM time inside the span, turn totals, and p50/p95 per node and per turn.
- **Cost.** `price_usd(model, input, output, cached)` prices each call:
  1. `MODEL_PRICING_JSON` is used first. It's how unreleased or private models get a price.
  2. Otherwise `genai-prices` is used.
  3. A model neither knows is counted as **unpriced**, and every total that includes one is labelled a **lower bound**.

```json
{"gpt-6-astra": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
 "gpt-5.6-luna": {"input": 0.0, "output": 0.0}}
```

Prices are USD per 1M tokens; fill in the real rates. Prefix matching applies, so `"gpt-6"` covers every `gpt-6-*` model.

---

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `EVAL_OPENAI_API_KEY` | falls back to `OPENAI_API_KEY` | Key for the system under test and the OpenAI judge |
| `EVAL_JUDGE_MODEL` | `openai:gpt-6-astra` | OpenAI judge and failure-analysis model |
| `JEV_BASE_URL` | unset (Jev disabled) | OpenAI-compatible endpoint for the Jev judge |
| `JEV_MODEL` | `jev` | Model id served there |
| `JEV_API_KEY` | unset | Key for that endpoint, if it needs one |
| `MODEL_PRICING_JSON` | `{}` | Per-model prices, as above |
| `LLM_REQUEST_TIMEOUT_S` | `120` | Per-request timeout for chat-path LLM calls |
| `RESEARCH_REQUEST_TIMEOUT_S` | `600` | Per-request timeout for Deep Research LLM calls |
| `LLM_MAX_RETRIES` | `1` | Retries after a failed or timed-out LLM request |
| `GIT_SHA` | baked in by `make build-backend` | Recorded on each run for comparisons |

**Helm.**
- `EVAL_JUDGE_MODEL`, `JEV_BASE_URL` and `JEV_MODEL` are in `values.yaml` under `env`.
- `EVAL_OPENAI_API_KEY`, `JEV_API_KEY` and `MODEL_PRICING_JSON` go in the `agent-system-secrets` secret, which the backend reads through `envFrom`.

---

## Storage

These are new tables, created by `create_all` at startup; the project has no migration tool.

| Table | Contents |
|---|---|
| `turn_traces` | One row per real chat or group turn: `path`, the full `trace` as JSON, `total_ms`, tokens, `cost_usd` |
| `eval_runs` | `suite`, `status`, `judge`, `git_sha`, `config` (including `origin`: `api` or `cli`), `summary`, `failure_analysis_md`, `error` |
| `eval_case_results` | Per case and repeat: `passed`, `failure_tags`, `case`, `scores`, `judgements`, `turns` (with traces), `total_ms`, `cost_usd`, `judge_cost_usd`, `error`. For entity cases the graph snapshot is stored under `judgements._snapshot`. |

At startup, runs still marked `running` are set to `interrupted` if they were started from the API or are more than 12 hours old. CLI runs may be alive in another process, so newer ones are left alone.

---

## API

All endpoints are under `/api/v1/evals` and require a superuser.

| Method | Path | Purpose |
|---|---|---|
| GET | `/suites` | Suites with case ids and rubrics |
| GET | `/rubrics/{name}` | A rubric's dimensions and anchors |
| GET | `/runs?suite=` | Run history, with cases done so far |
| POST | `/runs` | Start a run: `{suite, judge, repeats, concurrency, case_ids}` or `{conversation_ids, judge, rubrics}` |
| GET | `/runs/{id}` | Run detail: config, summary, failure analysis |
| GET | `/runs/{id}/cases` | Case rows |
| GET | `/cases/{id}` | Full case result, including turns and traces |
| GET | `/compare?a=&b=` | Metric deltas, regressions and fixes (`a` is the baseline) |
| GET | `/graph` | Static FSM topology used by the tree |
| GET | `/conversations` | The caller's conversations, with message and traced-turn counts |
| GET | `/traces/conversation/{id}` | Turns of one of the caller's conversations, with `trace` or `null` |
| GET | `/traces/{id}` | One stored turn trace |

```bash
curl -X POST https://agent.macdonml.com/api/v1/evals/runs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"suite":"memory_retrieval","judge":"both","repeats":2}'
```

---

## Extending

- **Add a case:** append it to a suite YAML. `make eval-list` validates the file, and `tests/unit/evals/test_scorers.py::test_suites_load` checks every suite parses with unique ids.
- **Add a suite:** create a new `datasets/<name>.yaml` with `name`, `description`, `rubrics`, `pass_threshold` and `cases`. Set `kind: research` for research cases.
- **Add a rubric:** create `rubrics/<name>.md` with YAML front matter (3–5 dimensions, each anchored at 1, 3 and 5) and a template using any of these placeholders:
  - `$seed`, `$transcript`, `$retrieved`, `$criteria`, `$flow`, `$tools`, `$tool_outputs`;
  - for research: `$question`, `$sources`, `$report`.
- **Add a scorer:** write a function in `scorers.py` that returns a `Score(name, score, passed, tag, detail)`, and call it from `score_agent_case`. Add the tag's code location to `SUSPECTS` in `failure_analysis.py`.
- **Add a judge:** subclass `_AgentJudge` with a `name` and a model, and add it to `build_judges`.
- **Trace a new branch:** see `decide(...)` under [Turn tracing](#turn-tracing).

---

## Operations and known issues

- **Where runs execute.** Runs execute in the backend process. A backend rollout interrupts them; the run is marked `interrupted`, and the throwaway users are removed by the teardown in each case's `finally`.
- **SQLite for local dev.** SQLite allows only one writer at a time. Eval cases therefore run one at a time, and chat traces are written through the request's own session. Postgres has no such limit.
- **Production doesn't use the tested library versions.** The backend image installs from the version ranges in `pyproject.toml`, not from `uv.lock`, so production runs newer libraries than local tests. For example: pydantic-ai 1.107 vs 1.56, openai 3.18 vs 2.17, opentelemetry-sdk 1.44 vs 1.39. Two consequences so far:
  - An OpenTelemetry hook added in the newer SDK broke every LLM call until the span processor was changed to subclass `SpanProcessor` (2026-09-22).
  - With pydantic-ai 1.107 and openai 3.18, Responses API calls report **zero tokens**. Production traces therefore show 0 tokens and $0 cost, while latency, routes, predicates and retrievals are correct.

  The fix is to build the image from `uv.lock`. Until then, smoke-test changes inside the built image:

  ```bash
  docker run --rm --platform linux/amd64 <image> python -c "..."
  ```
- **Findings still open** from the first runs:
  - `store_pet` overwrites a stored species with a new guess (`COALESCE($species, p.species)`);
  - hypotheticals create real entities;
  - the knowledge extractor defaults to `gpt-5.2`;
  - ReAct planning is slow (about 3 minutes for a trip-planning task).

---

## Testing the harness

```bash
make test                                         # includes tests/unit/evals
pytest tests/integration/test_eval_harness.py     # needs Docker
```

The integration test runs the whole harness against a Neo4j container, with every LLM replaced by pydantic-ai's `TestModel` and a deterministic embedder.
