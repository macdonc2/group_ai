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

## The reply check

`check_reply` extracts every link in the reply and reports the ones that appear in none of: the passages, any other tool result shown this turn, the user's message, or the conversation. Search-engine links the app suggests on purpose are not counted.

A reported link came from the model's own memory. It may be correct, but nothing in the turn supports it. The check reports and does not block: the result is on the trace and logged as `unsourced_links`.

## On the trace

Every turn's trace has a `context` field:

```json
{"passages": [{"id": "w1", "kind": "web_search", "trust": "untrusted", "source_ref": "https://...", "chars": 1840, "score": null, "truncated": false}],
 "rejected": [{"kind": "web_search", "reason": "bad_url", "source_ref": "javascript:alert(1)"}],
 "rejected_by_reason": {"bad_url": 1},
 "reply_check": {"links": 3, "unsourced_links": ["https://www.bandsintown.com/c/houston-tx"]}}
```

It holds each passage's identity and size, not its text again; tool results are already on the trace.

## Limits

- This validates form, ownership and provenance. It does not check that a passage is true or relevant.
- The link check covers links only. A reply can still state a fact that no passage supports; catching that needs claim-level checking against passages, which is a judge's job or a later stage.
- Coverage is partial (see the table above). Memory recall is the largest gap.

## Adding a source

1. Add a `SourceKind`, and add it to `UNTRUSTED_KINDS` if a third party wrote the text, or `OWNED_KINDS` if it is one user's data.
2. Add a builder on `ContextBundle` that turns the raw data into passages through `_add`, rejecting what breaks a rule.
3. Add a renderer, and make it the only path from that source to a prompt.
4. Test the rules in `tests/unit/chat/test_context.py`.
