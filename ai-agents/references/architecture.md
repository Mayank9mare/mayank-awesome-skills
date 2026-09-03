# Agent & workflow architecture

## First: do you need an agent?

An **agent** decides its own control flow at runtime. A **workflow** has control flow you
wrote. Agents are strictly more capable and strictly less predictable, so the default
should be the most constrained thing that solves the problem.

| Shape | Control flow | Use when |
|---|---|---|
| **Single prompt** | none | One transformation: classify, extract, summarise, rewrite. |
| **Chain** | fixed, sequential | Steps are known and ordered. Each step's output feeds the next. |
| **Router** | one model decision, then fixed | Input needs classifying into a handful of known paths. |
| **Parallel fan-out + reduce** | fixed, concurrent | Independent subtasks, then a merge. Cheap and fast. |
| **Evaluator–optimiser** | bounded loop | Output quality is checkable and iteration measurably helps. |
| **Agent (tool loop)** | model-decided | The number and order of steps genuinely cannot be known in advance. |
| **Multi-agent** | model-decided, delegated | Genuinely separable concerns needing different tools/context. |

**Most production "agents" should be workflows.** If you can enumerate the steps, write
them: a chain is debuggable, cheap, reproducible, and testable with ordinary assertions. An
agent loop costs one model call per step, can loop, and fails in ways you can't enumerate.
Reach for the loop when the task genuinely branches on discovered information — "research
this until you have enough" — not because "agent" sounds better than "function".

The honest cost comparison: a 3-step chain is 3 model calls with known latency. A tool loop
solving the same task averages 6–10 calls, sometimes 20, and occasionally never terminates.

## The agent loop, written out

Every framework wraps this. Know what's inside, because every failure mode lives here.

```python
async def run_agent(task: str, *, max_turns: int = 12, budget_usd: float = 0.50) -> Result:
    messages = [{"role": "user", "content": task}]
    spent = 0.0
    seen: set[tuple[str, str]] = set()

    for turn in range(max_turns):
        resp = await model.chat(messages=messages, tools=TOOL_SCHEMAS)
        spent += cost_of(resp)

        # Budget is a HARD stop. Without it one pathological task can cost more
        # than a thousand normal ones.
        if spent > budget_usd:
            return Result.failed("budget_exhausted", turns=turn, cost=spent)

        if not resp.tool_calls:
            return Result.ok(resp.text, turns=turn, cost=spent)

        messages.append(resp.as_assistant_message())

        for call in resp.tool_calls:
            key = (call.name, canonical_json(call.args))
            if key in seen:
                # Same tool, same args. The model is stuck; the same observation
                # will not change its mind. Tell it that explicitly.
                messages.append(tool_result(
                    call, "You already called this with identical arguments. "
                          "Use a different approach or give your final answer."))
                continue
            seen.add(key)

            # A tool raising must NOT kill the loop — the model can often recover
            # if you hand it the error as an observation.
            try:
                out = await dispatch(call, timeout=TOOL_TIMEOUT)
            except Exception as e:
                out = f"Tool failed: {type(e).__name__}: {e}"
            messages.append(tool_result(call, truncate(out, MAX_TOOL_CHARS)))

    # Loop exhausted with no answer. This is a FAILURE — record it as one.
    return Result.failed("max_turns_exhausted", turns=max_turns, cost=spent)
```

Five things in there are non-negotiable, and each maps to a real production incident:

1. **Turn cap.** Without it, "keep trying" runs until something else breaks.
2. **Budget cap.** Latency caps don't bound cost; a fast loop burns money fast.
3. **Tool errors become observations, not exceptions.** Most recoverable failures are
   recoverable *by the model* if it can see the error.
4. **Repeat detection.** Identical call twice means stuck; a nudge in the transcript beats
   silently looping.
5. **Truncate tool output.** One `SELECT *` returning 50k rows will blow the context window
   and take the whole task down.

### A timeout is not a turn cap, and neither is a budget cap

Worth stating plainly, because a survey of production agents showed exactly this gap: a
hand-rolled tool-using agent (31 tool definitions, direct SDK, no framework) had **timeouts
in 52 files** and **zero** occurrences of `max_turns`, `max_iterations`, `max_steps`,
`budget`, `cost_limit` or `max_cost`.

That is the normal failure shape. Teams reliably bound *latency* — it's the reflex carried
over from HTTP services — and reliably forget to bound *iterations* and *spend*. The three
are independent:

