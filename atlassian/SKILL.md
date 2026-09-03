---
name: atlassian
description: Use when interacting with Jira issues (create, search, update, transition, link, comment, sprint management) or Confluence pages (create, search, read, update, page trees, comments, attachments). Covers the mcp__atlassian__ tool family for both Jira and Confluence on your Atlassian site.
---

# Atlassian Skill (Jira + Confluence)

Reference guide for using `mcp__atlassian__` MCP tools to interact with Jira and Confluence on your Atlassian site.

**Before first use**, fill in the Site Configuration section at the bottom of this file with your Atlassian site name, default project key, and env var names — the examples throughout use placeholder values (`PROJ`, `your-site`).

## Quick Reference: Common Operations

| Task | Tool | Key Params |
|------|------|------------|
| Get issue details | `jira_get_issue` | `issue_key`, `fields` ("*all" for everything) |
| Search issues (JQL) | `jira_search` | `jql`, `fields`, `limit` |
| Create issue | `jira_create_issue` | `project_key`, `summary`, `issue_type` |
| Update issue fields | `jira_update_issue` | `issue_key`, `fields` (dict) |
| Transition status | `jira_transition_issue` | `issue_key`, `transition_id` (get from `jira_get_transitions`) |
| Add comment | `jira_add_comment` | `issue_key`, `comment` (markdown) |
| Read Confluence page | `confluence_get_page` | `page_id` or `title`+`space_key` |
| Search Confluence | `confluence_search` | `query` (exact title match) |
| Create page | `confluence_create_page` | `space_key`, `title`, `content` (markdown) |
| Update page | `confluence_update_page` | `page_id`, `title`, `content` |

---

## Jira

### Searching Issues

Use JQL (Jira Query Language) with `jira_search`:

```
# Issues assigned to current user
assignee = currentUser() AND status != Done

# Recent bugs in a project
project = PROJ AND issuetype = Bug AND created >= -7d

# Sprint issues
sprint in openSprints() AND project = PROJ

# Text search
summary ~ "checkout" OR description ~ "checkout"

# Combined filters
project = PROJ AND status = "In Progress" AND priority = High ORDER BY updated DESC
```

Default fields: `summary,status,assignee,priority`. Use `fields: "*all"` for full details including description, comments, links.

### Creating Issues

Required: `project_key`, `summary`, `issue_type` (Task, Bug, Story, Epic, Subtask).

Optional: `description`, `assignee`, `components`, `dev_assignee`, `pm_assignee`, `design_assignee`, `additional_fields`.

Custom assignee fields (`dev_assignee`, `pm_assignee`, `design_assignee`) accept email, name, or account ID.

### Updating Issues

Pass a `fields` dict to `jira_update_issue`:
```json
{"summary": "New title", "priority": {"name": "High"}, "labels": ["backend", "urgent"]}
```

For custom fields, use `additional_fields` or find field IDs with `jira_get_custom_field_ids`.

### Transitions (Status Changes)

Always get available transitions first:
1. `jira_get_transitions` with `issue_key` -- returns available transition IDs
2. `jira_transition_issue` with `issue_key` and `transition_id`

Never hardcode transition IDs -- they vary by project workflow.

### Issue Links

- `jira_create_issue_link` -- link two issues (Blocks, Duplicate, Relates to)
- `jira_link_to_epic` -- add issue to epic
- `jira_get_link_types` -- discover available link types

### Sprint Management

1. `jira_get_agile_boards` -- find board ID (filter by `project_key` or `board_name`)
2. `jira_get_sprints_from_board` -- list sprints (filter by `state`: active/future/closed)
3. `jira_get_sprint_issues` -- get issues in a sprint
4. `jira_move_issues_to_sprint` -- move issues to a sprint
5. `jira_create_sprint` / `jira_update_sprint` -- manage sprints

### Bulk Operations

- `jira_batch_create_issues` -- create multiple issues at once (JSON array of issue objects)
- `jira_batch_get_changelogs` -- get change history for multiple issues

### Other Jira Tools

