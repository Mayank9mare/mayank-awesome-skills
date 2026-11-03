# Wensity tools: MCP and CLI

Facts from ui.wensity.com/docs (checked 2026-11-04). If a tool behaves differently, trust the tool's
own output and the live docs over this file.

## Requirements
Node.js 20+, React 18.2+, TypeScript 5+, Tailwind CSS **v4**. Works with Next.js, Vite, Remix /
React Router and Astro.

**Tailwind v3 project:** Wensity targets v4 (`@theme`, CSS-first config). Don't upgrade Tailwind on
the side. Tell the user and offer three options: (a) upgrade to v4 as its own change first, (b) use
only the items that work after a manual port, or (c) build custom.

## Setup
MCP for Claude Code, run from the project root. It writes `.mcp.json` with the version pinned:

```bash
claude mcp add --transport stdio --scope project wensity -- npx -y @wensity/mcp@0.1.2
```

Drop `--scope project` to add it for this user only. Claude Code asks for approval the first time
and has to restart to pick it up. Check it with `/mcp` or `claude mcp list`.

Pro access: the **user** runs `npx wensity login` in their own terminal (`! npx wensity login`).
Never ask for a token, accept one in chat, or write one to a file.

## MCP tools

| Tool | Does | Writes? |
|---|---|---|
| `wensity_search` | Find components, primitives or blocks by need, name, category, tag, tier or npm dependency. Labels results Free / Pro / Needs Pro | no |
| `wensity_get_item` | One item's description, props, npm deps, install command and links (no source) | no |
| `wensity_auth_status` | Whether a credential is saved and what it unlocks | no |
| `wensity_inspect_project` | Framework, package manager, aliases, Tailwind file (no file contents) | no |
| `wensity_plan_install` | Every file, Tailwind token change, package command and conflict an install would cause, plus a plan token | no |
| `wensity_install` | Runs one approved plan by its token, then the planned package command | **yes** |

## Agent rules
- Always `wensity_plan_install` → show the plan → wait for approval → `wensity_install`.
- `wensity_install` is the only write tool.
- Use each plan token once. Plans expire after 10 minutes. A repeat call returns the first result
  with `replayed: true`.
- "Stale plan" means the project changed: re-plan. Nothing was written.
- For a Needs Pro item, say so before planning and suggest a free alternative.
- Read source only after install (`get_item` returns none).
- `package.json`, the lockfile and lifecycle scripts **aren't rolled back** on failure. Show the
  exact package command in the plan.
- The install doesn't format, lint or type-check. Run those yourself (Step 5).
- Keep the MCP version pinned. For an update, change only the version in `.mcp.json` and restart.
- "Recovery required": follow its steps, check `git diff`, and don't delete `.wensity-tmp` until the
  user has verified their files. Never commit `.wensity-tmp/`.

## CLI (fallback, or for scripting)

| Command | Use |
|---|---|
| `npx wensity@latest init` | Writes `wensity.json` (commit it) and a `cn()` helper; installs `clsx` + `tailwind-merge`. `--template next\|vite\|astro\|react-router`, `--dry-run`, `--no-install`, `--force` |
| `npx wensity@latest list [--type component\|block] [--json]` | The catalogue grouped by access (there's no CLI search; filter the `--json` output) |
| `npx wensity@latest add <slug...> [--type block] [--dry-run]` | Install items. **Always `--dry-run` first** and show the result, mirroring plan-then-install |
| `npx wensity@latest update <slug...> [--dry-run]` | Re-download and overwrite. It loses local restyling, so diff first |
| `npx wensity login` / `whoami` / `logout` | Pro credential (the user runs these) |

Free items also install through shadcn: `npx shadcn@latest add @wensity/<slug>`. Use this only if
the project already uses shadcn and has no `wensity.json`; don't mix both setups without a reason.

Default install paths: `@/components/wensity` for components and `@/lib/utils` for `cn()`. If the
project keeps components somewhere else, set the aliases in `wensity.json` instead of moving files
afterwards.