| Bound | Stops | Does NOT stop |
|---|---|---|
| **Timeout** | A single hung call | A loop that keeps making progress, one cheap call at a time |
| **Turn cap** | Unbounded iteration | A single turn that costs $4 in input tokens |
| **Budget cap** | Runaway spend | A fast loop that stays cheap but never converges |

You need all three. A per-call timeout with no turn cap is an agent that can run for hours
in short, successful steps; a turn cap with no budget cap is 12 turns of a 200k-token
context. Note also that a turn cap is a *safety net*, not a strategy — hitting it means the
task failed, which is why `max_turns_exhausted` must be recorded as a failure.

## Tool design is prompt engineering

Tools are how the model acts, and their *descriptions* are the only guidance it gets. Most
"the model is dumb" reports are tool-design problems.

```python
@tool
def search_orders(
    customer_id: Annotated[str, "Customer UUID, exactly as returned by lookup_customer"],
    status: Annotated[Literal["pending","shipped","delivered","cancelled"] | None,
                      "Filter by status. Omit for all."] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> list[OrderSummary]:
    """Search a customer's orders, most recent first.

    Use when the user asks about order history or the state of an order. Requires a
    customer_id — call lookup_customer first if you only have a name or email.
    Returns at most `limit` orders; if the customer has more, the oldest are omitted.
    """
```

What makes that work:

- **Constrain the type, don't validate in prose.** `Literal[...]` and `Field(ge=, le=)` make
  bad calls *impossible* rather than producing an error the model has to interpret.
- **State the precondition** ("call `lookup_customer` first"). Models cannot infer ordering
  from a tool list.
- **Say what it returns and what it omits.** Silent truncation makes the model confidently
  wrong about completeness.
- **Errors must be actionable.** `"customer_id not found: <id>. Call lookup_customer to
  resolve a name to an id."` teaches recovery; a stack trace teaches nothing.

Rules of thumb: **few well-named tools beat many overlapping ones** (5–15 is a healthy
range; past ~20 selection accuracy degrades and every schema costs input tokens on every
call). Make tools **idempotent** where possible, because retries happen. And **paginate** —
a tool returning everything will eventually return too much.

**Never expose an unbounded destructive tool.** Scope by identifier, require explicit
confirmation, and consider a `dry_run` parameter. See safety.md.

## Context management

Context is the scarcest resource, and the failure is gradual: quality degrades as the
window fills, well before you hit a hard limit.

- **Turn history grows quadratically in cost.** Every turn re-sends the whole transcript, so
  turn 10 pays for turns 1–9 again. This is usually the largest line on the bill.
- **Compact rather than truncate.** Dropping the oldest messages loses the task definition —
  the one thing that must survive. Summarise middle turns; keep the system prompt, the
  original task, and the most recent exchanges verbatim.
- **Keep the system prompt byte-stable** so prompt caching works. One dynamic value
  (a timestamp, a request ID) at the top of the prompt invalidates the cache prefix on
  every call and can multiply cost. Put volatile content at the **end**.
- **Tool results are the main bloat.** Return the fields the model needs, not the whole
  record. Filter server-side.
- **"Lost in the middle" is real.** Put the task and the constraints at the beginning or the
  end, not buried in the middle of a long context.

## Multi-agent: when it earns its cost

Delegation adds a full serialisation boundary — a sub-agent's findings reach the parent only
as text. That loses fidelity and costs a round trip, so it must buy something real.

**Good reasons:** genuinely different tool sets or permissions (a read-only researcher vs a
writer); **context isolation**, where a sub-agent burns 100k tokens exploring and returns a
1k summary, keeping the parent's window clean; parallel independent subtasks; and
adversarial separation, where a reviewer must not be the author.

**Bad reasons:** "it mirrors our org chart"; wanting a persona per domain (that's a prompt,
not a process); and diamond-shaped hand-offs where agent A's output feeds B and C which both
feed D — the coordination cost exceeds the benefit and debugging becomes guesswork.

Two patterns that work:

**Orchestrator–worker** — one coordinator decomposes and fans out to workers, each with a
narrow tool set, then synthesises. Keep workers stateless and single-purpose. This is the
default; prefer it.

