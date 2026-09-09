# Source Connectors

How to pull each kind of source. One system usually yields several sources — an ADO
project alone gives wiki pages, a work item tree, comments, revisions and attachments.

Pick connectors by where the sources actually live; a run may use one, or all of them.

**Read every source completely.** A summary of a summary loses the acceptance criteria,
which is the only part that matters. If a document is too large for one read, read it in
sections and keep notes per section — never skim.

---

## Azure DevOps

The most common single system to hold *both* docs and tickets. Three sub-connectors:
Wiki (docs), Boards (tickets), Test Plans (existing coverage).

Access, in order of preference:
1. **Official MCP server** — `microsoft/azure-devops-mcp`, tools below
2. **`az` CLI** — `az devops` / `az boards`, needs `az extension add --name azure-devops`
3. **REST API** — `https://dev.azure.com/{org}/{project}/_apis/...?api-version=7.1`

### Boards — work items

MCP tools: `wit_query` (`wiql` for ad-hoc, `get_results` for saved), `wit_work_item`
(`get`, `get_batch`, `list_comments`, `list_revisions`, `list_for_iteration`),
`wit_backlog` (`list`, `list_work_items`), `search_workitem`.

**Enumerate a whole tree in one query** — this is the query that matters, because
requirements hide in the leaves:

```sql
-- every descendant of an epic, at any depth
SELECT [System.Id], [System.WorkItemType], [System.Title], [System.State]
FROM WorkItemLinks
WHERE [Source].[System.Id] = 4412
  AND [System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward'
MODE (Recursive)
```

```sql
-- everything under an area path, any type, excluding closed
SELECT [System.Id], [System.WorkItemType], [System.Title]
FROM WorkItems
WHERE [System.TeamProject] = '{project}'
  AND [System.AreaPath] UNDER '{project}\{area}'
  AND [System.State] <> 'Removed'
ORDER BY [System.WorkItemType]
```

```sql
-- by tag, when the feature is tracked with one
SELECT [System.Id], [System.Title] FROM WorkItems
WHERE [System.Tags] CONTAINS '{feature-tag}'
```

Then batch-fetch the details. **Always request the fields that hold requirements** —
the default field set omits them:

```
System.Title, System.Description, System.State, System.WorkItemType,
Microsoft.VSTS.Common.AcceptanceCriteria,   ← the one people forget
Microsoft.VSTS.Common.Priority, System.Tags, System.AreaPath, System.IterationPath,
System.Parent, System.History
```

`az` CLI equivalents:
```bash
az boards query --wiql "SELECT [System.Id] FROM WorkItems WHERE [System.Tags] CONTAINS '{tag}'" \
  --org https://dev.azure.com/{org} -p {project} -o json
az boards work-item show --id {id} --org https://dev.azure.com/{org} --expand all -o json
# relations (children, related, attachments) come back under .relations with --expand all
```

REST, when neither is available:
```bash
# batch get with explicit fields
curl -sS -u ":$ADO_PAT" -H 'Content-Type: application/json' \
  "https://dev.azure.com/{org}/{project}/_apis/wit/workitemsbatch?api-version=7.1" \
  -d '{"ids":[4412,4418],"fields":["System.Title","System.Description","Microsoft.VSTS.Common.AcceptanceCriteria"]}'
# comments — a separate call, and often the richest source
curl -sS -u ":$ADO_PAT" \
  "https://dev.azure.com/{org}/{project}/_apis/wit/workItems/{id}/comments?api-version=7.1-preview.4"
# revisions — what changed and when
curl -sS -u ":$ADO_PAT" \
  "https://dev.azure.com/{org}/{project}/_apis/wit/workItems/{id}/revisions?api-version=7.1"
```

**Field content is HTML**, not markdown. Strip tags before extracting, and keep list
structure — acceptance criteria are almost always `<ul>` items, and flattening them
merges separate requirements into one.

**Always pull comments and revisions**, not just the item. Comments hold decisions that
never made it back into the description; revisions expose scope that changed silently.

### Wiki — docs

MCP: `wiki` (`list_wikis`, `list_pages`, `get_page_content`).

```bash
az devops wiki list --org https://dev.azure.com/{org} -p {project} -o table
az devops wiki page show --wiki {wiki} --path '/specs/checkout' \
  --org https://dev.azure.com/{org} -p {project} --include-content -o json
# child pages — the PRD is often split across a page tree
curl -sS -u ":$ADO_PAT" \
  "https://dev.azure.com/{org}/{project}/_apis/wiki/wikis/{wiki}/pages?path=/specs&recursionLevel=full&includeContent=true&api-version=7.1"
```

Read the page **and its children**. A PRD split into `/specs/checkout/{overview,rules,errors}`
loses two thirds of itself if you read only the parent.

### Attachments

Requirements frequently live in a spreadsheet attached to a ticket.
```bash
# relations with rel = AttachedFile carry a url + attributes.name
az boards work-item show --id {id} --expand all -o json \
  | jq -r '.relations[]? | select(.rel=="AttachedFile") | [.attributes.name, .url] | @tsv'
curl -sS -u ":$ADO_PAT" -o /tmp/spec.xlsx "{attachment_url}"
```
Then read it with the file recipes below.

### Test Plans — existing coverage

MCP: `testplan` (`list_plans`, `list_suites`, `list_cases`). Worth pulling: it shows what
QA already believes the requirements are, and the delta against your digest is itself a
finding.

