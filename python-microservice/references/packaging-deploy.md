# Packaging & Deploy

## uv — the modern toolchain

`uv` is a single Rust binary replacing `pip`, `pip-tools`, `virtualenv`,
`pipx`, and (for most projects) `poetry`/`pdm` — one order of magnitude
faster dependency resolution and installs, one tool instead of four.

```bash
uv init myservice              # scaffold pyproject.toml + src layout
uv add fastapi 'uvicorn[standard]'   # add a runtime dependency, updates pyproject + lock
uv add --dev pytest ruff       # add a dev-only dependency group
uv lock                        # (re)resolve, write uv.lock
uv sync --frozen               # install EXACTLY what's in uv.lock — no re-resolution
uv run pytest                  # run inside the project's venv, no manual activate
uv tool install ruff           # install a CLI tool globally, isolated from any project venv
uv python pin 3.14             # pin the interpreter version for this project
```

**Lockfile discipline**: commit `uv.lock`. Use `uv sync --frozen` in CI and in
Docker builds — `--frozen` refuses to touch the lockfile and fails loudly if
`pyproject.toml` and `uv.lock` have drifted, instead of silently re-resolving
and installing different versions than what was tested. A build that can
silently resolve different versions than the last one is a build you can't
reproduce.

| Tool | Status | Verdict |
|---|---|---|
| **uv** | Current, actively developed | Default choice for new projects. |
| Poetry | Mature, widely used | Fine if already adopted; slower resolver, its own lock format. |
| PDM | Mature | PEP 621-native early; uv has mostly closed the gap. |
| pip-tools | Maintenance-oriented | `pip-compile`/`pip-sync` still work; no project/venv management. |
| pip | Stdlib-adjacent baseline | No lockfile, no resolver strategy pinning — avoid for anything beyond a one-off script. |

## pyproject.toml anatomy

```toml
[project]
name = "myservice"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    # FastAPI is pre-1.0, so a minor bump CAN break. Pin a floor and a ceiling on
    # the MINOR, not the patch — `<0.137` would block every bugfix release.
    "fastapi>=0.141,<0.142",
    "uvicorn[standard]>=0.52",
    "pydantic-settings>=2.14",
    "sqlalchemy[asyncio]>=2.0.51",
]

[dependency-groups]           # PEP 735 — replaces the old [project.optional-dependencies] dev-deps hack
dev = ["pytest>=8", "pytest-asyncio>=1.4", "ruff>=0.16", "mypy>=2.3"]
test = ["testcontainers", "respx", "hypothesis"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

`[project]` is PEP 621 — the standardized, tool-agnostic metadata table every
modern build backend (hatchling, setuptools, pdm-backend) reads the same way.
`dependency-groups` (PEP 735) is the standardized replacement for stuffing dev
tooling into `optional-dependencies`: dev/test tooling was never actually an
*optional feature of the package* the way `extras` are, and mixing the two
made `pip install myservice[all-extras]` accidentally pull in test tooling for
end users.

**src-layout vs flat layout**:

```
# src-layout (recommended)
pyproject.toml
src/myservice/__init__.py
tests/

# flat layout
pyproject.toml
myservice/__init__.py
tests/
```

With a flat layout, running `pytest` or `python -m myservice` from the repo
root can import `myservice` straight off the filesystem — the package under
test is the *source tree*, not the *installed* package, even if you never
ran `pip install -e .`. That hides real packaging bugs: a missing entry in
`packages`/`include`, a data file that isn't actually bundled, an import that
only works because a sibling directory happens to be on `sys.path`. With
src-layout, `src/` is not importable by accident — Python only sees
`myservice` if it's actually installed (editable or not), so "tests pass
locally" reliably means "the installed package works," which is the thing you
actually care about.

## Config with pydantic-settings

```python
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")
    host: str
    port: int = 5432
    password: SecretStr

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",          # local dev convenience; absent in prod, that's fine
        env_nested_delimiter="__",
        extra="forbid",           # an unrecognized env var is a typo, fail on it
    )
    environment: str = "production"
    database: DatabaseSettings
    api_key: SecretStr

    @field_validator("environment")
    @classmethod
    def known_environment(cls, v: str) -> str:
        if v not in {"production", "staging", "development"}:
            raise ValueError(f"unknown environment: {v}")
        return v