**Adversarial verify** — generate, then have *independent* critics try to **refute** the
result, and require a majority to pass. Prompting a critic to "check this" produces
agreement; prompting it to "find the flaw, default to rejecting if uncertain" produces
signal. Use distinct lenses (correctness / security / does-it-reproduce) rather than N
identical critics — diversity catches failure modes redundancy can't.

Whatever the topology: **bound the fan-out**, give every level a turn and budget cap, and
never let a sub-agent spawn sub-agents without a depth limit. Unbounded recursion in an
agent system is unbounded spend.

## State, durability and resumption

A 30-turn agent will be interrupted. Decide up front whether that's recoverable.

- **Ephemeral** (all state in memory): fine for a request-scoped task under a few seconds.
  A restart loses everything.
- **Checkpointed** (state persisted per turn): resume where it stopped. Needed for
  long-running tasks, human approvals, and anything a deploy might interrupt.
- **Durable execution** (Temporal, Restate, DBOS, or a queue + state machine): the
  orchestration itself survives process death. Right for multi-hour or multi-day workflows.

If the agent takes actions with external side effects, checkpointing is not optional —
otherwise a retry re-issues the refund. Record **what was done** with an idempotency key, not
just what was decided.

**Human-in-the-loop is a state machine, not a callback.** Pausing for approval means the run
is suspended, persisted, and resumed by a different process, possibly hours later. Design for
that: persist the pending action plus enough context to render it for a human, and give it
an expiry so a forgotten approval doesn't wedge the task forever.

## Streaming

Users tolerate a slow answer far better than a silent one. Stream tokens for anything over a
second or two.

Two consequences worth planning for: you can't validate output you've already streamed, so
either stream only free text and buffer structured payloads, or accept that a guardrail may
have to retract. And **a cancelled stream must cancel the upstream call** — a client
disconnect that leaves the model generating is pure waste you're still billed for.

## Frameworks

| Option | Fit |
|---|---|
| **Direct SDK calls** | **Start here.** The loop is ~50 lines. You own the control flow, and debugging is reading your own code. |
| LangGraph | Explicit graph/state-machine model; good when the topology is genuinely complex and you want checkpointing. |
| Anthropic/OpenAI Agents SDKs | Provider-aligned loop with tool handling done for you. Least code for the common case. |
| Temporal / Restate / DBOS | Durable execution. Use when the *orchestration* must survive failure, not just the data. |
| CrewAI / AutoGen | Role-based multi-agent. Fast to demo; the abstraction can obscure exactly the control flow you need to debug. |

Framework choice is less important than owning the five loop invariants above. A framework
that hides the turn cap and the budget cap has hidden the two things most likely to hurt you.
Whatever you pick, verify you can still answer: what's the turn limit, what's the cost
ceiling, and where does a tool exception go?

### LangChain / LangGraph reached 1.0 — what that changes

Versions verified from PyPI, 2026-08-01: **langchain 1.3.14**, **langgraph 1.2.10**,
langsmith 0.10.15, langfuse 4.14.2. Both hit 1.0 in late Oct 2025 with a **commitment to no
breaking changes before 2.0** — which is the main reason it's now reasonable to depend on
them for production work.

Four things to know:

- **`create_react_agent` is deprecated → use `create_agent`.** LangGraph v1 is otherwise
  largely backwards compatible; this is the one migration most codebases need.
  `create_agent` runs on the LangGraph runtime and adds middleware.
- **A middleware system** hooks any point in the agent loop, with built-ins for
  **human-in-the-loop, summarisation, and PII redaction**. Those three are exactly the
  concerns this skill tells you to build — check the middleware before hand-rolling them.
- **Structured output is now inside the agent loop**, so it no longer costs an extra LLM
  call. If your code does a second call purely to coerce a shape, delete it.
- **Legacy code moved to `langchain-classic`.** Expect import moves on upgrade:
  `langchain.globals` → `langchain_core.globals`, `langchain.schema` →
  `langchain_core.outputs`, `langchain.docstore.document` → `langchain_core.documents`.

**Pin your dependencies.** A reported issue had `langgraph` failing to constrain
`langgraph-prebuilt`, letting pip resolve an incompatible pair. Pin both.

And the honest counterpoint: a visible minority of production teams are **rewriting off
LangChain onto raw provider SDKs**, on the grounds that the abstraction obscures the control
flow they need to debug. That's consistent with this file's advice — own the loop, or at
minimum know what your framework's defaults are. 1.0's stability promise makes the framework
a more defensible choice than it was; it doesn't remove the need to know what's underneath.

