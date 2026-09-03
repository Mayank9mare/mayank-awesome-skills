"""A production-shaped agent loop with tracing, cost control and guardrails.

~200 lines, no framework. Copy and adapt. It exists to demonstrate the five loop
invariants that frameworks tend to hide:

  1. turn cap
  2. budget cap (a latency cap does NOT bound cost)
  3. tool errors become observations, not exceptions
  4. repeated-identical-call detection
  5. tool output truncated before it enters context

Plus the observability that makes an agent debuggable at all: one trace per run,
OTel GenAI semantic-convention attributes, prompts in span EVENTS rather than
attributes, and cost recorded as a metric attributed to something actionable.

See the ai-agents skill's references/ for the reasoning behind each choice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, Literal

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

tracer = trace.get_tracer("myagent")
meter = metrics.get_meter("myagent")

# Metrics, not just span attributes: you want to aggregate cost by route/tenant
# without querying the trace store.
_tokens = meter.create_counter("gen_ai.client.token.usage")
_cost = meter.create_histogram("gen_ai.client.cost.usd")
_turns = meter.create_histogram("agent.turns")

MAX_TURNS = 12
MAX_TOOL_CHARS = 8_000          # one SELECT * will otherwise blow the window
TOOL_TIMEOUT_S = 20.0


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
# Constrain the TYPE rather than describing validation in prose: Literal and
# Field(ge=,le=) make an invalid call impossible instead of producing an error
# the model then has to interpret.


class SearchOrders(BaseModel):
    """Search a customer's orders, most recent first.

    Use when the user asks about order history or the state of an order. Requires a
    customer_id — call lookup_customer first if you only have a name or email.
    Returns at most `limit` orders; if there are more, the oldest are omitted.
    """

    customer_id: Annotated[str, Field(description="Customer UUID from lookup_customer")]
    status: Annotated[
        Literal["pending", "shipped", "delivered", "cancelled"] | None,
        Field(description="Filter by status. Omit for all."),
    ] = None
    limit: Annotated[int, Field(ge=1, le=50)] = 20


@dataclass(frozen=True)
class ToolPolicy:
    """Side-effect class drives whether a human must approve."""

    side_effect: Literal["read", "write", "destructive", "external"]
    requires_approval: bool = False
    max_calls_per_run: int | None = None
    allowed_roles: frozenset[str] = frozenset()


POLICIES: dict[str, ToolPolicy] = {
    "search_orders": ToolPolicy("read", max_calls_per_run=20),
    "lookup_customer": ToolPolicy("read", max_calls_per_run=10),
    "issue_refund": ToolPolicy(
        "destructive",
        requires_approval=True,
        max_calls_per_run=1,
        allowed_roles=frozenset({"support_agent"}),
    ),
}


class ApprovalRequired(Exception):
    """Raised to SUSPEND the run. The caller persists state and resumes later."""

    def __init__(self, call: ToolCall) -> None:
        super().__init__(f"approval required for {call.name}")
        self.call = call


# ---------------------------------------------------------------------------
# Result / state
# ---------------------------------------------------------------------------

Outcome = Literal[
    "answered",
    "max_turns_exhausted",     # a FAILURE — counting it as success makes metrics lie
    "budget_exhausted",
    "repeat_loop",
    "awaiting_approval",
    "tool_failed",
]


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str


@dataclass
class Result:
    outcome: Outcome
    text: str | None = None
    turns: int = 0
    cost_usd: Decimal = Decimal(0)
    trace_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "answered"


@dataclass
class RunState:
    """Everything needed to resume after a suspend. Persist this verbatim."""

    task: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    spent: Decimal = Decimal(0)
    turn: int = 0
    seen_calls: set[tuple[str, str]] = field(default_factory=set)
    call_counts: dict[str, int] = field(default_factory=dict)


def _canonical(args: dict[str, Any]) -> str:
    """Stable key so {"a":1,"b":2} and {"b":2,"a":1} count as the same call."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def _truncate(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(text) <= limit:
        return text
    # Tell the model it was truncated, or it will confidently treat the partial
    # result as complete.
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


