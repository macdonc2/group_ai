# Validated context

What a model is given decides what it says. This app already typed what the model **returns** (intent, plans, extractions are Pydantic models). This document covers the other direction: what the model is **given**.

The rule: text does not go into a prompt as a loose string or an untyped dictionary. It becomes a `Passage` first, the rules are applied in code, and only then is it rendered. Everything is in `adapters/outbound/llm/context.py`.

## The pieces

| Piece | What it is |
|---|---|
| `Passage` | One piece of text the model may read: `id`, `kind`, `text`, `trust`, `title`, `source_ref`, `owner_id`, `score`, `truncated`, `retrieved_at`. A frozen Pydantic model. |
| `ContextBundle` | The passages for one turn, plus every candidate that was rejected and why. One per turn, shared by both chat engines. |
| Renderers | `render_web_results`, `render_web_page`: the only code that writes this context into a prompt. |
| `check_reply` | After the reply: which links does it give that appear nowhere in what the model was shown? |

## The rules, and where each is enforced

| Rule | Enforced by | On failure |
|---|---|---|
| A passage has text | `Passage` (`min_length=1`) after cleaning | dropped: `empty` |
| Web text has a real `http(s)` address with a host | `Passage` validator | dropped: `bad_url` |
| Web text is untrusted | `Passage` validator: it cannot be constructed as trusted | cannot happen |
| Remembered text belongs to the current user | `add_history` compares the hit's `user_id` with the bundle's | dropped: `wrong_owner` |
| Remembered text clears the similarity threshold | `add_history` | dropped: `low_score` |
| No passage repeats another | fingerprint of the normalised text, and the address | dropped: `duplicate` |
| Length is capped per passage and per search | builders | `truncated`, or dropped: `over_budget` |
| Text cannot use the prompt's own structure | `clean` strips `<untrusted>` tags and control characters | cleaned |

Two design choices worth being able to explain:

- **Trust is a property of the type, not a wrapper applied by a call site.** Before, web text was safe only if each place that handled it remembered to call `_untrusted(...)`. Now a web passage that is not untrusted fails validation, so forgetting is not possible.
- **A bad passage is dropped, not raised.** Validation errors are caught at the bundle and recorded as a rejection with a reason. Bad context should cost one passage, never the reply.

The ownership check repeats something the database query already does (`WHERE node.user_id = $user_id`). That is deliberate. A leak between users was found and fixed in the graph queries in November 2026; this check means a future query that forgets the filter still cannot put another person's memory in a prompt.

## What goes through it today

| Context | Engine | Status |
|---|---|---|
| Web search results | both | validated and rendered from passages |
| A fetched page | both | validated and rendered from passages |
| Related past messages (`semantic_search` in `GenerateResponse`) | state machine | validated; rendered by the existing prompt code from the hits that passed |
| `recall_about_topic`, entity lists, the knowledge summary | both | not yet: still tool message strings |
| Intent memory hints | state machine | not yet |
| Houston events | both | typed (`HoustonEvent`) and selected in code, but not as passages |
| Calendar, internal docs, journal entries | both | not yet |

## Grounding: text a model wrote from a source

Everything above covers text that comes straight from a source. A second kind of context is written by a model and then handed to another model as if it were fact. Deep Research does this: a lane model reads sources and writes **findings**, and the synthesis and report models then build on those findings without ever seeing the sources. If a finding is wrong, nothing downstream can know.

