# {{feature}} — QA Task File

Copy to `tasks/{{feature}}.md` and fill in. Delete sections that do not apply, but say
*why* in a line rather than leaving them empty — an absent section reads as a gap.

## Feature Model

Fill this in first; the scenario list is derived from it (see
`references/scenario-catalog.md`).

- **Entry points:** {{every way the feature can start — api, event, cron, retry, admin}}
- **External effects:** {{everything that outlives the request — rows, files, messages, money, notifications, partner calls}}
- **Wait points:** {{everywhere it pauses for something it does not control}}
- **States:** {{legal states and transitions}}
- **Concurrency surface:** {{what two actors can touch at once}}

## Environment

One block per environment. `tier` gates destructive behaviour — see SKILL.md.

### stage
```
tier:            stage
base_url:        {{https://...}}
region/project:  {{...}}
test_tenant:     {{...}}
test_user:       {{...}}
```

### prod
```
tier:            prod          # read-only by default
base_url:        {{https://...}}
```

## Adapters

| Probe | Type | Config |
|---|---|---|
| health | {{http-endpoint}} | url={{...}} |
| api | {{http}} | base_url={{...}}, auth_cmd={{...}} |
| workflow | {{temporal\|sfn\|airflow\|camunda\|argo\|none}} | {{...}} |
| queue | {{pubsub\|sqs\|kafka\|rabbitmq\|none}} | {{...}} |
| store | {{postgres\|mysql\|dynamodb\|firestore\|mongodb}} | {{...}} |
| object | {{gcs\|s3\|azure-blob\|none}} | {{...}} |
| logs | {{loki\|cloudwatch\|gcp-logging\|elasticsearch\|datadog}} | {{...}} |
| metric | {{prometheus\|none}} | {{...}} |
| ci | {{github-actions\|jenkins\|argocd\|none}} | {{...}} |

Commands for each type: `references/adapters.md`.

## Credentials

Commands only — never values.

```
api_token:    {{command that prints a token}}
db_password:  {{command that prints the password}}
cloud_refresh:{{command to re-auth when the token expires}}
```

## Deploy

Optional. Order, job names, health-check wait, any manual step (e.g. a workflow
definition that is not deployed with the code).

## Preflight

Feature-specific checks beyond adapter reachability.

1. {{config/flag seeded}}
2. {{test tenant exists}}
3. {{downstream dependency healthy}}

## Fixtures

| Name | Creates | Teardown |
|---|---|---|
| {{order-awaiting-capture}} | {{...}} | {{scoped by RUN_ID}} |

## Invariants

Checked after **every** step of **every** scenario. This is where race bugs get caught.

| Name | Assertion |
|---|---|
| {{exactly-one-capture}} | `store.count({{table}}, {{filter}}) == 1` |
| {{status-never-regresses}} | {{...}} |
| {{dlq-empty}} | `queue.dlq == 0` |
| {{no-orphan-workflow}} | no execution left RUNNING after a terminal state |

## Scenarios

Group by class. Every scenario declares its class, and races declare a repeat count.

### happy/{{name}}
Class: 1 · Setup: {{fixture}}

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | {{...}} | `{{template-name}}` | {{poll api 15s}} | {{...}} |

### negative/{{name}}
Class: 2 — assert `absent`: no row, no message, no workflow started.

### authz/{{name}}
Class: 3 — needs two tenant fixtures.

### idempotency/{{name}}
Class: 4 · Repeat: 3

### races/{{name}}
Class: 5 · Repeat: 10 — see `references/race-conditions.md`

### timeouts/{{name}}
Class: 6

### failure/{{name}}
Class: 7 · Blast radius: {{what may be degraded, and nothing else}}

### lifecycle/{{name}}
Class: 8

### data-edges/{{name}}
Class: 9

## Action Templates

Named, parameterised commands. Referenced by name from step tables.

### {{create-entity}}
```bash
curl -sS -w '\n%{http_code}' --connect-timeout 10 --max-time 30 \
  -X POST "$BASE_URL/{{path}}" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $RUN_ID" \
  -d '{"ref":"'"$RUN_ID"'","{{field}}":"{{value}}"}'
```
Extract: `ENTITY_ID=$(jq -r '.id')`

### {{inject-callback}}
```bash
{{publish command from references/adapters.md for the declared queue type}}
```

### `burst:[a,b]`
Concurrent release of two templates — see the barrier pattern in
`references/race-conditions.md`.

## Expected States

| Step | api | workflow | store | logs |
|---|---|---|---|---|
| {{1}} | {{status=CREATED}} | {{state=AwaitingX}} | {{1 row, status=new}} | {{"created entity"}} |

## Cleanup

Permission-gated. Scope every predicate by `RUN_ID` so teardown cannot over-delete.

```sql
-- DRY RUN FIRST: SELECT count(*) ... then show the user before deleting
DELETE FROM {{table}} WHERE ref LIKE 'qa-%' AND created_at < now() - interval '1 day';
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| {{...}} | {{...}} | {{...}} |