| Tool | Purpose |
|------|---------|
| `jira_get_comments` | Get issue comments (pagination with `start_at`, `limit`) |
| `jira_add_comment` / `jira_update_comment` / `jira_delete_comment` | Manage comments |
| `jira_get_project_issues` | All issues in a project |
| `jira_get_all_projects` | List accessible projects |
| `jira_get_issue_types` | Valid issue types for a project |
| `jira_get_statuses` | Available statuses (optionally by project) |
| `jira_get_priorities` | Available priorities |
| `jira_get_project_components` | Project components |
| `jira_get_project_versions` | Fix versions |
| `jira_assign_issue` | Assign/unassign (null to unassign) |
| `jira_add_worklog` / `jira_get_worklog` | Time tracking |
| `jira_add_attachment` / `jira_download_attachments` | File attachments (base64) |
| `jira_get_watchers` / `jira_add_watcher` | Manage watchers |
| `jira_search_fields` | Find custom field IDs by keyword |
| `jira_get_user_profile` | Look up user by email/name/ID |
| `jira_get_remote_issue_links` | External links on an issue |

---

## Confluence

### Reading Pages

Two lookup methods:
1. **By page_id** (preferred): `confluence_get_page` with `page_id`
2. **By title + space**: `confluence_get_page` with `title` and `space_key`

Returns markdown by default. Set `convert_to_markdown: false` for raw HTML.

### Searching Pages

`confluence_search` does exact title matching. Use `spaces_filter` (comma-separated space IDs) to narrow results.

To discover spaces: `confluence_get_spaces`.

### Page Hierarchy

| Tool | Purpose |
|------|---------|
| `confluence_get_page_children` | Direct children of a page |
| `confluence_get_page_tree` | Full descendant tree (recursive, max depth 10) |
| `confluence_get_page_ancestors` | Parent pages going up |

### Creating & Updating Pages

- `confluence_create_page`: requires `space_key`, `title`, `content`. Content format defaults to markdown. Optional `parent_id`.
- `confluence_update_page`: requires `page_id`, `title`, `content`. Optional `version_comment`, `parent_id`.

### Attachments & Images

1. `confluence_get_page_attachments` -- list attachments on a page
2. `confluence_download_image` -- download attachment content (base64 for binary, text for text)
3. `confluence_upload_attachment` -- upload file (base64 content)
4. `confluence_delete_attachment` -- remove attachment

### Other Confluence Tools

| Tool | Purpose |
|------|---------|
| `confluence_get_comments` / `confluence_add_comment` / `confluence_delete_comment` | Page comments |
| `confluence_get_labels` / `confluence_add_label` / `confluence_remove_label` | Page labels |
| `confluence_get_watchers` / `confluence_add_watcher` / `confluence_remove_watcher` | Page watchers |
| `confluence_get_page_history` | Version history (who edited when) |
| `confluence_get_content_restrictions` | Read/update permissions |
| `confluence_search_user` | Find users by name or email |

---

## Common Patterns

### Find and update an issue
```
1. jira_search(jql="key = PROJ-123", fields="*all")
2. jira_get_transitions(issue_key="PROJ-123")
3. jira_transition_issue(issue_key="PROJ-123", transition_id="31")
4. jira_add_comment(issue_key="PROJ-123", comment="Done - deployed to staging")
```

### Create issue with epic link
```
1. jira_create_issue(project_key="PROJ", summary="...", issue_type="Task")
2. jira_link_to_epic(issue_key="PROJ-NEW", epic_key="PROJ-100")
```

### Document a decision in Confluence
```
1. confluence_get_spaces()  -- find target space
2. confluence_search(query="Architecture Decisions", spaces_filter="...")
3. confluence_create_page(space_key="ENG", title="ADR-042: ...", content="...", parent_id="12345")
```

### Look up user then assign
```
1. jira_search_user(query="your-name") or jira_get_user_profile(user_identifier="you@example.com")
2. jira_assign_issue(issue_key="PROJ-123", account_id="...")
```

## Site Configuration

Fill these in for your organization:

