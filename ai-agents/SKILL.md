---
name: ai-agents
description: Use when building, reviewing or debugging an LLM agent, tool-calling loop, or AI workflow — choosing between a chain, router, evaluator-optimiser or agent loop; designing tools and their schemas; multi-agent orchestration; RAG retrieval quality; prompt caching and token cost; adding tracing with OpenTelemetry GenAI conventions; evaluation and LLM-as-judge; prompt injection and tool permissions; human-in-the-loop approvals; durable/resumable runs. Also for "my agent loops forever", "the agent picks the wrong tool", "LLM costs too much", "how do I trace an agent", "agent gives inconsistent answers".
---

# AI Agents & Workflows

## Overview

An agent is a **non-deterministic distributed system whose control flow is chosen at runtime
by a model**. That single sentence explains most of what's different: you can't unit-test
your way to confidence, logs won't tell you why a decision was made, and the failure modes
are "didn't stop", "picked the wrong tool", and "was confidently wrong" rather than
exceptions.

Two consequences drive everything here. **Prefer the least agentic design that works** —
most production "agents" should be workflows. And **you cannot operate what you cannot
trace** — tracing and evaluation are not observability polish, they're how you know whether
a change helped.

Library versions verified from PyPI, 2026-08-01: **langchain 1.3.14** · **langgraph 1.2.10**
(both past 1.0, so no breaking changes promised before 2.0) · langfuse **4.14.2** ·
langsmith **0.10.15** · openai **2.52.0** · anthropic **0.120.2**. Note
`create_react_agent` is **deprecated** in favour of `create_agent` — see
references/architecture.md.

## When to Use

- Designing an LLM feature and deciding chain vs router vs agent loop
- Writing or reviewing tool definitions and their schemas
- Debugging: infinite loops, wrong tool selection, degrading answers, runaway cost
- Adding tracing, cost attribution, or evaluation to an existing agent
- Multi-agent orchestration, or deciding whether you need it (usually not)
- RAG that retrieves the wrong things
- Prompt injection, tool permissions, human approval flows
- Long-running or resumable agent runs

**Not for:** training/fine-tuning models, classical ML pipelines, or prompt-only
single-shot use with no tools and no loop.

## Step 0: Choose the least agentic shape

| Shape | Control flow | Use when |
|---|---|---|
| **Single prompt** | none | One transformation — classify, extract, summarise. |
| **Chain** | fixed, sequential | Steps known and ordered. |
| **Router** | one decision, then fixed | Classify input into a few known paths. |
| **Parallel + reduce** | fixed, concurrent | Independent subtasks then a merge. |
| **Evaluator–optimiser** | bounded loop | Quality is checkable and iteration helps. |
| **Agent (tool loop)** | model-decided | Steps genuinely can't be known in advance. |
| **Multi-agent** | delegated | Separable concerns needing different tools/permissions. |

**If you can enumerate the steps, write them.** A 3-step chain is 3 calls with known
latency and ordinary assertions. The same task as a tool loop averages 6–10 calls, sometimes
20, and occasionally never terminates. Full reasoning in references/architecture.md.

## Quick Reference

| Task | Approach | Detail |
|---|---|---|
| Pick an architecture | Least-agentic shape that works | references/architecture.md |
| The agent loop | Turn cap + budget cap + repeat detection | references/architecture.md |
| Tool schemas | Constrained types, stated preconditions, actionable errors | references/architecture.md |
| Tracing | **OTel GenAI semconv**, one instrumentation layer | references/observability.md |
| Cost control | Metrics by route/tenant; child costs on the trace root | references/observability.md |
| Evaluation | Deterministic asserts → validated LLM judge → human | references/observability.md |
| Prompt injection | Capability limits, **not** prompt instructions | references/safety-guardrails.md |
| Tool permissions | Policy table + authorisation in code | references/safety-guardrails.md |
| Human approval | Suspend → persist → resume, with expiry | references/safety-guardrails.md |
| RAG quality | Chunking, hybrid search, rerank, citation checks | references/rag-retrieval.md |
| Prompt engineering | Structure, caching, few-shot, output formats | references/prompting.md |
| Durability | Checkpoint per turn; idempotency keys | references/architecture.md |

## The five loop invariants

Every one of these maps to a real incident. If your framework hides them, find out what its
defaults are.

1. **Turn cap.** Without it, "keep trying" runs until something else breaks.
2. **Budget cap.** A latency cap does not bound cost. A fast loop burns money fast.
3. **Tool errors become observations, not exceptions.** Most recoverable failures are
   recoverable *by the model* — if it can see the error.
4. **Repeated-identical-call detection.** Same tool, same args means stuck; the same
   observation will not change its mind.
5. **Truncate tool output before it enters context.** One `SELECT *` blows the window and
   takes the task down.

And record `max_turns_exhausted` / `budget_exhausted` as **failures**. Counting them as
successes makes your success rate a lie.