async def run_agent(
    task: str,
    *,
    principal: Principal,
    route: str,
    budget_usd: Decimal = Decimal("0.50"),
    max_turns: int = MAX_TURNS,
    state: RunState | None = None,
) -> Result:
    st = state or RunState(task=task, messages=[{"role": "user", "content": task}])

    with tracer.start_as_current_span("agent.run") as run_span:
        run_span.set_attribute("agent.name", "support-agent")
        run_span.set_attribute("agent.route", route)
        run_span.set_attribute("agent.max_turns", max_turns)
        trace_id = f"{run_span.get_span_context().trace_id:032x}"

        def finish(outcome: Outcome, text: str | None = None) -> Result:
            run_span.set_attribute("agent.outcome", outcome)
            run_span.set_attribute("agent.turns", st.turn)
            run_span.set_attribute("gen_ai.usage.cost_usd", float(st.spent))
            if outcome != "answered":
                # Non-answers must be ERROR spans or they vanish from dashboards.
                run_span.set_status(Status(StatusCode.ERROR, outcome))
            _turns.record(st.turn, {"agent.route": route, "agent.outcome": outcome})
            return Result(outcome, text, st.turn, st.spent, trace_id)

        repeats = 0

        while st.turn < max_turns:
            st.turn += 1

            with tracer.start_as_current_span("agent.turn") as turn_span:
                turn_span.set_attribute("agent.turn", st.turn)

                resp = await _chat(st.messages, route=route)
                st.spent += resp.cost_usd

                # Budget is a HARD stop: one pathological task can otherwise cost
                # more than a thousand normal ones.
                if st.spent > budget_usd:
                    return finish("budget_exhausted")

                if not resp.tool_calls:
                    return finish("answered", resp.text)

                st.messages.append(resp.assistant_message)

                for call in resp.tool_calls:
                    key = (call.name, _canonical(call.args))
                    if key in st.seen_calls:
                        # Identical call again: the model is stuck. The same
                        # observation won't change its mind — say so explicitly.
                        turn_span.add_event(
                            "agent.repeated_tool_call", {"gen_ai.tool.name": call.name}
                        )
                        st.messages.append(
                            _tool_result(
                                call,
                                "You already called this tool with identical arguments. "
                                "Try a different approach or give your final answer.",
                            )
                        )
                        repeats += 1
                        if repeats >= 2:
                            return finish("repeat_loop")
                        continue

                    st.seen_calls.add(key)
                    st.messages.append(_tool_result(call, await _dispatch(call, principal)))

        # Fell out of the loop with no final answer.
        return finish("max_turns_exhausted")


async def _dispatch(call: ToolCall, principal: Principal) -> str:
    """Authorise, then execute. Returns an OBSERVATION string — never raises for
    ordinary failures, because the model can usually recover if it sees the error."""
    with tracer.start_as_current_span("execute_tool") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", call.name)

        # Lookup table, never getattr() on a model-supplied name — that is RCE.
        policy = POLICIES.get(call.name)
        if policy is None:
            return f"Unknown tool: {call.name}"

        # Authorisation is checked HERE against the real principal, never inferred
        # from anything the model said.
        if policy.allowed_roles and not (policy.allowed_roles & principal.roles):
            return f"Not permitted: {call.name} requires {sorted(policy.allowed_roles)}"

        if policy.requires_approval and not await _approved(call, principal):
            raise ApprovalRequired(call)   # suspend; caller persists RunState

        try:
            out = await _invoke(call, timeout=TOOL_TIMEOUT_S)
        except TimeoutError:
            span.set_status(Status(StatusCode.ERROR, "tool timeout"))
            return f"Tool {call.name} timed out after {TOOL_TIMEOUT_S}s."
        except Exception as e:  # noqa: BLE001 — deliberate: becomes an observation
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, "tool failed"))
            return f"Tool failed: {type(e).__name__}: {e}"

        return _truncate(out)


async def _chat(messages: list[dict[str, Any]], *, route: str) -> ModelResponse:
    """One model call, instrumented per OTel GenAI semantic conventions."""
    with tracer.start_as_current_span("chat") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", MODEL)
        span.set_attribute("gen_ai.request.temperature", TEMPERATURE)

        resp = await client.messages.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMAS, temperature=TEMPERATURE
        )

        span.set_attribute("gen_ai.response.model", resp.model)
        span.set_attribute("gen_ai.usage.input_tokens", resp.usage.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", resp.usage.output_tokens)
        # finish_reasons is the cheapest high-value signal: a rising `length` rate
        # means you are silently truncating answers.
        span.set_attribute("gen_ai.response.finish_reasons", [resp.stop_reason])

        # Payloads go in EVENTS, never attributes: attributes are indexed and
        # size-limited, so a prompt there means PII in your index.
        span.add_event("gen_ai.content.prompt", {"gen_ai.prompt": _redact(messages)})

        for direction, n in (
            ("input", resp.usage.input_tokens),
            ("output", resp.usage.output_tokens),
        ):
            _tokens.add(n, {"gen_ai.request.model": MODEL, "direction": direction,
                            "agent.route": route})

        cost = _price(resp.usage)
        _cost.record(float(cost), {"gen_ai.request.model": MODEL, "agent.route": route})
        return ModelResponse.from_provider(resp, cost_usd=cost)


def _tool_result(call: ToolCall, content: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": call.id, "content": content}],
    }