- **Site**: `{{your-site}}` (`https://{{your-site}}.atlassian.net`)
- **User**: `{{you@example.com}}`
- **Default project key**: `{{PROJ}}` — replace `PROJ` in the examples above with your project's key
- **Env vars** (in `~/.zshrc`): `$ATLASSIAN_SITE_URL`, `$ATLASSIAN_USER_EMAIL`, `$ATLASSIAN_API_TOKEN`
- **Default site param**: `{{your-site}}` (all tools default to this)

Use `list_atlassian_sites` to see other available sites if needed.

## REST API via curl (Fallback)

When MCP tools are unavailable or fail to connect, use the Jira/Confluence REST API directly via curl. Auth uses env vars from `~/.zshrc`.

**Auth pattern**: `source ~/.zshrc 2>/dev/null; curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN"`

### Jira REST API (v3)

Base: `$ATLASSIAN_SITE_URL/rest/api/3`

```bash
# Get issue
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123?fields=summary,status,assignee,priority,description"

# Search with JQL
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/rest/api/3/search?jql=project%3DPROJ%20AND%20status%3D%22In%20Progress%22&maxResults=20&fields=summary,status,assignee"

# Create issue
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  -X POST -H "Content-Type: application/json" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue" \
  -d '{"fields":{"project":{"key":"PROJ"},"summary":"Title","issuetype":{"name":"Task"}}}'

# Update issue fields
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  -X PUT -H "Content-Type: application/json" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123" \
  -d '{"fields":{"summary":"Updated title","priority":{"name":"High"}}}'

# Get transitions
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123/transitions"

# Transition issue
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  -X POST -H "Content-Type: application/json" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123/transitions" \
  -d '{"transition":{"id":"31"}}'

# Add comment
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  -X POST -H "Content-Type: application/json" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123/comment" \
  -d '{"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"Comment text"}]}]}}'

# Assign issue
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  -X PUT -H "Content-Type: application/json" \
  "$ATLASSIAN_SITE_URL/rest/api/3/issue/PROJ-123/assignee" \
  -d '{"accountId":"ACCOUNT_ID"}'

# List projects
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/rest/api/3/project"
```

### Confluence REST API (v2)

Base: `$ATLASSIAN_SITE_URL/wiki/api/v2`

```bash
# Get page by ID
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/wiki/api/v2/pages/PAGE_ID?body-format=storage"

# Search pages by title
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/wiki/api/v2/pages?title=Page%20Title&space-id=SPACE_ID"

# List spaces
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/wiki/api/v2/spaces"

# Get child pages
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/wiki/api/v2/pages/PAGE_ID/children"

# CQL search (legacy v1 - more powerful)
curl -s -u "$ATLASSIAN_USER_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_SITE_URL/wiki/rest/api/content/search?cql=space%3DENG%20AND%20type%3Dpage%20AND%20title~%22search%20term%22"
```

### Parsing Jira responses

Jira v3 uses ADF (Atlassian Document Format) for description/comments. Extract text with:
```bash
| python3 -c "
import json, sys
def extract_text(node):
    if isinstance(node, dict):
        t = node.get('text','')
        for c in node.get('content',[]):
            t += extract_text(c)
        return t
    return ''
d = json.load(sys.stdin)
f = d['fields']
print(f'Key: {d[\"key\"]}')
print(f'Summary: {f[\"summary\"]}')
print(f'Status: {f[\"status\"][\"name\"]}')
print(f'Description: {extract_text(f.get(\"description\",{}))}')
"
```

### When to use curl vs MCP tools

- **MCP tools available and connected**: prefer MCP (cleaner, structured responses)
- **MCP auth failed or server not connected**: use curl with env vars
- **Bulk/complex queries**: curl gives more control over pagination, fields, expand
- **Always** `source ~/.zshrc 2>/dev/null` before curl to load env vars

## Common Mistakes

- **Hardcoding transition IDs** -- always call `jira_get_transitions` first; IDs differ per workflow
- **Using `fields: "*all"` on search** -- returns too much data; specify only needed fields for search, use `*all` only on `jira_get_issue`
- **Forgetting pagination** -- most list tools have `limit` (default 10-25) and `start_at`; check if results are truncated
- **Confluence search is exact title** -- not fuzzy; use `confluence_get_page_children` to browse hierarchies instead