**A timeout is none of these.** In a survey of production agents, timeouts appeared in 52
files while `max_turns`/`max_iterations`/`budget`/`cost_limit` appeared **zero** times — the
normal shape, because bounding latency is the reflex carried over from HTTP services. A
timeout stops one hung call; it does not stop a loop that keeps making cheap, successful
progress for an hour. **On LangGraph, `recursion_limit` IS your turn cap** — and it defaults
to a framework author's guess, so set it per graph.

## The non-negotiables

1. **Trace before you scale.** One trace per user request, with turns, model calls and tool
   calls as nested spans. Debugging an agent from flat logs is guesswork.
2. **OTel GenAI semantic conventions** for attribute names — not homegrown ones.
3. **Prompts/completions in span *events*, never attributes.** Attributes are indexed and
   size-limited: raw prompts there mean PII in your index and truncated telemetry.
4. **Instrument at exactly one layer.** Auto-instrumentation + framework tracing + manual
   spans = every call counted twice, and a cost dashboard that's wrong but plausible.
5. **Cost as a metric, attributed to something actionable** (route, tenant, agent). Sum
   child costs onto the trace root.
6. **Model output is untrusted input.** Never `eval` it; never dispatch tools via dynamic
   attribute access on a model-supplied name.
7. **Authorise in code, against the real principal.** The model may *request* an action; your
   code decides if it's allowed.
8. **Never combine private data + untrusted content + an exfiltration path** in one agent.
   Remove any one leg and injection stops being catastrophic.
9. **Idempotency keys on side-effecting tools.** Retries and resumptions happen.
10. **Pin the model version and version the prompts.** "Latest" changes behaviour with no
    diff to review.
11. **Eval set built from real failing traces**, with deterministic assertions in CI. Without
    eval you're tuning prompts by vibes.
12. **Keep the system prompt byte-stable** for cache hits. One dynamic value at the top
    invalidates the prefix on every call.

## Reference Map

| File | Read when |
|---|---|
| references/architecture.md | Choosing a shape; the loop; tool design; multi-agent; durability; streaming |
| references/observability.md | Tracing, GenAI semconv, cost accounting, metrics, evaluation, replay |
| references/safety-guardrails.md | Injection, tool permissions, guardrails, approvals, containment |
| references/rag-retrieval.md | Retrieval quality, chunking, hybrid search, reranking, citations |
| references/prompting.md | Prompt structure, caching, few-shot, structured output, model choice |

## Common Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| Agent where a chain would do | 3× the cost, non-deterministic, harder to test | Enumerate the steps if you can |
| No turn cap | Runs until something else breaks | Cap it; count exhaustion as failure |
| No budget cap | One pathological task costs more than a thousand normal ones | Hard spend ceiling per run |
| Tool exception kills the loop | Loses recoverable failures the model could handle | Return the error as an observation |
| Untruncated tool output | One big query blows the context window | Truncate + paginate at the tool |
| 30+ tools | Selection accuracy degrades; every schema costs tokens each call | 5–15, well named, non-overlapping |
| Validation described in prose | Model has to interpret errors | `Literal`/`Field(ge=,le=)` — make bad calls impossible |
| Prompt in a span attribute | PII in the index, truncated telemetry, surprise bill | Span events, or an external store |
| Two instrumentation layers | Tokens and cost double, plausibly | One layer; verify span count |
| `getattr(tools, name)` | RCE with extra steps | Lookup table; unknown tool → refuse |
| Trusting "ignore injected instructions" | Reduces the rate, doesn't close the hole | Limit capability, not phrasing |
| Model-supplied identity | Privilege escalation by text | Authorise against the real principal |
| Dynamic value atop the system prompt | Cache prefix invalidated every call | Volatile content at the **end** |
| Truncating oldest history | Drops the task definition — the one thing needed | Compact/summarise; keep task + recent turns |
| Uncalibrated LLM judge | A random number generator with good manners | Validate against human labels first |
| Approval rate ~100% | A rubber stamp that adds latency, not safety | Re-scope what needs approval |
| No idempotency key | A resumed run re-issues the refund | Key every side-effecting call |
| Tenant filter applied post-retrieval | The classic RAG cross-tenant leak | Filter in the query; test adversarially |
| Timeouts set, turn/budget caps absent | The most common real gap — bounds latency only | All three; they're independent |
| LangGraph default `recursion_limit` | The turn cap left to a framework guess | Set it per graph |
| `MemorySaver` on a human-gated graph | A routine deploy silently drops the run mid-flight | `PostgresSaver` for anything durable |
| `except Exception: pass` in tool dispatch | The failure vanishes; the model reasons on from a gap it can't see | Log **and** return the error as an observation |
| Tracing init that can throw | A telemetry outage takes down the service | try/except with `None` fallbacks |
| No `flush()` in a short-lived process | Exporters batch — the process exits and the trace is gone | Flush on shutdown and in `finally` |