### If you use LangGraph: two settings that are decisions, not defaults

Surveying a production LangGraph suite (19 `StateGraph`s, 43 `ToolNode`s) turned up the same
two omissions repeatedly. Both are one line.

**`recursion_limit` IS your turn cap.** It bounds supersteps before LangGraph raises
`GraphRecursionError`. In that survey it appeared **once across 19 graphs** — so nearly every
graph ran to the framework default rather than to a considered bound.

```python
# The default is a framework author's guess about your workload. Make it yours.
result = graph.invoke(state, config={"recursion_limit": 12})
```

**The checkpointer is your durability decision.** The same codebase used all three:

| Checkpointer | Survives process death? | Right for |
|---|---|---|
| `MemorySaver` | **No** | Request-scoped runs of a few seconds. A deploy loses them. |
| `SqliteSaver` | Locally | Dev, single-node tools. |
| `PostgresSaver` | **Yes** | Anything long-running, human-gated, or with side effects. |

`MemorySaver` (19 uses) sitting alongside `PostgresSaver` (20) in one codebase is a smell
worth catching in review: if a graph waits on a human or takes external actions and is
checkpointed to memory, **a routine deploy silently drops it mid-run**. Choose per graph,
deliberately.

A reviewed example makes the failure concrete. One agent in that suite is served from a
**Slack bot** and deliberately suspends to ask the user a clarifying question — with a
hardcoded `MemorySaver`. So every deploy discards in-flight clarifications: the user answers
in Slack, the resume finds no thread, and because the caller catches the exception and "falls
back to standard processing", the conversation **silently restarts** instead of reporting an
error. The same repo already had a correct env-aware `PostgresSaver` factory that a sibling
agent used. The bug wasn't ignorance — it was a default nobody revisited.

### The module-level compiled graph is the root cause

Watch for this shape, because it's what makes the checkpointer un-injectable in the first
place:

```python
# ANTI-PATTERN — a compiled graph built at import time.
def create_graph():
    memory = MemorySaver()            # forced: there's no caller to pass one in
    return workflow.compile(checkpointer=memory)

graph = create_graph()                # runs on `import`
```

Three problems, all downstream of the same choice: the checkpointer **cannot** be injected,
so `MemorySaver` becomes the only option; importing the module opens resources as a side
effect, which breaks tests and tooling; and configuration can't vary by environment.

```python
# RIGHT — a factory, called once at startup with its dependencies.
def create_graph(checkpointer) -> CompiledStateGraph:
    ...
    return workflow.compile(checkpointer=checkpointer)

# in your startup path, not at import:
graph = create_graph(get_checkpointer_for_env())
```

What that survey got *right* and is worth copying: **388 `interrupt` calls against 159
`checkpoint` references** — real human-in-the-loop, where the graph genuinely suspends,
persists, and is resumed later by a different process. That's the state machine described
above, implemented properly, and it's rarer in practice than it should be.

One more signal from the same data: **22 `add_node` but only 1 `add_conditional_edges`**.
Those graphs are almost entirely linear — which is evidence for the thesis at the top of this
file. If your graph has no branches, a chain is simpler and you lose nothing.

## Checklist

- [ ] Chosen the **least agentic** shape that solves the problem
- [ ] Turn cap **and** budget cap, both enforced — a timeout is neither
- [ ] On LangGraph: `recursion_limit` set explicitly per graph
- [ ] Checkpointer chosen per graph — `PostgresSaver` for anything human-gated or with side effects
- [ ] Tool exceptions become observations, not loop-killers
- [ ] Repeated-identical-call detection
- [ ] Tool output truncated before entering context
- [ ] 5–15 tools, constrained types, preconditions stated, actionable errors
- [ ] Destructive tools scoped, confirmed, ideally `dry_run`-capable
- [ ] Context compaction that preserves the system prompt and original task
- [ ] System prompt byte-stable; volatile content at the end (cache safety)
- [ ] Multi-agent only for tool/permission separation, context isolation, or parallelism
- [ ] Fan-out bounded; recursion depth limited
- [ ] Durability model chosen deliberately; side effects idempotency-keyed
- [ ] Human approval modelled as suspend/persist/resume with an expiry
- [ ] Streaming cancels upstream on client disconnect
- [ ] `max_turns_exhausted` and `budget_exhausted` recorded as failures
