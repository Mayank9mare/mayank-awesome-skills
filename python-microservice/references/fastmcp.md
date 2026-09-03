# Building MCP servers with FastMCP

MCP (Model Context Protocol) lets an LLM client discover and call your tools. FastMCP is
the high-level Python way to build a server.

Verified 2026-08.

## First: pick the right package

There are **two** implementations, both with a class people call "FastMCP". Copying a
snippet from one into the other misbehaves — often silently.

Versions from PyPI, 2026-08-01: **`fastmcp` 3.4.5 (stable)** · **`mcp` 2.0.0** (released
2026-07-28, **GA — not a beta**).

> **`fastmcp` 4.x is in beta** — `4.0.0b1` is on PyPI alongside two alphas. **3.4.5 is the
> stable line and what `pip install fastmcp` gives you.** Pin `fastmcp>=3.4,<4` if you want
> to be sure a resolver never drifts you onto 4.x, and read the 4.0 notes before adopting —
> given 2.x→3.x replaced mounting with a Providers/Transforms model, assume 4.0 moves things
> again. The project also now lives under the **PrefectHQ** org (formerly `jlowin/fastmcp`),
> so older links redirect.

| | standalone **`fastmcp`** | official **`mcp`** SDK **2.x** | official `mcp` **1.x** (legacy) |
|---|---|---|---|
| Install | `pip install fastmcp` | `pip install mcp` | `pip install "mcp<2"` |
| Import | `from fastmcp import FastMCP` | `from mcp.server import MCPServer` | `from mcp.server.fastmcp import FastMCP` |
| Class name | `FastMCP` | **`MCPServer`** (renamed) | `FastMCP` |
| Tool decorator | `@mcp.tool` (bare canonical; parens needed only to pass metadata) | `@mcp.tool()` | `@mcp.tool()` |
| Transport arg | `transport="http"` | `transport="streamable-http"` | `transport="streamable-http"` |
| Host/port | CLI flags, decoupled from code | constructor kwargs | constructor kwargs |
| OAuth | `OAuthProxy`, `RemoteAuthProvider`, OIDC helpers built in | you wire discovery/validation/PKCE | same |
| Testing | in-memory `Client` transport — no sockets | no first-class in-memory client | same |
| CLI | `fastmcp run` / `fastmcp dev` | none | none |

### The `mcp` 1.x → 2.0 migration is a rewrite, not a rename

**`mcp.server.fastmcp.*` is GONE in 2.0 — removed, not deprecated.** Everything moved to
`mcp.server.mcpserver.*`. Any code or tutorial using the old path fails to import on 2.0.

Why so brutal: the **2026-07-28 spec** moved MCP from a stateful, bidirectional,
session-oriented protocol to **stateless request/response**. The 1.x SDK was built around
long-lived sessions, so supporting the new spec meant replacing the core — and since that
was breaking anyway, 2.0 also fixed accumulated API problems.

The parts that will actually break you:

- **Decorators survive.** `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()` keep the same
  arguments and handler signatures. If you built with decorators, the rename is most of
  the port.
- **Every field is `snake_case`** now (`result.is_error`, `tool.input_schema`,
  `listing.next_cursor`). The JSON on the wire is still camelCase.
- **Symbol moves**: `Image`/`Audio`/`Icon` → `mcp.server.mcpserver`;
  `Message`/`UserMessage`/`AssistantMessage` → `mcp.server.mcpserver.prompts.base`;
  `ToolError`/`ResourceError` → `mcp.server.mcpserver.exceptions`;
  `FastMCPError` → **`MCPServerError`**; `McpError` → **`MCPError`**.
- **Wire types split out** into a separate `mcp-types` distribution, imported as
  `mcp_types` (depends only on Pydantic + typing-extensions).
- **The lowlevel `Server` API changed shape**: handlers are constructor parameters, not
  decorators, and return values are no longer auto-wrapped. A new Dispatcher pipeline
  replaces `ServerSession` server-side (`ServerSession` remains a thin proxy).
- **Removed entirely**: WebSocket transport (and the `mcp[ws]` extra); the experimental
  Tasks API. httpx/httpx-sse replaced by httpx2.
- **Pin defensively.** If your package depends on `mcp`, keep `mcp>=1.28,<2` until you've
  migrated — an unpinned install now resolves to 2.x and breaks. The 1.x line still gets
  critical bug and security fixes, with docs under `/v1/`.

