# Evals and tracing

The eval harness measures how the agent behaves. It covers:
- routing, tool selection, memory retrieval and entity resolution;
- end-to-end task completion;
- Deep Research source quality and synthesis groundedness;
- latency and cost for all of the above.

It runs two ways: against **seeded synthetic users**, where the right answer is known, and against **your real conversations**, which are judged with rubrics only. Results, failure analyses and a predicate-tree view of every turn are in the **Evals** tab. The tab is visible to superusers only.

Memory also shapes routing. Before the router picks a tool, it's shown the user's own most relevant statements from other conversations (the `intent_memory` retrieval in the trace), so standing instructions such as "use my full name for patent searches" reach it. The assistant's own past replies are deliberately excluded, so an earlier wrong answer can't steer the next one.

Contents:
- [How it fits together](#how-it-fits-together)
- [Turn tracing](#turn-tracing)
- [Suites and cases](#suites-and-cases)
- [Incident regressions and frozen data](#incident-regressions-and-frozen-data)
- [Tool fault injection](#tool-fault-injection)
- [Scoring](#scoring)
- [Judges and rubrics](#judges-and-rubrics)
- [Uncertainty: intervals, consistency, paired comparison](#uncertainty-intervals-consistency-paired-comparison)
- [Checking the graders against a person](#checking-the-graders-against-a-person)
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
| Intervals, consistency, paired comparison | `evals/stats.py` |
| Human labels and grader calibration | `evals/calibration.py`, table `eval_human_labels` |
| CLI | `evals/__main__.py` (`python -m agent_system.evals`) |
| API | `adapters/inbound/api/routes/evals.py` (`/api/v1/evals`) |
| Tables | `adapters/outbound/persistence/eval_models.py` |
| UI | `frontend/src/components/evals/`, `frontend/src/stores/evalStore.ts` |

---

## Turn tracing

Every agent turn records a `TurnTrace`, whether it comes from a chat, a group chat, the journal's side conversation or an eval. `run_agent_workflow` drives the graph with `agent_workflow.iter(...)`. That lets it open a timed span for each node visit and bind the trace and the current node to context variables.

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
| `CheckPlan` | `auto_plan ∧ (requires_planning ∨ (intent = task ∧ ¬direct_tool))`: a task is planned unless its picked tool is the whole job (`read_webpage`) |
| `ExecutePlan` | `react_mode ∧ plan` |
| `ExecutePlan` | `step N: needs_tool ∧ tool_suggestion` |
| `ExecutePlan` | `requires_tool ∧ tool_name` |
| `ExecutePlan` | `plan.current_step.tool_required` |
| `EvaluateResult` | `¬plan.is_complete` |
| `GenerateResponse` | `react_mode ∧ step_results` |
| `GenerateResponse` | structured-data and markdown-table bypasses |

**Where traces are stored.**
- **Chat turns:** written to `turn_traces` inside the same transaction as the turn's messages.
- **Journal turns:** written to `turn_traces` with `source = "journal"` and `conversation_id = "journal:<day>"`. There is no journal eval suite yet.
- **Group chat turns:** written in a short session of their own.
- **Deep Research:** stores a per-stage rollup (`lane:*`, `synthesis`, `writer`, …) in `research_jobs.progress.usage`.
- **Messages:** `messages.token_count` is now filled in.

To add a branch to the tree, wrap the condition in `ctx.deps.decide(node, "readable predicate", result, next_node, **inputs)`. It returns `result`, so it drops straight into an `if`.

---

## Suites and cases

| Suite | Kind | Cases | Rubrics | What it covers |
|---|---|---|---|---|
| `routing` | agent | 15 | agent_flow | Intent and the FSM path it drives: direct answer, tool, or plan. Also covers `auto_plan` off and clarifications that shouldn't re-run a tool. |
| `tool_selection` | agent | 20 | agent_flow | Right tool, plus usable arguments with pronouns and references resolved (math, definitions, docs, web, recall, time). Includes public-record lookups about the user (such as patents) going to `web_search` under the user's full name, and no false "I have no internet access" claims. |
| `memory_retrieval` | agent | 17 | memory_retrieval, task_completion | Recalling seeded people, pets, places, preferences and backdated messages. Includes aliases, multi-hop links, temporal recall, no fabrication, and no false links. |
| `entity_resolution` | agent | 15 | none (deterministic) | Knowledge-graph state after `FinalizeKnowledge`: new vs. existing entities, aliases, nicknames, relationship changes, no duplicates, no spurious entities. |
| `e2e_tasks` | agent | 10 | task_completion, agent_flow | Multi-turn and planning tasks judged end to end, including honesty about what it can't do. |
| `incidents` | agent | 6 | none (deterministic) | Real production failures, replayed against frozen events and calendar data. A hard gate: every case must pass. |
| `resilience` | agent | 8 | agent_flow | Tools made to fail on purpose: rate limits, refused pages, crashes, timeouts, empty results, a service that is down. |
| `injection` | agent | 7 | none (deterministic) | Untrusted web and pasted text must not trigger writes or become memory. Web content is canned. |
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
    must_mention_any: ["6 PM", "6:00 PM"] # at least one must appear (for facts with several spellings)
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

## Incident regressions and frozen data

The `incidents` suite holds real production failures, one case each. It answers a different question from the other suites. They estimate how good the agent is, with a pass rate and an interval. This one asks whether a bug that already reached a user has come back, and the answer has to be no.

**A hard gate.** The suite sets `must_pass_all: true`. Every attempt at every case must pass; the run summary carries `gate` with the failing case ids, the CLI exits 1 on a failed gate whatever `--fail-under` says, and the Evals tab shows a banner. A pass rate would hide one regression among several passes, so none is used. The suite has no rubrics, so the gate never depends on a judge.

**Frozen data** (`evals/world_fixture.py`). A case about events or the calendar cannot be repeated if it reads what the events service holds today or a real connected calendar. A case can set:

| Field | Replaces | What still runs for real |
|---|---|---|
| `events_fixture` | The HTTP fetch from the events service | Time-window selection, merging of duplicate listings, formatting, both engines' handling of the result |
| `calendar_fixture` | The Google Calendar API call | The Google event parser, the timezone conversion, the tool's filtering and formatting |
| `web_fixture` | Web search and page fetches | Untrusted-text wrapping and the write block |

Two design choices:

- **Dates are relative.** A fixture record says `day: 0` (today in Houston) or `day: 1`, with a local `time`, never a calendar date. "What's on today" then means something on any day the suite runs, and no clock has to be pinned across the many places the app reads the time. The cost is that cases cannot depend on a weekday ("this weekend").
- **The substitution is at the edge, below the code under test.** Calendar entries are built in the JSON shape Google sends, a local time with a UTC offset, and pass through the real parser, because that parser is where the timezone bug was. A fixture placed any higher would have passed with the bug present.

```yaml
- id: calendar_event_is_read_back_at_its_local_hour
  incident: >
    2026-11-14: a 6 to 8 PM Central event was read back as noon ... Fixed in 99b1f14.
  seed: {timezone: America/Chicago}
  calendar_fixture:
    - {summary: "Hangout with Ben Luis", day: 1, start: "18:00", end: "20:00"}
  turns: ["What time is my hangout with Ben tomorrow?"]
  expect:
    tool: get_upcoming_events
    must_mention_any: ["6:00 PM", "6 PM"]
    must_not_mention: ["12:00 PM", "noon"]
```

**Adding a case when something breaks in production.**

1. Write down what the user asked, as `turns`.
2. Freeze what the tools would have returned, as a fixture. Trim real data; keep the detail that triggered the bug.
3. Assert the thing that was wrong, narrowly. The check should fail on the old behaviour and pass on any correct answer, not only on the wording the fix happens to produce.
4. Name the incident and the fixing commit in `incident`.
5. Prove the case has teeth: put the bug back and confirm the case fails. A regression test that passes with the bug present protects nothing. Five of the six current cases were checked this way; the follow-up routing case guards prompt wording and was not.

**Running it.** `incidents` is first in `make eval`. To check both engines:

```bash
CHAT_ENGINE=fsm  python -m agent_system.evals run --suite incidents --judge none --no-analysis
CHAT_ENGINE=loop python -m agent_system.evals run --suite incidents --judge none --no-analysis --repeats 2
```

A full pass makes about 20 model calls and takes one to two minutes.

---

## Tool fault injection

Every other suite runs with the tools working. In production they do not always: web search is rate-limited from the cluster, ticketing sites refuse page reads, a service is down. The `resilience` suite makes tools fail on purpose and checks what the agent does about it (`evals/tool_faults.py`).

**What a good reply does**, and what each case asserts:

- says the lookup failed (`must_mention_any`, a list of the ways a reply can say so);
- does not invent the answer (`must_not_mention`);
- does not hammer the failing tool (`max_tool_calls`);
- never reports a failed read as "nothing there". A crashed calendar read must not become "you're free".

**Planning a fault.**

```yaml
- id: calendar_read_fails_is_not_an_empty_calendar
  tool_faults: [{tool: get_upcoming_events, kind: exception, message: "database connection lost"}]
  turns: ["What's on my calendar tomorrow?"]
  expect:
    tool: get_upcoming_events
    must_mention_any: ["couldn't", "unable", "failed", "error"]
    must_not_assert: ["schedule is clear", "you're free", "no events"]   # a denial of these is fine
    max_tool_calls: 3
```

| `kind` | What the tool call gets | What it tests |
|---|---|---|
| `error` | The tool's own failure result (`success=False` and a message, e.g. HTTP 429) | What the agent tells the user |
| `exception` | The tool raises | An unhandled crash in a tool must not crash the turn |
| `timeout` | The tool raises `TimeoutError` | The same, for the timeout path |
| `empty` | Success with no data | "No results" must not be turned into an answer |

`times: N` fails only the first N calls and lets later ones through (retry behaviour). `required: false` marks a fault on a tool the agent may reasonably use instead of another; with only optional faults, at least one must fire. A service being down can also be expressed with a fixture: `events_fixture: []` is what the events adapter returns when it cannot reach the service.

**How it works.** Both chat engines call tools through one function, `tools.run_tool`. It has an optional interceptor that nothing sets in production; the eval runner installs one that reads the running case's faults. So the fault is met by the same code that handles a real failure: the state machine's `ExecuteTool` and `EvaluateResult`, or the loop's `_call`.

**A case cannot pass for the wrong reason.** If the agent never calls the faulted tool, nothing was tested, and the case fails with `fault_not_reached`. That tag points at routing, not at failure handling.

**Not a hard gate.** `resilience` is measured like the other suites (pass rate, interval, consistency across repeats). Substring checks are a blunt tool for "did it admit the failure", so run it with a judge when you want a second opinion: the `agent_flow` rubric's `recovery` dimension scores exactly this.

**Results when first run** (2026-11-15, no judge):

| Engine | Attempts | Result |
|---|---|---|
| Loop | 2 per case | 16 of 16 |
| State machine | 3 per case | 21 of 24: seven cases passed every time, `page_read_refused` failed every time |

The one failure was a routing defect, not a failure-handling one: asked "Summarize this page for me: <url>", the state machine classified it as a task, planned, and called `recall_about_topic` with the URL as the topic. It never tried to read the page, so the fault was never met. The router had chosen `read_webpage`; `CheckPlan` planned every `task` intent regardless, and planning replaces the router's tool with the planner's own steps. Fixed the same day by not planning a task whose chosen tool is the whole job (`DIRECT_ANSWER_TOOLS`, currently `read_webpage`). A broader first fix, letting any chosen tool skip planning, was rejected by the routing and end-to-end suites: the router also names `web_search` or `recall_about_topic` for genuine planning tasks, and those stopped being planned. The case is kept as the `a_commanded_page_summary_reads_the_page` case in `incidents`.

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
| `mentions_any` | The reply contains at least one `must_mention_any` | `incomplete_answer` |
| `no_false_claim` | The reply states none of `must_not_assert`. A phrase inside a denial ("that doesn't mean you have no events") does not count. Heuristic: no negation word earlier in the same sentence. | `false_claim` |
| `tool_calls` | The last turn made at most `max_tool_calls` tool calls | `retry_storm` |
| `faults_fired` | Every planned tool fault was actually met | `fault_not_reached` |
| `no_hallucination` | The reply contains no `must_not_mention` | `hallucinated_memory` |
| `entity_resolution` | Each expected entity exists with its aliases linked and the right relationship or species | `entity_miss` |
| `entity_dedup` | No expected entity is split across several nodes | `entity_dup` |
| `no_spurious_entities` | No forbidden entity was created | `entity_spurious` |
| `latency` | The turn is within `max_latency_ms` | `slow` |
| research: `source_count`, `source_diversity`, `lane_coverage`, `citable_sources` | minimum sources met, ≥50% distinct domains, every expected lane produced findings, every source has a URL | `thin_sources`, `low_diversity`, `lane_empty`, `uncitable_source` |

Phrase checks (`must_mention`, `must_mention_any`, `must_not_mention`) ignore case and whitespace and treat typographic quotes and dashes as plain ones, so a case asking for `couldn't` matches the `couldn’t` a model writes.

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

## Uncertainty: intervals, consistency, paired comparison

A pass rate from a few dozen cases is an estimate, and the agent is not deterministic. `evals/stats.py` adds three things so a number is not read as more certain than it is. All of it is pure and seeded: the same results give the same numbers.

**Interval on the pass rate.** Every run summary carries `pass_rate_interval`, a 95% interval.

| Situation | Method | Why |
|---|---|---|
| One attempt per case | Wilson score interval | Stays inside 0 to 100% and is not zero-width at a clean sweep. 9 of 10 gives 60% to 98%. |
| Several attempts per case | Bootstrap that resamples whole cases | Repeats of one case mostly agree with each other, so they are not independent evidence. Four cases tried five times is four cases, not twenty. |
| Several attempts, every case identical | Wilson on the number of cases | The bootstrap has nothing to resample. |

**Consistency.** With `--repeats 2` or more the summary carries `consistency`:

- `pass_all_k`: the share of cases that passed every one of k attempts (pass^k in the τ-bench paper). This is the reliable share, and it is the number to quote for something a user depends on.
- `pass_any`: the share that passed at least once.
- `flaky`: the cases with mixed results, by name. These are where to look first: a case that passes two times in three is a real defect that a single run hides two times in three.

**Paired comparison.** Two runs of one suite share their cases, so comparing them is a paired test: what matters is whether the per-case differences lean one way. `/compare` and the CLI report the mean difference in pass rate on the shared cases, a 95% interval on it (bootstrap over cases), and a p-value from a sign-flip permutation test (with one attempt per case this is the exact McNemar test). The verdict is `better` or `worse` only when the interval excludes zero and the p-value is below 0.05; otherwise it is `no_clear_difference`, whatever the raw rates look like. Both are required because the bootstrap interval runs narrow on a handful of cases. Going from 8 of 10 to 9 of 10 is one case flipping and is reported as no clear difference; on a 10-case suite it takes six cases moving the same way, with none moving back, to be called.

```bash
python -m agent_system.evals compare <baseline_run_id> <run_id>
python -m agent_system.evals run --suite routing --repeats 3 --baseline <run_id> --fail-on-regression   # exit 1 only when clearly worse
```

What this does not fix: the suites are small. With 10 to 20 cases the intervals are wide and only large changes will show as clear. The remedy is more cases and more repeats, not a different formula.

---

## Checking the graders against a person

An LLM judge is a model like any other. Until its verdicts have been compared with a person's on the same outputs, its scores are unvalidated, and agreement between two judges is not agreement with you.

**Labelling.** Open a case result, go to **Scores & judges**, and mark **Pass** or **Fail** under *Your verdict*: once for the case as a whole (`overall`) and once per rubric that was judged, with an optional note on why. Clicking the chosen button again removes the label. Tick **Hide judge scores until I have labelled** so the judge's score cannot anchor yours; the case's own pass/fail badge is still visible in the header. Labels are stored in `eval_human_labels`, one per result and rubric.

**What is compared.**

| Label | Grader checked | Its verdict |
|---|---|---|
| a rubric | each judge that scored that rubric | its mean on the rubric is at least the suite's `pass_threshold` |
| `overall` | the harness | the case's stored pass/fail (deterministic checks and judges together) |

**What is reported** (Evals tab, *Grader calibration* card; `python -m agent_system.evals calibration`; `GET /api/v1/evals/calibration`). A failure is the thing worth catching, so it is the positive class.

| Number | Meaning |
|---|---|
| agrees | Share of labels where grader and person match. Misleading alone: if 80% of outputs are fine, a judge that passes everything agrees 80% of the time. |
| catches failures | Of the outputs you failed, the share the grader failed. The number that matters most. |
| passes good | Of the outputs you passed, the share the grader passed. |
| kappa | Agreement beyond what the two pass rates would give by chance. |
| by threshold | Agreement at cut-offs from 2.5 to 4.5, to show whether 3.5 is the right one for that rubric. |
| status | `needs more labels` below 30 labels or fewer than 5 of either class; `agrees with you` when both rates are at least 80%; otherwise `disagrees too often`. |

The card links to the cases where you and a grader disagreed. Reading those is the point: each one is either a rubric to tighten, a threshold to move, or a deterministic check to add.

**How to use it.** Label 30 to 50 results per rubric, deliberately including failures (a run with only passes cannot measure whether failures are caught). Label real conversations as well as suite cases. Re-check after changing a rubric or the judge model, since calibration belongs to one judge, one rubric and one threshold.

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
| `--baseline` | A run id to compare against, paired by case |
| `--fail-on-regression` | With `--baseline` or `--baseline-file`: exit 1 when the run is clearly worse |
| `--export` | Write each suite's pass/fail per case to a JSON file |
| `--baseline-file` | Compare against a file written by `--export`, for when the earlier run is not in this database (CI) |

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
  - pass rate with its 95% interval, turn latency (p50 and p95), cost per case, tokens;
  - with repeats: the share of cases that passed every time, at least once, and with mixed results;
  - deterministic check means;
  - judge means per `rubric.dimension`, per judge, plus agreement when `both` ran;
  - node latency (p95);
  - failure categories and flags, which you can click to filter the case table.
- **Cases.** Result, failure tags, judge mean, latency and cost. Click one to open it:
  - **Predicate tree:** see below;
  - **Scores & judges:** every deterministic check with its detail, and every judge dimension with its rationale;
  - **Seed & knowledge graph:** what was seeded, the expectations, and the social graph after the run. Not shown for real conversations or research cases.
- **Failure analysis:** the markdown write-up.
- **Compare with an earlier run** of the same suite: a paired verdict (better, worse, or no clear difference) with its interval and p-value, then metric deltas, regressions (passed before, fails now) and fixes.
- **Grader calibration:** how often each judge, and the harness as a whole, agrees with your labels.

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
| `WEB_READ_PAGES` | `3` | How many top `web_search` results are opened and read |
| `WEB_JS_RENDER` | `true` | Render JavaScript-only pages in headless Chromium (Playwright). Falls back to a plain fetch when Playwright isn't installed. |
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
| `eval_human_labels` | A person's pass/fail on a case result, per rubric or `overall`, with a note. Removed with the run's results. |
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
| GET | `/compare?a=&b=` | Paired comparison, metric deltas, regressions and fixes (`a` is the baseline) |
| PUT | `/cases/{id}/labels/{rubric}` | Set a human label: `{passed: true|false|null, note}`; `null` removes it. `rubric` is a rubric name or `overall` |
| GET | `/calibration?suite=` | Agreement between each grader and the human labels |
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
- **Library versions.** The backend image installs from `uv.lock`, the same versions tests and CI use (see [ci.md](ci.md)). It used to install from the ranges in `pyproject.toml`, so production ran newer libraries than tests did. Two problems came from that, and the second is still open:
  - An OpenTelemetry hook added in a newer SDK broke every LLM call until the span processor was changed to subclass `SpanProcessor` (2026-09-22).
  - With pydantic-ai 1.107 and openai 3.x, Responses API calls report **zero tokens**. Traces and eval runs therefore show 0 tokens and $0 cost, while latency, routes, predicates and retrievals are correct.
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
