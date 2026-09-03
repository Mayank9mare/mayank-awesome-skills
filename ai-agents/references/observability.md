# Tracing, evaluation & observability for agents

An agent is a non-deterministic distributed system whose control flow is decided at
runtime by a model. You cannot debug it from logs alone, because the interesting question
is never "what did the code do" — it's **"why did the model choose that"**. That requires
capturing the decision inputs, not just the outcomes.

## The unit of observability is the trace, not the log line

One user request becomes a tree: agent turns, model calls, tool calls, retrievals,
sub-agents. Flat logs interleave those and lose the parent/child relationship, so you can
never answer "which tool call caused this bad answer". Model it as a trace from the start.

```
trace: "resolve support ticket"                                  12.4s  $0.043
├── span  agent.turn (1)                                          3.1s
│   ├── span  gen_ai.chat  (model=…, in=1204 out=88)              2.8s  $0.011
│   └── span  tool.search_orders  (order_id=…)                    0.3s
├── span  agent.turn (2)
│   ├── span  gen_ai.chat  (in=1580 out=142)                      3.4s  $0.014
│   ├── span  tool.get_refund_policy                              0.1s
│   └── span  tool.issue_refund  ⚠ requires_approval               —
└── span  agent.turn (3) → final
```

What each span level answers: the **trace** gives you cost and latency per user request;
the **turn** shows the reasoning loop and whether it's converging or thrashing; the
**model call** captures the exact inputs that produced a decision; the **tool call**
shows what the agent actually did to the world.

## Use OpenTelemetry GenAI semantic conventions

Don't invent your own attribute names. The GenAI conventions exist so your traces work in
any OTLP backend and can be compared across services.

| Attribute | What it holds |
|---|---|
| `gen_ai.operation.name` | `chat`, `embeddings`, `execute_tool` |
| `gen_ai.provider.name` | the inference provider |
| `gen_ai.request.model` | the model **actually invoked**, not the alias you asked for |
| `gen_ai.request.temperature`, `.max_tokens` | sampling params — needed to reproduce |
| `gen_ai.response.model` | what answered (may differ from requested) |
| `gen_ai.response.finish_reasons` | `stop` / `length` / `tool_calls` — see below |
| `gen_ai.usage.input_tokens` | prompt tokens |
| `gen_ai.usage.output_tokens` | completion tokens |
| `gen_ai.tool.name` | tool invoked |

**Status: the GenAI conventions are still pre-stable.** They've moved out of the core
semconv registry into a dedicated GenAI repo, and attribute names have churned. Set
`OTEL_SEMCONV_STABILITY_OPT_IN` to dual-emit old and new names during a transition rather
than cutting over blind, and pin your instrumentation version.

`gen_ai.response.finish_reasons` is the highest-value cheap signal. A rising rate of
`length` means you are silently truncating outputs — the agent looks like it's giving
worse answers when actually it's being cut off mid-sentence. Alert on it.

```python
from opentelemetry import trace

tracer = trace.get_tracer("myagent")

with tracer.start_as_current_span("gen_ai.chat") as span:
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.request.temperature", temperature)

    resp = client.messages.create(model=model, messages=msgs, tools=tools)

    span.set_attribute("gen_ai.response.model", resp.model)
    span.set_attribute("gen_ai.usage.input_tokens", resp.usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", resp.usage.output_tokens)
    span.set_attribute("gen_ai.response.finish_reasons", [resp.stop_reason])
```

## Prompts and completions go in span EVENTS, never attributes

This is the rule people break first and regret most.

```python
# WRONG — attributes are indexed and size-limited. A 30KB prompt here means
# PII in your search index, truncated telemetry, and a bill you didn't plan for.
span.set_attribute("prompt", full_prompt)

# RIGHT — an event body carries the payload; it isn't indexed as a dimension.
span.add_event("gen_ai.content.prompt", {"gen_ai.prompt": redacted(full_prompt)})
```