The official [migration guide](https://py.sdk.modelcontextprotocol.io/migration/) is the
best 2.x documentation; each heading names the affected API, so searching the page for the
symbol that broke is the fastest route.

**Recommendation unchanged: use standalone `fastmcp`** unless you're hard-constrained to
depend only on `mcp`. It's a superset with better docs, OAuth helpers, an in-memory test
client and HTTP deployment helpers. **Requires Python 3.10+.**

**Recommendation: use standalone `fastmcp`** unless something hard-constrains you to
depend only on `mcp`. It's effectively a superset — better docs, OAuth helpers, an
in-memory test client, HTTP deployment helpers. **Requires Python 3.10+.**

### Why the mismatch is silent rather than loud

- `transport="http"` on the official SDK either errors on an unknown transport or falls
  through to a default. Your server starts, logs look fine, and the client fails later
  with a confusing "connection refused" or `406 Not Acceptable`.
- `@mcp.tool` (no parens) against the SDK's decorator raises a cryptic `TypeError` about
  a missing argument — or, if defensively wrapped, registers the decorator factory
  itself as a broken "tool".

Pin your version and confirm which package you're on before copying any snippet.

## Transports

| Value | Use |
|---|---|
| `"stdio"` | **Default for local tools.** The client spawns your script and talks over stdin/stdout. No network, no auth needed. |
| `"streamable-http"` | **The transport for anything remote or multi-client.** Single endpoint, supports resumable streaming via an `EventStore`. |
| `"http"` | Modern alias for `streamable-http` — **standalone `fastmcp` only.** |
| `"sse"` | **DEPRECATED.** |

**Do not use SSE.** The two-endpoint HTTP+SSE transport was superseded by single-endpoint
Streamable HTTP in MCP spec revision **2025-03-26**. Many tutorials still say
`transport="sse"` — they're stale. Only reach for it as a compatibility shim for old
clients.

Precision worth having, since "SSE is dead" overstates it:

- The **SSE transport mode is deprecated but still present** — it has not been deleted.
  Deprecated MCP features now follow a formal lifecycle giving roughly a year's notice
  before removal becomes possible.
- **SSE *resumability* — `Last-Event-ID`-based stream resumption — was removed** from
  Streamable HTTP. So if your design depended on a client reconnecting and replaying a
  missed stream, that specific capability is gone; use an `EventStore` (below) or design
  for idempotent replay instead.

### Spec revisions to know

| Revision | What it brought |
|---|---|
| **2025-03-26** | Streamable HTTP replaces two-endpoint HTTP+SSE. |
| **2025-06-18** | OAuth 2.1 standardised for remote servers (PKCE mandatory, DCR, Protected Resource Metadata). |
| **2026-07-28** | **Current.** Stateless request/response model — sessions removed. Multi-round-trip requests, a Tasks extension, and deprecation of the Roots/Sampling/Logging capabilities. This is the revision that forced the `mcp` SDK 2.0 rewrite. |

The stateless shift is the one with architectural consequences: a server can no longer
assume it holds per-client session state between calls, which is what makes horizontal
scaling behind a load balancer straightforward instead of requiring sticky sessions.

The detailed 2026-07-28 changelog items above come from secondary sources —
**verify against the official spec changelog** before depending on any single one.

## Decorators

```python
@mcp.tool                                    # an action the LLM can execute
@mcp.resource("resource://uri")              # read-only data source (static or templated)
@mcp.prompt                                  # reusable prompt template
@mcp.custom_route("/healthz", methods=["GET"])   # plain HTTP route on the same app
```

In standalone FastMCP 3.x, **bare `@mcp.tool` is canonical**; add parentheses only when
passing metadata (`name=`, `description=`, `tags=`, `meta=`). `@mcp.resource(...)` and
`@mcp.custom_route(...)` always take arguments. `custom_route` handlers must be **async**,
take a Starlette `Request` and return a `Response` — use it for health checks, OAuth
callbacks and admin endpoints.

**Footgun: bare `@mcp.tool` does not work on methods.** It registers at decoration time,
before the class exists, so `self` (or `cls`) is exposed to the LLM as a required
parameter — a tool the model can never call correctly. Register methods explicitly instead:

```python
class OrderTools:
    def __init__(self, repo): self.repo = repo

    async def find_order(self, order_id: str) -> dict:
        """Look up an order by id."""
        return await self.repo.get(order_id)

tools = OrderTools(repo)
mcp.add_tool(Tool.from_function(tools.find_order))   # bound method — no self in the schema
```

Module-level functions with the bare decorator are fine; that's the common case.

## Type hints become the schema

FastMCP builds the MCP `inputSchema` (JSON Schema) from your **type hints**, and the
tool `description` the LLM sees from your **docstring**. Standard types, `Literal`,
`Enum`, Pydantic models, dataclasses and `TypedDict` all map to nested JSON Schema.

That has two consequences worth internalising:

1. **The docstring is a prompt, not a comment.** It is the primary thing determining
   whether the model calls your tool correctly. Say what it does, when to use it, what
   the arguments mean, and what it returns.
2. **`TYPE_CHECKING`-only imports in a tool signature break schema generation — confirmed,
   with a concrete mechanism.** FastMCP builds schemas through Pydantic's `TypeAdapter`
   (cached via `get_cached_typeadapter()`, `lru_cache(maxsize=5000)`), and resolves forward
   references with **`get_type_hints()`**, which evaluates in **VALUE** mode. A name that
   only exists under `if TYPE_CHECKING:` does not exist at runtime, so resolution raises
   **`NameError`**.

   Note this is *not* the same as FastAPI's fix: FastAPI moved to
   `annotationlib.Format.FORWARDREF`, which returns unresolved `ForwardRef` objects instead
   of raising. That wouldn't fully rescue FastMCP anyway — Pydantic still needs a real class
   to build a schema from, so an unresolved `ForwardRef` fails at the schema-building step
   instead of the resolution step.

   **Import the types used in tool signatures for real.** No `TYPE_CHECKING` guard.

   Two adjacent failure modes with the same symptom:
   - **Return annotations are load-bearing.** When you don't supply an output schema,
     FastMCP derives one from the return annotation — so a `TYPE_CHECKING`-only *return*
     type breaks registration just as surely as a parameter type.
   - **Unsupported return types** raise `PydanticSchemaGenerationError`: a custom or
     third-party class Pydantic can't schematise. Return a dict, a Pydantic model, or a
     dataclass — not an arbitrary domain object.

```python
from typing import Annotated, Literal
from pydantic import Field

@mcp.tool
def search_orders(
    customer_id: Annotated[str, Field(description="Customer UUID")],
    status: Literal["pending", "shipped", "cancelled"] = "pending",
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> list[dict]:
    """Search a customer's orders by status.

    Use this when the user asks about order history or the state of an order.
    Returns the most recent orders first. Does not include cancelled orders
    older than 90 days.
    """
    ...
```

`Annotated[..., Field(...)]` gives per-argument descriptions and constraints, which the
client shows the model — and constraints reduce invalid calls.

## The `Context` object

Declare `ctx: Context` on any tool/resource/prompt and FastMCP injects it. It is **not**
part of the client-visible schema.

```python
from fastmcp import Context

@mcp.tool
async def reindex(collection: str, ctx: Context) -> dict:
    """Rebuild the search index for a collection."""
    await ctx.info(f"starting reindex of {collection}")     # → client log notification
    total = await count(collection)
    for i, batch in enumerate(batches(collection)):
        await index(batch)
        await ctx.report_progress(i + 1, total, message=f"batch {i + 1}/{total}")
    return {"indexed": total}
```

Capabilities: **logging** (`ctx.info/warning/error`), **progress**
(`ctx.report_progress`), **sampling** (`ctx.sample(...)` — your tool asks the *client's*
LLM to generate something, inverting the usual direction), **elicitation** (prompt the
user for structured input mid-call), and request/session state.

Note progress only streams meaningfully over `streamable-http`; a single
request/response transport won't surface incremental updates the same way.

## Auth (OAuth 2.1)

MCP spec **2025-06-18** standardised **OAuth 2.1** for remote servers — PKCE mandatory,
Dynamic Client Registration (RFC 7591), Protected Resource Metadata (RFC 9728).

Standalone FastMCP ships helpers so you don't hand-roll this:

- **`OAuthProxy`** — bridges a conventional provider (GitHub, Google, Azure) that
  doesn't support DCR into an MCP-compliant flow, registering clients locally and
  delegating token exchange upstream with separate PKCE flows at each boundary.
- **`RemoteAuthProvider`** — FastMCP acts purely as a resource server, validating JWTs
  from an external authorization server via JWKS.
- OIDC proxies that auto-discover endpoints from `/.well-known/openid-configuration`.

These serve the `/.well-known/oauth-protected-resource` and
`/.well-known/oauth-authorization-server` discovery routes for you — you generally do
**not** need `@mcp.custom_route` handlers for them.

The client-side contract, either way: `401` → read `WWW-Authenticate` → fetch protected
resource metadata → discover the authorization server → DCR if supported →
Authorization Code + PKCE (S256) including the `resource` parameter (RFC 8707) on both
authorization and token requests → bearer token → retry.

## Mounting into an existing FastAPI app

```python
from fastapi import FastAPI
from fastmcp import FastMCP

mcp = FastMCP("my-mcp-server")

@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

mcp_app = mcp.http_app(path="/")

# CRITICAL: forward the MCP app's lifespan, or its session manager/task group
# never starts. The routes mount fine and tools then fail at call time —
# a confusing, common bug.
app = FastAPI(lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)
```

If your host app has its own lifespan, compose them with
`contextlib.AsyncExitStack` rather than dropping either.

For long-running streams, plug in an `EventStore` so a client that disconnects
mid-stream can resume from the last event ID instead of restarting.

## Testing — in-memory, no sockets

```python
import pytest
from fastmcp import FastMCP, Client

mcp = FastMCP("test-server")

@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

@pytest.mark.asyncio
async def test_add():
    async with Client(mcp) as client:          # in-memory transport
        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert result.data == 5

@pytest.mark.asyncio
async def test_tools_are_discoverable():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert "add" in {t.name for t in tools}
        # Descriptions are the model's only guidance — assert they exist.
        assert all(t.description for t in tools)
```

The client returns structured objects rather than raw values, so you'll usually want a
small extraction helper. Also worth testing: that every tool has a non-empty
description, and that invalid arguments produce a clean error rather than a traceback.

## A complete server

```python
# server.py
from fastmcp import FastMCP, Context

mcp = FastMCP("demo-server")

@mcp.tool
async def get_weather(city: str, ctx: Context) -> dict:
    """Fetch current weather for a city.

    Use when the user asks about current conditions. Returns temperature in
    Celsius and a one-word condition summary.
    """
    await ctx.info(f"looking up weather for {city}")
    # ... real API call here, with a timeout (see http-clients.md) ...
    return {"city": city, "temp_c": 21, "condition": "clear"}

@mcp.resource("config://app-version")
def app_version() -> str:
    """The running application version."""
    return "1.0.0"

@mcp.prompt
def summarize(topic: str) -> str:
    """Reusable summarization prompt."""
    return f"Summarize the key points about {topic} in three bullets."

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("ok")

if __name__ == "__main__":
    mcp.run(transport="stdio")     # local; see below for remote
```

Local (client spawns it): `python server.py`

Remote:
```sh
fastmcp run server.py:mcp --transport=streamable-http --host=0.0.0.0 --port=8080
fastmcp dev server.py:mcp        # with the MCP Inspector attached
```

`server.py:mcp` is module path : instance variable name.

## stdio vs HTTP — deciding

**stdio** when the server is a locally installed tool invoked by one desktop client. The
trust boundary is "you can run a process on this machine", so no auth is needed, there's
no network config, and it's trivially simple. Wrong for anything multi-tenant or remote.

**streamable-http** when the server is remote, shared by a team, multi-client, or must
outlive a single client process. Then it's a real service: put it behind uvicorn/granian
and a reverse proxy, add OAuth 2.1, and apply everything in observability.md and
packaging-deploy.md — an MCP server reachable over the network is a web service and
deserves the same rigour.

## Tool-design notes

Beyond the mechanics, the things that make an MCP server actually usable:

- **Few, well-named, well-described tools** beat many overlapping ones. The model picks
  from descriptions; ambiguity produces wrong calls.
- **Constrain inputs** with `Literal`, enums and `Field(ge=…, le=…)`. Cheaper than
  validating and explaining an error afterwards.
- **Return structured data**, not prose. Let the model do the narrating.
- **Errors should be actionable.** "customer_id not found: <id>" tells the model what to
  do next; a stack trace doesn't.
- **Keep tools idempotent** where possible — a model may retry.
- **Never expose an unbounded destructive tool.** If a tool can delete, scope it, require
  explicit identifiers, and consider a dry-run parameter.
- **Paginate.** A tool returning 10,000 rows will blow the client's context window.
