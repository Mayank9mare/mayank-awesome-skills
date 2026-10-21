# mayank-awesome-skills

A handpicked collection of generic [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) — practical, reusable, and not tied to any one company or codebase.

## Using a skill

Copy (or symlink) any skill folder into `~/.claude/skills/` to make it available globally, or drop it into a project's `.claude/skills/` to scope it to that project.

```bash
ln -s "$(pwd)/tdd" ~/.claude/skills/tdd
```

Some skills need one-time setup before first use — check the top of the `SKILL.md` for a "before first use" note and fill in the placeholders (`{{like-this}}`) for your environment (site URLs, tool names, project keys, etc.).

## Skills

### Engineering stack skills

Deep, opinionated reference skills for building/reviewing services and apps in a given stack — each ships with a `references/` directory (framework choice, persistence, caching, messaging, observability, testing, packaging) and a `templates/` starter file.

| Skill | What it does |
|---|---|
| [ai-agents](ai-agents/SKILL.md) | Building/reviewing LLM agents and tool-calling loops — architecture choice, tracing, evaluation, safety guardrails, RAG retrieval, prompting. |
| [flutter-app](flutter-app/SKILL.md) | Building/reviewing a Flutter/Dart mobile app — state management, navigation, networking, platform integration, release engineering. |
| [go-microservice](go-microservice/SKILL.md) | Building/reviewing a Go backend service — routers, persistence, caching, messaging, observability, container tuning. |
| [java-microservice](java-microservice/SKILL.md) | Building/reviewing a Java/JVM backend service — framework choice, Spring Boot, persistence, virtual threads, JVM container tuning. |
| [node-microservice](node-microservice/SKILL.md) | Building/reviewing a Node.js/TypeScript backend service — framework choice, persistence, queues, observability, graceful shutdown. |
| [python-microservice](python-microservice/SKILL.md) | Building/reviewing a Python backend service or MCP server — framework choice, async patterns, persistence, packaging with uv. |
| [web-frontend](web-frontend/SKILL.md) | Building/reviewing a React/TypeScript web frontend — rendering strategy, server vs client state, performance, accessibility. |

### General skills

| Skill | What it does |
|---|---|
| [atlassian](atlassian/SKILL.md) | Reference for the `mcp__atlassian__` tool family — Jira issues and Confluence pages. |
| [autoresearch](autoresearch/SKILL.md) | Karpathy-style autoresearch on any repo + metric: the agent edits a fixed scope, runs a frozen benchmark, and keeps commits only when they beat measured noise. Includes a scope guard, correctness gate, held-out checks, and a morning report (`ratchet.py`). |
| [design-an-interface](design-an-interface/SKILL.md) | Generate multiple radically different interface designs for a module via parallel sub-agents, then compare. |
| [firebase-crashlytics-analyzer](firebase-crashlytics-analyzer/SKILL.md) | Analyze Firebase Crashlytics crashes, ANRs, and events for Android/iOS apps. |
| [grill-me](grill-me/SKILL.md) | Interview the user relentlessly about a plan or design until reaching shared understanding. |
| [hyperthymesia](hyperthymesia/SKILL.md) | Memory coach for anyone: Derren Brown's *Tricks of the Mind* system (linking, memory palaces, pegs, his number code, cards, names), Jane-style observation, Ross-style document recall, daily recall, scored drills (`memgym.py`), and a personal vault with spaced review. Companion: **[Memory Palace Workbook](https://mayank9mare.github.io/mayank-awesome-skills/hyperthymesia/)**, an illustrated, interactive course anyone can open. |
| [implement-feature](implement-feature/SKILL.md) | Execute a large feature implementation from a spec: phased steps, test gates, design-change handling, progress tracking — while keeping living `decision.md`, `flow.md` (with Mermaid/Excalidraw diagrams), `review.md` and `bugs.md` docs in sync with the code. |
| [improve-codebase-architecture](improve-codebase-architecture/SKILL.md) | Find deepening opportunities in a codebase — turn shallow modules into deep, testable ones. |
| [jenkins](jenkins/SKILL.md) | Interact with Jenkins CI/CD via REST API — jobs, builds, logs, queue. |
| [kb](kb/SKILL.md) | Personal work knowledgebase for team context, people, projects, and reply drafting. |
| [learn-anything](learn-anything/SKILL.md) | Tutor to understand *and* remember anything — physics, maths, a repo's architecture, design patterns — via Socratic questioning, explicit mental models, Derren Brown's memory system (via hyperthymesia), and spaced retrieval with a persistent learning log. |
| [memory-expert](memory-expert/SKILL.md) | Search and store durable memory (preferences, solutions, context) across conversations. |
| [qa](qa/SKILL.md) | Stack-agnostic E2E QA automation — derives and runs the full scenario set for a feature (happy path, negatives, authz, idempotency, races, timeouts, failure injection, lifecycle, data edges) against a real environment. Workflow engine, event bus, datastore and log platform are per-feature task-file adapters. |
| [requirements-digest](requirements-digest/SKILL.md) | Digest scattered requirements — ADO wiki + work item trees, PRD/BRD `.docx`/`.md` files, Confluence, Notion — into one requirements.md with EARS-formatted requirements, surfaced conflicts, derived test cases, and full traceability. Emits a `qa` task file. |
| [remotion](remotion/SKILL.md) | Domain knowledge for building programmatic videos with React + Remotion. |
| [sandbox-context](sandbox-context/SKILL.md) | Daytona sandbox lifecycle management across agent sessions. |
| [slack-auto-responder](slack-auto-responder/SKILL.md) | Set up a recurring auto-responder for Slack DMs using knowledgebase context. |
| [tdd](tdd/SKILL.md) | Test-driven development via red-green-refactor, with vertical-slice tracer bullets. |
| [tech-design-doc](tech-design-doc/SKILL.md) | End-to-end workflow for writing and publishing a technical design doc to Confluence, with diagrams and review cycles. |
| [to-prd](to-prd/SKILL.md) | Turn the current conversation into a PRD and submit it as a GitHub issue. |
| [troubleshooter](troubleshooter/SKILL.md) | Systematic investigation methodology for bugs, incidents, and infrastructure issues. |
| [ubiquitous-language](ubiquitous-language/SKILL.md) | Extract a DDD-style ubiquitous language glossary from the current conversation. |

## Provenance

These skills were curated and genericized from a larger personal collection — company-specific tooling, internal service names, and proprietary CI/CD platforms were stripped out or excluded so each skill stands on its own outside any particular org.
