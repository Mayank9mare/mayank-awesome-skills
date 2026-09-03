# Prompts, structured output & cost

Prompts are code. They get versioned, reviewed, tested and rolled back. A prompt edited
directly in a dashboard with no diff is an unreviewed production change.

## Structure

Order matters, because of both attention and caching.

```
[system]
  role and scope          — what this assistant is and is NOT for
  behavioural rules       — constraints, refusals, tone
  output contract         — exact expected format
  static examples         — few-shot, if any
  ── everything above is STABLE and therefore CACHEABLE ──
[user / later turns]
  retrieved context       — volatile
  the actual task         — volatile
```

Put **stable content first and volatile content last**. This is not stylistic: prompt caching
matches on a prefix, so a single dynamic value near the top (a timestamp, a request ID, a
greeting with the user's name) invalidates the cache on **every** call. Teams routinely
discover a 5–10× cost difference from moving one line.

Other structural rules that hold up:

- **Delimit clearly.** XML-ish tags (`<document>`, `<task>`) or markdown headings — models
  attend to structure, and clear boundaries also make injection harder to disguise.
- **Positive instructions beat prohibitions.** "Answer only from the provided documents" works
  better than "do not use outside knowledge"; a prohibition invites negotiation, a positive
  contract just describes the output.
- **State the output contract precisely**, and show one example of it.
- **Say what to do when the task can't be done.** Without an explicit "if the documents don't
  contain the answer, say you don't know", the model will invent something — this is the
  single highest-value line in most RAG prompts.
- **"Lost in the middle" is real.** Task and constraints at the start or end; never buried
  mid-context.

## Prompt caching — the biggest cost lever

Most providers cache a stable prefix; reads cost a fraction of fresh input tokens.

Requirements: the prefix must be **byte-identical**, must exceed a minimum length, and cache
entries expire (minutes, typically). Practical consequences:

- Tool schemas belong in the cacheable prefix — they're static and often large.
- **Never interpolate anything dynamic above the cache boundary.** Not the date, not a
  request ID, not a per-user greeting.
- In a multi-turn loop, history grows at the end, so the stable prefix keeps hitting — this
  is why agent loops are far cheaper with caching than the raw token counts suggest.
- **Monitor cache-hit rate.** A regression (someone made the system prompt dynamic) looks
  exactly like a provider price increase. See observability.md.

Other cost levers, in rough order of payoff:

| Lever | Effect |
|---|---|
| Prompt caching | Often the largest single win. Free if you order the prompt correctly. |
| Right-sizing the model | A small model for classify/extract/route; a large one for reasoning. Most calls in a pipeline don't need the frontier model. |
| Trimming retrieved context | Usually the largest *variable* input cost. Rerank and pass 5, not 50. |
| Capping `max_tokens` | Bounds the worst case — but watch `finish_reasons=length` for silent truncation. |
| Batch APIs | Big discounts for non-interactive work. |
| Compacting history | Turn history grows quadratically in cost; summarise the middle. |

**Watch input tokens more than output.** Input growth is usually accidental — accumulated
history, over-fetched context, tool schemas that keep expanding — and it's where the money
goes.

## Structured output

Three mechanisms, in order of reliability:

1. **Constrained/JSON-schema mode** — the provider guarantees valid JSON matching a schema.
   Use it when available; it eliminates parse failures entirely.
2. **Tool calling as the output channel** — define a single tool whose parameters are your
   output shape. Well-supported and effectively schema-enforced.
3. **Prompt-and-parse** — ask for JSON and parse it. **Always validate**, always have a
   retry path. Fenced code blocks, prose preambles, and trailing commas are all normal.

```python
class Extraction(BaseModel):
    order_id: str
    sentiment: Literal["positive", "neutral", "negative"]
    # Optional fields need an explicit default, or the model is forced to invent one.
    refund_amount: Decimal | None = None

# Validate, and on failure feed the ERROR back — models correct well from a
# concrete validation message and poorly from "try again".
for attempt in range(2):
    raw = await model.chat(messages=msgs, response_format=schema_of(Extraction))
    try:
        return Extraction.model_validate_json(raw)
    except ValidationError as e:
        msgs.append({"role": "user", "content": f"Invalid output: {e}. Fix and resend."})
raise ExtractionFailed()
```

Two design notes: **prefer flat schemas** — deeply nested structures have measurably higher
failure rates; extract in two passes if needed. And **use enums, not free strings**, for
anything categorical. `Literal["a","b","c"]` cannot produce a fourth value; a string field
described as "one of a, b, c" can and will.

## Few-shot examples

Worth their tokens when the task is idiosyncratic, the output format is unusual, or you need a
specific tone. Rules:

- **Cover the edge cases**, not three variations of the easy path. The ambiguous and
  refuse-to-answer cases teach the most.
- **Be consistent.** Any inconsistency in your examples is a licence to be inconsistent.
- **Keep them in the cacheable prefix** so they're nearly free after the first call.
- **Delete them once instructions suffice.** Examples are input tokens on every call forever;
  re-measure whether they're still earning their cost.

## Model selection

| Task | Model tier |
|---|---|
| Classify, route, extract, simple rewrite | Smallest that passes eval — often much smaller than assumed |
| Tool-using agent loop | Mid/large — **tool-selection accuracy** is the binding constraint, not prose quality |
| Multi-step reasoning, ambiguous judgement | Largest |
| LLM-as-judge | **Stronger than the model under test**, always |

**Pin the version.** "Latest" silently changes behaviour with no diff. **Canary an upgrade
like a deploy**: a newer, better model can be worse on *your* task, and tool-selection
accuracy in particular does not always move with benchmark scores.

Two per-model realities: **temperature 0 is not determinism** (batching and hardware move
outputs), and **tool-calling quality varies more between models than prose quality does** —
if your agent picks wrong tools, try a different model before rewriting the prompt again.

## Reasoning models

Models that think before answering trade latency and output tokens for accuracy.

Use them for genuinely hard reasoning, multi-constraint planning, and complex debugging. Don't
use them for extraction, classification or formatting — you pay reasoning tokens for a task a
small model does instantly.

And **don't tell them how to think.** "Let's think step by step" and elaborate chain-of-thought
scaffolding can *hurt* a model that reasons natively. State the problem and the constraints;
let it work. Reasoning tokens also count toward cost and toward the context limit, so budget
for them explicitly.

## Prompt engineering that isn't prompting

Before rewriting a prompt a fifth time, check whether the actual problem is elsewhere:

- **Retrieval** — is the answer even in the context? (See rag-retrieval.md. Most
  "hallucination" is this.)
- **Tool descriptions** — wrong-tool selection is usually a tool-description problem, not a
  system-prompt problem.
- **Output schema** — an unconstrained string where an enum belongs.
- **Context ordering** — the constraint buried in the middle.
- **Model** — a capability ceiling no prompt clears.

A prompt change with no eval attached isn't an improvement, it's a hypothesis.

## Checklist

- [ ] Prompts in version control, with model name and sampling params alongside
- [ ] Stable content first, volatile last — cache prefix never invalidated by a dynamic value
- [ ] Tool schemas inside the cacheable prefix
- [ ] Cache-hit rate monitored
- [ ] Explicit instruction for "cannot answer from the given information"
- [ ] Output contract stated, with one example
- [ ] Structured output via schema mode or tool calling; validated with a retry that feeds back the error
- [ ] Flat schemas; enums instead of free strings for categoricals
- [ ] Few-shot examples cover edge cases, are internally consistent, and are re-justified periodically
- [ ] Smallest model that passes eval, per task
- [ ] Model version pinned; upgrades canaried against eval
- [ ] Judge model stronger than the model under test
- [ ] `max_tokens` capped, with `finish_reasons=length` monitored
- [ ] Checked retrieval / tools / schema / ordering before blaming the prompt