Better still for regulated data: log a **hash plus a redacted summary**, keep the raw text
in a separate store with its own retention and access control, and put the storage key on
the span. You almost always need the prompt to debug; you almost never need it in the
telemetry backend forever.

Redact before it leaves the process. A redaction step downstream is a redaction step you
will discover was misconfigured after the incident.

## Instrument at exactly ONE layer

The most common self-inflicted wound. These three all emit GenAI spans:

1. an OTel auto-instrumentation package for your LLM SDK,
2. your agent framework's built-in tracing,
3. your own manual spans.

Enable two and every model call appears twice — **token counts and costs double**, and
your "spend per route" dashboard is wrong in a way that looks plausible. Pick one layer,
disable the others explicitly, and verify by counting spans for one known request.

## Cost and token accounting

Cost is the metric that gets a project cancelled, so treat it as a first-class signal.

```python
# Record cost as a metric, not just a span attribute — you want it aggregatable
# by route/tenant/model without querying the trace store.
token_counter.add(resp.usage.input_tokens,
                  {"gen_ai.request.model": model, "direction": "input", "route": route})
cost_histogram.record(estimated_cost_usd,
                      {"gen_ai.request.model": model, "route": route})
```

Rules that save money:

- **Attribute cost to a dimension you can act on** — route, tenant, feature, agent name.
  "We spent $4,000 last month" is not actionable; "checkout-assist is 70% of spend" is.
- **Sum child costs onto the trace root.** Per-call cost hides the real number: a
  12-turn agent loop is one user action and one bill.
- **Alert on cost per successful outcome**, not total spend. Total spend rising with
  traffic is fine; cost per resolved ticket rising means the agent got worse.
- **Cache-hit rate is a cost metric.** Prompt caching can cut input cost dramatically, and
  a silent cache-miss regression (someone made the system prompt dynamic, so the prefix
  stopped matching) looks exactly like a price increase. Track it.
- Watch **input** tokens more than output. Growth there is usually accidental —
  accumulated history, over-fetched RAG context, tool schemas that keep expanding.

## The metrics worth having

| Metric | Why |
|---|---|
| Turns per task (histogram) | The single best health signal. A rising p95 means the agent is thrashing — see loop detection. |
| Tool-call error rate, by tool | A broken tool shows up as degraded *answers*, not as an exception. |
| Tool selection distribution | A tool that's never chosen is dead weight in the prompt; one chosen constantly may be over-described. |
| `finish_reasons` = `length` rate | Silent truncation. |
| Time to first token / total latency | Users perceive TTFT; cost tracks total. |
| Cost per trace, per successful outcome | See above. |
| Guardrail / refusal / retry rates | Sudden movement means a prompt or model change landed. |
| Human-approval rate and time-to-approve | If approvals bottleneck, the design is wrong. |
| Context-window utilisation | Approaching the limit predicts truncation before it happens. |

**Cardinality discipline is the same as any service**: model, tool name, route, tenant tier,
outcome class — bounded. Never user IDs, session IDs, prompt hashes, or free-text error
strings as metric labels. Those belong on spans, which aren't time series.

## Loop and thrash detection

Agents fail by not stopping. Instrument the stopping conditions.

```python
MAX_TURNS = 12

seen_calls: set[tuple[str, str]] = set()
for turn in range(MAX_TURNS):
    ...
    key = (tool_name, canonical_json(tool_args))
    if key in seen_calls:
        # Same tool, same arguments, again — the model is stuck. Feeding it the
        # same observation will not change its mind; it needs different input.
        span.add_event("agent.repeated_tool_call", {"tool": tool_name})
        repeats += 1
        if repeats >= 2:
            span.set_attribute("agent.terminated_reason", "repeat_loop")
            break
    seen_calls.add(key)
else:
    # Loop exhausted WITHOUT a final answer. This is a failure, not a success —
    # record it as one or your success rate is a lie.
    span.set_attribute("agent.terminated_reason", "max_turns_exhausted")
    span.set_status(Status(StatusCode.ERROR, "max turns exhausted"))
```