settings = Settings()   # instantiated at IMPORT TIME
```

Instantiating `Settings()` at module import time — not lazily inside a
request handler — means a missing or invalid environment variable fails the
process at startup, loud and immediate, before it ever accepts traffic.
Deferring validation to first use means the same misconfiguration instead
surfaces as a 500 on whichever request happens to touch that field first,
which in practice means 3am, in production, on the on-call's phone.

Secrets: never baked into the image, never logged. `SecretStr` prevents the
value from appearing in a `repr()`, a traceback, or an accidental
`logger.info(f"settings: {settings}")` — it renders as `SecretStr('**********')`
and requires an explicit `.get_secret_value()` to expose the real string.

## Dockerfile with uv

```dockerfile
# --- builder ---
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies BEFORE source: this layer only invalidates when pyproject.toml
# or uv.lock change, not on every source edit — the single most impactful
# Docker cache-efficiency rule for Python images.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime ---
FROM python:3.14-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --chown=appuser:appuser src/ ./src/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8000
CMD ["uvicorn", "myservice.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- **Layer ordering**: copying `pyproject.toml` + `uv.lock` and running `uv
  sync` before `COPY src/` means editing application code — the thing that
  changes on every commit — never invalidates the dependency-install layer,
  which is the slow, network-bound one. Get this backwards and every commit
  re-downloads and re-resolves the entire dependency tree.
- `uv sync --frozen --no-dev` — `--frozen` refuses to re-resolve (see lockfile
  discipline above), `--no-dev` excludes the `dev`/`test` dependency groups
  from the image entirely.
- The cache mount (`--mount=type=cache,target=/root/.cache/uv`) persists uv's
  download/build cache across builds on the same builder without baking it
  into any image layer — faster rebuilds, no bloat.
- Non-root user (`appuser`) — a container running as root that gets
  compromised hands the attacker root inside the container, and depending on
  the runtime's isolation, a path toward the host.
- `PYTHONUNBUFFERED=1` — without it, stdout is block-buffered when not
  attached to a TTY (which a container's stdout never is), so logs sit in a
  buffer instead of reaching `docker logs`/your log collector promptly, which
  is actively dangerous during an incident where the last few log lines are
  the ones that explain what happened.
- `PYTHONDONTWRITEBYTECODE=1` — skips writing `.pyc` files to disk in the
  running container; they buy nothing at runtime here (the image is rebuilt,
  not reused across code changes) and just add filesystem writes and image
  layer noise.
- `.dockerignore` should exclude `.venv/`, `__pycache__/`, `tests/`, `.git/`,
  `*.pyc` — anything not needed to build or run the image, so it never enters
  the build context and never accidentally ends up copied in by a broad `COPY
  . .` elsewhere.

**The alpine trap, explained properly**: Alpine Linux uses `musl` as its C
standard library, not `glibc`. The prebuilt Python wheels on PyPI
(`manylinux*` tagged) are built against `glibc` and simply don't apply to
Alpine — `pip`/`uv` fall back to building any C-extension dependency
(`pydantic-core`, `cryptography`, `asyncpg`, half of a typical dependency
tree) **from source, inside the build**. That means a C compiler toolchain in
the build image, dramatically slower builds (minutes instead of seconds for
the same dependency set), and occasionally genuine runtime differences
between musl's and glibc's implementations of things like DNS resolution or
locale handling that show up as hard-to-reproduce bugs specific to the
Alpine-built image. The image size savings Alpine promises rarely survive
contact with a real dependency tree once you've added back a build toolchain
and any missing shared libraries.

**Recommendation: `python:3.x-slim`** (Debian-based, glibc, wheels apply
directly, small already) for the default case. **Distroless**
(`gcr.io/distroless/python3`) is worth reaching for once you want the
smallest possible attack surface and are comfortable losing the shell —
there's no package manager, no shell, nothing to `exec` into for debugging,
which is a deliberate trade-off, not a free upgrade.

## Servers

```bash
# uvicorn directly — fine for a single process, or as the worker under gunicorn
uvicorn myservice.main:app --host 0.0.0.0 --port 8000 --workers 4

# gunicorn + uvicorn-worker (current) supervises N uvicorn workers, handles
# worker restarts, integrates with process managers expecting gunicorn's CLI
gunicorn myservice.main:app -k uvicorn_worker.UvicornWorker -w 4 --bind 0.0.0.0:8000
```

`uvicorn.workers.UvicornWorker` is **DEPRECATED** — the worker class moved out
of the `uvicorn` package into a separate `uvicorn-worker` package
(`uvicorn_worker.UvicornWorker`). Code and docs still referencing
`uvicorn.workers` are pinned to an old uvicorn version or simply stale.

**Granian** — a Rust-based ASGI/WSGI server, worth evaluating as an
alternative to the gunicorn+uvicorn combination; fewer moving parts (one
process manager, not two), competitive or better throughput in benchmarks.
Current and actively developed, but with a smaller operational track record
than uvicorn/gunicorn — evaluate under your own load profile before betting
production on it.

**Worker-count guidance**: for a traditional **sync** WSGI app, `(2 × cores)
+ 1` — the classic gunicorn formula, sized for a worker blocking on I/O half
the time. For an **async** ASGI app under uvicorn, each worker's event loop
already handles concurrent I/O-bound requests without blocking, so start
around **≈1 worker per core** and load-test from there — more workers than
cores mostly adds memory and context-switch overhead without adding
throughput, since the bottleneck for a well-written async app is CPU, not
threads waiting on I/O. Either formula is a starting point, not a
substitute for load-testing your actual workload.

`--preload` (gunicorn) loads the application once in the master process
*before* forking workers, so workers share the loaded code and initial
memory pages via **copy-on-write** instead of each worker separately
importing and initializing the app. `gc.freeze()`, called right after
`--preload`'s import completes, moves all currently-tracked objects into a
permanent generation the garbage collector never scans again — normally, the
GC's mark-and-sweep touches (and thus dirties) the `refcount` field on every
object it visits, including ones inherited from the parent via copy-on-write,
which defeats the memory sharing one object at a time as each worker's GC
runs. Freezing the pre-fork heap keeps those pages genuinely shared and
un-dirtied across all workers, which is where the real memory savings from
`--preload` come from.

## Graceful shutdown

```bash
gunicorn myservice.main:app -k uvicorn_worker.UvicornWorker \
    --timeout-graceful-shutdown 30
```

Correct SIGTERM ordering:

1. **Fail readiness** (`/readyz` starts returning non-200) the instant SIGTERM
   is received — before doing anything else.
2. **Wait for load-balancer propagation** — the LB/service-mesh's view of
   "this pod is unready" is eventually consistent; it takes a moment for the
   endpoint to actually stop receiving new traffic after the readiness probe
   flips.
3. **Stop accepting new connections.**
4. **Drain** — let in-flight requests finish.
5. **Close pools/clients** — DB engine, the shared `httpx.AsyncClient` from
   `http-clients.md`, any broker connections — last, only once nothing is
   using them.

The pre-stop delay in step 2 is necessary precisely because step 1 is not
instantaneous system-wide: requests keep arriving for some window after
SIGTERM is sent, simply because the load balancer hasn't caught up yet. Skip
the delay and shut down immediately on SIGTERM, and every deploy produces a
burst of 5xx/connection-reset errors for the requests that were in flight to
an endpoint the LB hadn't yet removed — this is the single most common cause
of "every deploy causes a few seconds of errors."

`terminationGracePeriodSeconds` (Kubernetes) or the equivalent in any
orchestrator must exceed the full budget above: pre-stop delay + drain time +
connection close. Set it too short and the orchestrator SIGKILLs the process
mid-drain, which is exactly the failure mode graceful shutdown exists to
prevent.

## Migrations at deploy

Run schema migrations as a **separate Job/step** in the deploy pipeline —
never as something each app replica does on its own startup. N replicas
starting concurrently and each racing to run `alembic upgrade head` against
the same database is a lock contention and race-condition generator: two
replicas can both see "migration not yet applied," both attempt to apply it,
and one fails or — worse — a not-fully-idempotent migration partially applies
twice.

For a **rolling deploy** where old and new code briefly run side by side
against the same database, use the **expand-contract** pattern:

1. **Expand** — deploy a migration that adds the new column/table/constraint
   *additively*, in a way both old and new application code can still work
   against (nullable new column, new table nothing reads yet).
2. **Migrate code** — roll out the new application version; it starts using
   the new schema element. Old code, if still running during rollout, is
   unaffected because step 1 didn't remove anything it needs.
3. **Contract** — once the new code is fully rolled out and no old instances
   remain, a follow-up migration removes what's no longer needed (drop the
   old column, add the `NOT NULL` constraint, drop the old table).

Skipping straight to a destructive change (drop a column the currently-running
old code still reads) is what turns an ordinary rolling deploy into an outage.

## ruff + type checking

```toml
[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = [
    "E", "F", "W",   # pycodestyle errors/warnings, pyflakes — the baseline
    "I",             # isort — import sorting or dependency-order bugs
    "N",             # pep8-naming
    "UP",            # pyupgrade — flags old syntax once a newer, cleaner form exists
    "B",             # flake8-bugbear — real bug patterns (mutable default args, etc.)
    "A",             # flake8-builtins — shadowing `list`, `id`, `type`, ...
    "C4",            # flake8-comprehensions — unnecessary list()/dict() wraps
    "SIM",           # flake8-simplify — needlessly convoluted logic
    "RUF",           # ruff's own rules — a mix of correctness and style
    "ASYNC",         # flake8-async — blocking calls inside async def, missing awaits
    "S",             # flake8-bandit — security: eval, hardcoded passwords, weak hashes
]
```

`ruff format` replaces `black` + `isort` in one pass — one tool, one config
surface, no risk of the two disagreeing on import ordering vs line wrapping.

### Which type checker (2026)

| Checker | Status | Verdict |
|---|---|---|
| **mypy** | **2.3.0** — the reference implementation | **Default choice.** Note 2.x is a major bump from the 1.x line; check the release notes for config changes before upgrading a CI gate. |
| **pyright** | stable, fast, Microsoft | Excellent alternative, especially if the team is in VS Code (Pylance embeds it). |
| **ty** (Astral) | **beta, pre-1.0 (0.0.x)** | **Do not make it your only checker yet.** 10–100× faster than mypy (one benchmark: 4.7 ms vs 386 ms to recheck after an edit on PyTorch), and Astral use it internally — but it's on `0.0.x` with **no stable-API guarantee, so breaking changes can land between point releases**, and it still has typing-spec conformance gaps. Reasonable to run *alongside* mypy in CI for the speed; not a replacement until 1.0. |
| pyrefly | emerging | Sometimes preferred over `ty` for new projects specifically because `ty` is still beta. |

**mypy/pyright strict settings worth adopting incrementally** — turning on
full `strict` mode on a large existing codebase in one commit produces
thousands of errors and gets reverted. Adopt per-flag, and per-module:

```toml
[tool.mypy]
# These four option NAMES are unchanged in mypy 2.x — but 2.0 flipped two DEFAULTS
# that will surface new errors on an existing codebase. See the note below.
disallow_untyped_defs = true     # every function needs a full signature
warn_return_any = true           # returning Any silently defeats type checking downstream
no_implicit_optional = true      # `def f(x: int = None)` must spell out `int | None`
warn_unused_ignores = true       # a `# type: ignore` that's no longer needed is dead weight/a lie

[[tool.mypy.overrides]]
module = "myservice.legacy.*"
disallow_untyped_defs = false    # carve out the untyped legacy corner explicitly...
```

...rather than one repo-wide `ignore_errors = true` or a blanket
`# type: ignore` sprinkled everywhere, which silences real errors in new code
right alongside the legacy debt it was meant to exempt.

### Upgrading to mypy 2.x — two flipped defaults will bite

mypy 2.0 (May 2026) changed defaults rather than renaming options. Expect **new errors on
unchanged code**:

| Change | Effect | Escape hatch |
|---|---|---|
| **`--local-partial-types` now ON by default** | Changes inference for values assigned in another scope. Usually needs small code edits. | `local_partial_types = false` still works, but **support will be removed** — the legacy behaviour is incompatible with the daemon and the new redefinition implementation. Fix the code, don't disable. |
| **`--strict-bytes` now ON by default** | `bytearray`/`memoryview` are no longer silently assignable to `bytes` (matching PEP 688). | Fix the annotations — the old behaviour was a special case that hid real bugs. |
| **`--allow-redefinition` semantics changed** | It now means what `--allow-redefinition-new` used to. | `--allow-redefinition-old` (added in 1.20) preserves the legacy meaning. |

Also removed: assignment of `None` to class variables via type comments; legacy
bundled-stub logic (so `--ignore-missing-imports` is now honoured consistently for all
packages). Fixed-format cache is the new default.

**Experimental parallel checking** — up to ~5× faster with 8 workers, and it implicitly
enables the Ruff-based native parser. There are minor semantic differences from
single-process mode, so **keep strict CI gates on single-process mypy** and use parallel
mode for fast local feedback.

`pre-commit` wires `ruff check --fix`, `ruff format`, and a fast subset of
type checking into every commit, catching issues before they reach CI.
`pip-audit` (or `uv`'s own `uv pip audit` equivalent tooling) scans the
resolved dependency tree against known vulnerability databases — run it in CI
on a schedule, not just at dependency-bump time, since new CVEs get
disclosed against versions you already shipped.

## Checklist

- [ ] `uv.lock` committed; `uv sync --frozen` used in CI and Docker builds
- [ ] `pyproject.toml` uses PEP 621 `[project]` + PEP 735 `dependency-groups`
- [ ] src-layout, not flat layout
- [ ] `Settings()` instantiated at import time; invalid config fails at startup
- [ ] Secrets are `SecretStr`, never logged, never baked into the image
- [ ] Dockerfile installs dependencies before copying source (cache ordering)
- [ ] `python:slim` base, not alpine, unless the musl trade-off was deliberate
- [ ] Non-root user; `PYTHONUNBUFFERED=1`; `PYTHONDONTWRITEBYTECODE=1`; `.dockerignore` in place
- [ ] Correct worker class (`uvicorn_worker.UvicornWorker`, not the deprecated `uvicorn.workers`)
- [ ] Worker count derived from a formula, then load-tested
- [ ] `--preload` + `gc.freeze()` used if squeezing memory via copy-on-write
- [ ] Graceful shutdown: readiness fails first, then delay, then drain, then close pools
- [ ] `terminationGracePeriodSeconds` exceeds the full shutdown budget
- [ ] Migrations run as a separate step, never from N replicas' startup; expand-contract for rolling deploys
- [ ] ruff configured with a real rule selection, not just defaults
- [ ] mypy/pyright strict flags adopted incrementally with explicit per-module overrides
- [ ] pre-commit and pip-audit wired into the workflow