### Auth

```bash
export ADO_PAT={{pat}}          # REST uses basic auth with an empty username
az devops login --org https://dev.azure.com/{org}   # reads AZURE_DEVOPS_EXT_PAT
az devops configure --defaults organization=https://dev.azure.com/{org} project={project}
```

---

## Local files

Loose documents on disk are a first-class source — often *the* source for a BRD.

### Discover
```bash
# don't guess at names; list everything and judge by content
find {dir} -maxdepth 3 -type f \( -name '*.md' -o -name '*.docx' -o -name '*.pdf' \
  -o -name '*.xlsx' -o -name '*.csv' -o -name '*.txt' \) -not -path '*/node_modules/*' \
  -exec ls -la {} \;
```

### `.md` / `.txt`
Read directly. Keep heading structure — section paths become the source refs
(`S1 §3.2`), which is what makes traceability checkable.

### `.docx`
Not readable by `cat`. In order of preference:
```bash
pandoc -f docx -t markdown --wrap=none "{file}.docx" -o /tmp/src.md     # best: keeps tables + lists
```
```bash
# no pandoc — python-docx keeps paragraphs and tables
python3 - "$F" <<'PY'
import sys, docx                      # pip install python-docx
d = docx.Document(sys.argv[1])
for p in d.paragraphs:
    if p.text.strip(): print(f"[{p.style.name}] {p.text}")
for i, t in enumerate(d.tables):
    print(f"\n--- table {i} ---")
    for r in t.rows: print(" | ".join(c.text.strip() for c in r.cells))
PY
```
```bash
# last resort — raw XML text, loses all structure, use only to confirm content exists
unzip -p "{file}.docx" word/document.xml | sed -e 's/<[^>]*>/ /g' | tr -s ' '
```
**Tables and numbered lists in a BRD are usually the business rules.** A conversion that
drops them has dropped the requirements — check the output for tables before trusting it.
Also check for tracked changes and comments (`word/comments.xml`), which often hold the
disputed points:
```bash
unzip -p "{file}.docx" word/comments.xml | sed -e 's/<[^>]*>/ /g' | tr -s ' '
```

### `.pdf`
Use the Read tool with a `pages` range — it handles PDFs natively and preserves layout
better than text extraction. For bulk text:
```bash
pdftotext -layout "{file}.pdf" -           # -layout is essential for tables
```

### `.xlsx` / `.csv`
Rule matrices and decision tables live here, and each row is usually one requirement.
```bash
python3 - "$F" <<'PY'
import sys, openpyxl                   # pip install openpyxl
wb = openpyxl.load_workbook(sys.argv[1], data_only=True)   # data_only: values, not formulas
for ws in wb:
    print(f"\n=== sheet: {ws.title} ({ws.max_row}x{ws.max_column}) ===")
    for row in ws.iter_rows(values_only=True):
        if any(c is not None for c in row):
            print(" | ".join("" if c is None else str(c) for c in row))
PY
```
Read **every sheet** — the rules are rarely on the first one.

### Images / mocks
Read the file with the Read tool; it renders images. Mocks carry the states the prose
omits: empty, loading, error, truncation, long strings.

---

## Confluence and Jira

Use the `atlassian` skill — it documents the `mcp__atlassian__` tool family. What matters
here:

```
confluence_search   → find the PRD/BRD by title or CQL
confluence_get_page → full body; then fetch child pages too
jira_search         → JQL for the ticket tree
jira_get_issue      → fields="*all" to include description, acceptance criteria, comments
```

Tree enumeration:
```
JQL: "Epic Link" = PROJ-123 OR parent = PROJ-123 ORDER BY issuetype
JQL: project = PROJ AND labels = {feature} AND status != Closed
```
Fetch with `fields="*all"` — the default field set omits custom acceptance-criteria
fields, which is where the requirements are.

---

## Notion

`mcp__claude_ai_Notion__notion-search` then `notion-fetch` for full page content.
Notion PRDs nest heavily — fetch child pages and inline databases, not just the parent.
A requirements database's rows are individual requirements; read its properties, not the
rendered view.

---

## Google Docs / Drive

`mcp__claude_ai_Google_Drive__search_files`, then `read_file_content` (Docs and Sheets
export as text). Comments on a Google Doc frequently hold the unresolved decisions —
if the connector cannot read them, say so and flag it as an unread source rather than
implying the doc was fully digested.

---

## GitHub

Issues, and markdown specs living in the repo:
```bash
gh issue list --repo {org}/{repo} --label {feature} --state all --limit 100 \
  --json number,title,body,labels,state
gh issue view {n} --repo {org}/{repo} --comments --json title,body,comments
# specs in-repo
rg -l -i '{feature}' --glob '*.md' docs/
```

---

## URLs

`WebFetch` with a specific extraction prompt. Never digest a URL you could not actually
read — a fetch failure makes it an unread source, and it belongs in "expected but not
found", not silently omitted.

---

## Recording what you read

Every source gets a stable `S{n}` and a version marker, because `refresh` compares
against it:

| Field | Example |
|---|---|
| id | `S2` |
| kind | PRD |
| ref | `ADO Wiki /specs/checkout` |
| locator | page id 118, rev 18 |
| version | rev 18, updated 2026-08-02 |
| authority | high |
| read | full / partial (say which sections) / failed |

A source marked `partial` or `failed` **must** appear in the digest's "Not Covered"
section. Never let an unread source look digested.