Emit a distinct outcome for each termination reason: `answered`, `max_turns_exhausted`,
`repeat_loop`, `guardrail_blocked`, `tool_failed`, `awaiting_approval`. Collapsing these
into success/failure destroys the diagnosis.

## Evaluation — the part that makes the rest useful

Tracing tells you what happened on one request. Evaluation tells you whether a change made
things better. Without eval you are tuning prompts by vibes, and you will regress silently.

**Build the dataset from production traces.** Every user thumbs-down, every
`max_turns_exhausted`, every escalation-to-human becomes a test case. This is the real
payoff of tracing: your eval set writes itself, and it's drawn from the distribution you
actually serve rather than from cases you imagined.

Three tiers, in the order you should build them:

1. **Deterministic assertions** — cheap, fast, no model needed, and where most real bugs
   live. Did it call the required tool? Is the output valid JSON against the schema? Is
   the cited order ID one that actually exists in the input? Did it refuse when it should
   have? Run these on every PR.

   **Use a graded metric for set-valued fields, not exact match.** If a field is a list —
   segments, tags, IDs, extracted entities — exact-set-equality scores a near-miss the same
   as a total miss, and you lose the signal that would tell you the model is 90% right.
   **Jaccard similarity** is the cheap correct answer:

   ```python
   def score_set_field(predicted: set[str], expected: set[str]) -> float:
       union = len(predicted | expected)
       # Both empty is a correct answer, not a division error.
       return 1.0 if union == 0 else len(predicted & expected) / union
   ```

   Keep exact match for scalars (an enum, an ID, a boolean) where partial credit is
   meaningless. Mixing the two — exact for scalars, Jaccard for sets — is what makes a
   deterministic suite sensitive enough to detect a regression before a human notices.
2. **LLM-as-judge** — for qualities you can't assert (helpfulness, tone, faithfulness to
   sources). Caveats that matter: use a **different, stronger model** than the one under
   test; give the judge a rubric and few-shot examples, not "rate 1–10"; **validate the
   judge against human labels** before trusting it; and beware position bias in pairwise
   comparison (randomise order). A judge you haven't calibrated is a random number
   generator with good manners.
3. **Human review** — sample continuously, and always review the disagreements between
   tiers 1 and 2. That's where your rubric is wrong.

**Track eval scores per version and gate deploys on them.** A prompt change is a code
change: it needs a diff, a review, a test run, and a rollback path. Prompts belong in
version control with the model name and sampling params pinned alongside — "we changed the
prompt and it got worse, and we don't know what the old one was" is an avoidable outage.

Also: **regression-test the tools, not just the prompts.** A tool whose schema description
changed can silently alter tool selection across every task.

## Replay and reproduction

Non-determinism makes bug reports useless unless you capture enough to replay.

Record on the trace: model + version, all sampling params, the **full** message list, tool
schemas as sent, the seed if the provider supports one, and every tool result. With those
you can re-run a failing trace against a new prompt or model and diff the behaviour. Store
them keyed by trace ID so a support ticket links straight to a replayable case.

Temperature 0 is **not** determinism — batching, hardware, and provider-side changes all
move outputs. Design for reproducibility of *inputs*, and accept variance in outputs; that
is exactly why you need statistical eval rather than golden-output assertions.

## Tooling

| Layer | Options |
|---|---|
| Vendor-neutral, OTLP | OpenTelemetry SDK + GenAI semconv; OpenLLMetry (OTel-native, Apache 2.0, instruments many providers/frameworks) |
| LLM-specific platforms | **Langfuse**, LangSmith, Phoenix/Arize, Braintrust, Helicone — better prompt/eval UX, proprietary pipeline |
| Gateways | A proxy in front of providers gives you cost/latency/caching/rate-limits in one place, at the cost of a hop |