A finding has three parts: `claim` (the model's words), `evidence` (the supporting span from the source) and `source_id`. The claim needs judgement to check. The other two do not, so code checks them before the finding is passed on (`verify_findings` in `research/lanes.py`, `find_quote` in `llm/context.py`):

1. The source exists among the sources that model call was given.
2. The evidence appears **word for word** in exactly the text the model was shown for that source (its title and excerpt).

"Word for word" forgives only what is not content: typographic quotes and dashes, Unicode forms, whitespace and case. A quote may skip words with `...`; each part must then appear, in order. A changed number, a paraphrase, or a quote from a different source all fail. A quote shorter than 12 characters or 3 words is refused, since it would match almost anything.

What happens to a finding that fails:

- The model gets **one** correction call that lists the failed findings and asks for exact quotes.
- Whatever still fails is dropped and never reaches the synthesis model.
- The counts (proposed, verified, repaired, dropped) appear as a step in the research progress and in the log.

Why exact matching and not similarity: a paraphrase is the model's own wording, and the purpose of the check is to tell the source's words from the model's. A similarity threshold would re-admit exactly the thing being excluded, and it would make the check a matter of tuning instead of a yes or no.

Measured on 2026-11-18, findings step only, two lanes, one question ("best practices for evaluating RAG systems"), real sources:

| Findings prompt | Findings proposed | Evidence found word for word in the cited source |
|---|---|---|
| Before ("quoted or closely paraphrased") | 19 | 0 |
| After (exact quote required, checked, one correction) | 20 | 20 (19 first time, 1 after the correction, 0 dropped) |

The "before" findings were not shown to be false. Their evidence was the model's summary with fragments of quotation inside it, so there was nothing a program could check. One question is a small sample; the counts for every run are in its progress and log.

What this does and does not establish:

- **It does** establish that the evidence was really said by the cited source. That removes invented quotes, misattributed quotes and "closely paraphrased" spans that drift.
- **It does not** establish that the claim follows from the evidence, or that the source is right. A model can still attach a true quote to a claim it does not support. That step needs judgement: a judge model, or a person. The deterministic check makes that judgement cheap and bounded, because the judge compares one claim with one verified span instead of a whole document.

## The reply check

After a chat reply, `check_reply` looks for two things the reply contains that appear in none of: the passages, any other tool result shown this turn, the user's message, or the conversation.

- **Links.** Search-engine links the app suggests on purpose are not counted.
- **Quotations.** Text in double quotation marks (25 characters or more) and Markdown block quotes is treated as a claim to be someone's exact words, and is checked with the same `find_quote`.

A reported link or quotation came from the model's own memory. It may be correct, but nothing in the turn supports it. The check reports and does not block: the result is on the trace and logged as `unsourced_links` or `unsupported_quotes`.

## On the trace

Every turn's trace has a `context` field:

```json
{"passages": [{"id": "w1", "kind": "web_search", "trust": "untrusted", "source_ref": "https://...", "chars": 1840, "score": null, "truncated": false}],
 "rejected": [{"kind": "web_search", "reason": "bad_url", "source_ref": "javascript:alert(1)"}],
 "rejected_by_reason": {"bad_url": 1},
 "reply_check": {"links": 3, "unsourced_links": ["https://www.bandsintown.com/c/houston-tx"],
                 "quotes": 1, "unsupported_quotes": []}}
```

It holds each passage's identity and size, not its text again; tool results are already on the trace.

## Limits

- This validates form, ownership and provenance. It does not check that a passage is true or relevant.
- The reply check covers links and quotations. A reply can still state a fact, without quotation marks, that no passage supports; catching that needs claim-level checking, which is a judge's job.
- In the chat path the model reads tool results directly, so there is no model-written hand-off to gate. The grounding gate applies where one model's output becomes another's context: today that is Deep Research findings. Reasoning-step observations in the state machine's planning mode are the next such hand-off and are not gated yet.
- Coverage is partial (see the table above). Memory recall is the largest gap.

## Adding a source

1. Add a `SourceKind`, and add it to `UNTRUSTED_KINDS` if a third party wrote the text, or `OWNED_KINDS` if it is one user's data.
2. Add a builder on `ContextBundle` that turns the raw data into passages through `_add`, rejecting what breaks a rule.
3. Add a renderer, and make it the only path from that source to a prompt.
4. Test the rules in `tests/unit/chat/test_context.py`.