**Prefer the OTel-native path** if you already run OTel: agent spans sit in the same trace
as your HTTP and database spans, so you can see that the slow agent turn was actually a
slow SQL query. That single property is worth more than a prettier prompt viewer. Adopt an
LLM platform when your bottleneck is prompt iteration and human labelling, and accept the
lock-in knowingly.

### What production actually does — and the pattern worth copying

Be aware the LLM-platform path is the more common real-world choice, not the exception. In
one large organisation, an org-wide code search found **~550 Langfuse references with a
shared `langfuse_helper.py` replicated across nine-plus services**, alongside ~275 LangSmith
references used for trace export and eval feedback. If you're joining an existing codebase,
expect to find a platform SDK rather than raw OTel.

That shared helper is worth copying, because it gets two things right that hand-rolled
instrumentation usually misses:

```python
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

# 1. GRACEFUL DEGRADATION. Tracing init inside try/except with None fallbacks, so a
#    telemetry outage costs you visibility — never availability. Exactly the same
#    principle as wrapping cache reads: observability is optional infrastructure.
try:
    Langfuse(public_key=..., secret_key=..., host=LANGFUSE_HOST)
    client = get_client()
    handler = CallbackHandler()
except Exception as e:                     # noqa: BLE001 — deliberate
    logger.error("failed to initialise tracing: %s", e)
    client = None
    handler = None

def callbacks() -> list:
    return [handler] if handler else []

# 2. AN EXPLICIT FLUSH. Exporters batch. In a short-lived process — a Lambda, a CLI, a
#    queue worker that exits after a job — the process dies with events still buffered
#    and you silently lose the traces for exactly the runs you wanted to inspect.
def flush() -> None:
    if client:
        client.flush()
```

Call `flush()` in your shutdown path and in any `finally` that ends a short-lived run. This
is the most common cause of "the trace just isn't there" in serverless agents.

**Name the seam, though.** That same file also read a Datadog environment variable — meaning
agent spans live in Langfuse while HTTP and database spans live in Datadog. Both tools are
fine; the cost is that **no single trace spans both**, so "was the slow turn actually a slow
query?" is unanswerable without correlating by hand. If you take the platform path
deliberately, at least propagate one shared correlation ID into both so a join is possible.

Whatever you choose, **the trace must join to the rest of your system** — propagate
`traceparent` inbound and outbound so an agent action and the service call it triggered
share one trace ID.

## Checklist

- [ ] One trace per user request; turns, model calls and tool calls as nested spans
- [ ] OTel **GenAI semantic conventions** for attribute names, version pinned
- [ ] Prompts/completions in span **events** (or an external store), never attributes
- [ ] Redaction applied **in-process**, before export
- [ ] Instrumented at exactly **one** layer — span count verified for a known request
- [ ] Tracing init cannot throw — try/except with `None` fallbacks
- [ ] Exporter **flushed** on shutdown and in short-lived processes (Lambda/CLI/worker)
- [ ] If using an LLM platform rather than OTel: a shared correlation ID lets agent and
      service telemetry be joined by hand
- [ ] Token counts and cost recorded as **metrics**, attributed to route/tenant/agent
- [ ] Child costs summed onto the trace root
- [ ] Prompt-cache hit rate tracked
- [ ] Alert on `finish_reasons=length`, turns-per-task p95, tool error rate
- [ ] Distinct outcome values per termination reason — `max_turns_exhausted` counted as failure
- [ ] Repeated-tool-call loop detection with a turn cap
- [ ] Metric labels bounded — no user/session IDs
- [ ] Eval set built from real failing traces; deterministic assertions in CI
- [ ] LLM judge validated against human labels; stronger model than the one under test
- [ ] Prompts, model name and sampling params in version control; deploys gated on eval
- [ ] Enough captured to replay a failing trace
- [ ] `traceparent` propagated so agent and service telemetry join
