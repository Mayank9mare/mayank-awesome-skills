---
name: qa
description: E2E QA automation for SFN-based workflows. Runs preflight checks, executes test scenarios step-by-step, validates via Loki logs + AWS SFN + service APIs, and reports pass/fail.
user-invocable: true
---

# SFN QA Automation

Automated E2E testing for Step Function workflows on stage/prod. Generic framework — feature-specific scenarios live in task files under `tasks/`.

## When to Use

- User says `/qa {feature}`, `/qa {feature} {scenario}`, `/qa {feature} preflight`
- User wants to run E2E tests on stage for an SFN-based flow
- User wants to validate a deployment by running through test scenarios

## Usage

```
/qa {feature}                    — list available scenarios
/qa {feature} preflight          — run pre-flight checks only
/qa {feature} {scenario}         — run a specific scenario
/qa {feature} all                — run all scenarios sequentially
```

## Architecture

```
SKILL.md              ← you are here (generic framework)
tasks/
  {feature}.md        ← feature-specific: env, scenarios, curls, expected states, DB queries, troubleshooting
```

To add a new feature, create a task file under `tasks/` following the Task File Format below.

## Step 1: Load Task File

Read `~/.claude/skills/qa/tasks/{feature}.md`. If not found, list available task files.

The task file defines:
- **Environment** — hosts, SFN ARN, region, headers
- **Preflight** — service-specific health + config checks
- **Scenarios** — step-by-step test flows with curls and validation
- **Curl Templates** — named curl blocks with `{{PLACEHOLDER}}` substitution
- **Expected States** — DB status, SFN state, log patterns per step
- **Troubleshooting** — feature-specific failure patterns

## Step 2: Preflight Protocol

Run these checks before any scenario. Report pass/fail for each.

### Generic checks (always run)

1. **Service health** — `curl {{HOST}}/actuator/health` → expect 200
2. **Loki connectivity** — `loki_query(env="stage", service_name="{{SERVICE}}", includes=["INFO"], limit=1)` → expect results
3. **SFN exists** — `aws stepfunctions describe-state-machine --state-machine-arn {{SFN_ARN}} --region {{REGION}}` → expect status=ACTIVE
4. **No stuck executions** — `aws stepfunctions list-executions --state-machine-arn {{SFN_ARN}} --status-filter RUNNING --region {{REGION}}` → report count (warn if > 5)

### Feature-specific checks

Run whatever the task file's `## Preflight` section defines (config seeded, queues exist, dependencies healthy).

### Preflight report

```
## Preflight: {feature}
| Check | Status | Details |
|-------|--------|---------|
| Service health | PASS | 200 OK |
| Loki | PASS | Connected |
| SFN | PASS | ACTIVE, updated 2026-05-27 |
| Running executions | WARN | 2 running |
| Feature config | PASS | configs found |
```

## Step 2b: Cleanup (before each scenario)

If the task file has a `cleanup` section, **always ask user permission before running DELETEs.** Never run destructive DB operations without explicit confirmation.

1. Show the user what will be deleted (table names, filter criteria)
2. Ask for permission via AskUserQuestion
3. If approved: run cleanup queries + stop running SFN executions
4. If denied: skip cleanup, warn that test may fail on duplicate records

## Step 3: Execute Scenario

For each step in the scenario:

### 3a. Fire Action

Execute the curl from the task file. Substitute `{{PLACEHOLDERS}}` with values from:
- Previous step responses (chain forward)
- User-provided values
- Generated values (unique app_form_id, timestamp)

### 3b. Wait

Wait the specified duration (default 10s) for async processing (SQS → consumer → DB update).

### 3c. Validate (run ALL of these after EVERY step)

**1. Service API check** — call the task file's `get-details` curl to get current state:
- Check `last_event_status` matches expected
- Check `higher_order_status` matches expected
- Check `is_active` matches expected
- Check events timeline has the expected new event

**2. Log error check** — query for errors in the primary service:
- Build query: `{{LOG_STREAM_SELECTOR}} |~ "ERROR" |~ "{{CORRELATION_ID}}"`
- PASS if no results
- FAIL if errors found (include log messages in report)

**3. Log step completion** — query for step-specific keyword:
- Build query: `{{LOG_STREAM_SELECTOR}} |~ "{{STEP_KEYWORD}}"`
- PASS if expected log patterns found
- FAIL if missing after wait

**4. SFN execution check** — query execution status + current state:
```bash
# Get execution status
aws stepfunctions describe-execution --execution-arn {{EXEC_ARN}} --region {{REGION}} \
  --query '{status:status, startDate:startDate, stopDate:stopDate}'

# Get last 5 state transitions
aws stepfunctions get-execution-history --execution-arn {{EXEC_ARN}} --reverse-order --max-results 10 --region {{REGION}} \
  --query 'events[?type==`TaskStateEntered` || type==`TaskStateExited`].{type:type, state:stateEnteredEventDetails.name || stateExitedEventDetails.name, ts:timestamp}'
```
- PASS if current state matches expected from Expected States table
- FAIL if unexpected state, FAILED/TIMED_OUT status, or stuck

**5. DB check (optional, for deeper validation)** — run the task file's DB validation queries:
- Check the feature's core tables (as defined in the task file)
- Only when API response is insufficient (e.g., checking a JSON metadata field)

**6. Cross-service log check (if applicable)** — query downstream service logs:
- Check each downstream service's logs after the steps that call it (as defined in the task file)

### 3d. Record Result

Store step result: PASS/FAIL, duration, notes (error messages, unexpected values).

If a step FAILs:
1. Log the failure details
2. Ask user: continue to next step, retry this step, or abort scenario?
3. In auto mode: abort scenario and report

## Step 4: Report

After scenario completes (or aborts), output:

```
## QA Report: {feature} / {scenario}
**Result: PASS** (or FAIL at step N)
**Duration: 45s**

| # | Step | Status | Duration | Notes |
|---|------|--------|----------|-------|
| 1 | Step A | PASS | 1.2s | id=456 |
| 2 | Step B | PASS | 8.1s | workflowId=789 |
| 3 | Step C | PASS | 0.8s | |
| 4 | Step D | FAIL | 12.3s | HTTP 500 — see errors |
| ... | | | | |

### Errors
- Step D: HTTP 500 — `{"error": "process_failed", ...}`

### Warnings
- (any non-blocking observations)

### Loki Errors (last 30min)
- (errors found for this request, or "none")
```

## Tools Reference

### Log Platform

Query service logs for validation. The task file's `## Environment` section defines:
- `Log Platform URL` — base URL for log queries
- `Log Query API` — API path (e.g., `/loki/api/v1/query_range`)
- `Log Stream Selector` — how to filter by service (e.g., `{subsystemName=~"{{SERVICE}}"}`)
- `Log Services` — map of logical name → stream selector value

**Generic query pattern:**
```bash
START=$(date -u -v-{{MINUTES}}M +"%Y-%m-%dT%H:%M:%SZ")
END=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s "{{LOG_PLATFORM_URL}}{{LOG_QUERY_API}}" \
  --data-urlencode 'query={{LOG_STREAM_SELECTOR}} |~ "keyword1" |~ "keyword2"' \
  --data-urlencode "start=$START" --data-urlencode "end=$END" --data-urlencode "limit=20"
```

**Filter syntax (LogQL-compatible):**
- `|~ "keyword"` — regex include filter (AND with multiple)
- `!~ "keyword"` — regex exclude filter
- Multiple `|~` are ANDed: `|~ "ERROR" |~ "requestId=123"` matches lines with both

**Error check pattern:**
```bash
# Query for errors in a service within last N minutes
{{LOG_STREAM_SELECTOR}} |~ "ERROR" |~ "{{CORRELATION_ID}}"
```

**Step completion pattern:**
```bash
# Query for step-specific log keyword
{{LOG_STREAM_SELECTOR}} |~ "{{STEP_KEYWORD}}" |~ "{{CORRELATION_ID}}"
```

**Parse response (Loki format):**
```bash
| python3 -c "
import json,sys
d=json.load(sys.stdin)
for stream in d.get('data',{}).get('result',[]):
    for ts, line in stream.get('values',[]):
        try:
            log = json.loads(json.loads(line).get('log','{}') if 'log' in line else line)
            print(f'{log.get(\"level\",\"?\")} {log.get(\"message\",line[:200])}')
        except: print(line[:200])
"
```

**Note:** If migrating to a different log platform (e.g., Elasticsearch, CloudWatch), update the task file's environment section — the query patterns above stay the same as long as the new platform supports similar filter syntax.

### AWS Credentials

AWS credentials typically expire hourly (`ExpiredTokenException` on any aws CLI / MCP call). If your org uses
an SSO credential helper (e.g. `aws-okta`, `aws-okta-py`, `saml2aws`) that supports non-interactive refresh,
refresh them **yourself** rather than asking the user — document the exact commands for your org's tool below
the first time you use this skill.

```bash
# Example pattern (adapt to your org's SSO/credential tool):
# Step 1: refresh credentials via your SSO credential helper
{{your-credential-refresh-command}}

# Step 2: verify
aws sts get-caller-identity --query 'Account' --output text   # expect {{your-account-id}}
```

Notes:
- Use a generous Bash `timeout` (e.g. 90000 ms) — a SAML/SSO round-trip can take 10-30s.
- If your credential tool ever blocks on a prompt it can't satisfy non-interactively (e.g. an MFA challenge),
  fall back to asking the user to run the refresh command themselves via `!`.
- Refresh commands should be safe/idempotent and only rewrite `~/.aws/credentials`.

### AWS CLI — Step Functions

```bash
# List executions
aws stepfunctions list-executions --state-machine-arn {{ARN}} --status-filter RUNNING --max-results 5 --region {{REGION}}

# Describe execution
aws stepfunctions describe-execution --execution-arn {{EXEC_ARN}} --region {{REGION}}

# Get history (most recent events first)
aws stepfunctions get-execution-history --execution-arn {{EXEC_ARN}} --reverse-order --max-results 20 --region {{REGION}}
```

### AWS CLI — SQS

```bash
# Queue depth
aws sqs get-queue-attributes --queue-url {{QUEUE_URL}} --attribute-names ApproximateNumberOfMessages --region {{REGION}}

# Send test message (for simulating events)
aws sqs send-message --queue-url {{QUEUE_URL}} --message-body '{{BODY}}' --region {{REGION}}
```

### SQS Event Simulation

Many SFN workflows pause at wait states expecting external events (user actions, partner webhooks, timer callbacks). In E2E testing, simulate these by publishing directly to the SQS queue.

**Pattern:**
```bash
aws sqs send-message \
  --queue-url "https://sqs.{{REGION}}.amazonaws.com/{{ACCOUNT_ID}}/{{QUEUE_NAME}}" \
  --message-body '{{JSON_PAYLOAD}}' \
  --region {{REGION}}
```

**When to use:** The task file's scenario steps will specify `simulate-*` actions — these map to SQS publishes defined in the Curl Templates section.

**Common simulation targets:**
- User document upload events (simulates a document-processing service callback)
- Partner decision events (simulates a partner webhook relay)
- Timer callbacks (simulates a scheduler lapse/reminder fire)
- External service callbacks (simulates any async response)

**Verify queue received the message:**
```bash
# Check queue depth increased
aws sqs get-queue-attributes \
  --queue-url "https://sqs.{{REGION}}.amazonaws.com/{{ACCOUNT_ID}}/{{QUEUE_NAME}}" \
  --attribute-names ApproximateNumberOfMessages \
  --region {{REGION}} \
  --query 'Attributes.ApproximateNumberOfMessages' --output text
```

**Check DLQ for failed processing:**
```bash
aws sqs get-queue-attributes \
  --queue-url "https://sqs.{{REGION}}.amazonaws.com/{{ACCOUNT_ID}}/{{QUEUE_NAME}}-dlq" \
  --attribute-names ApproximateNumberOfMessages \
  --region {{REGION}} \
  --query 'Attributes.ApproximateNumberOfMessages' --output text
```

**SAFETY:** Only publish to stage queues. Never publish to prod queues without explicit user permission.

### Stage DB Access

Query the stage database directly for validation. Connection details come from the task file's `## Environment` section (DB Host, Port, Name, User, SSM path for password).

**Fetch password (run once per session):**
```bash
DB_PASS=$(aws ssm get-parameter --name "{{SSM_PASSWORD_PATH}}" --region {{REGION}} --with-decryption --query 'Parameter.Value' --output text)
```

**Run queries:**
```bash
mysql -h "{{DB_HOST}}" -P {{DB_PORT}} -u "{{DB_USER}}" -p"$DB_PASS" "{{DB_NAME}}" -e "{{QUERY}}"
```

All DB values (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`, `SSM_PASSWORD_PATH`) are defined in the task file — never hardcode them here.

**SAFETY RULES:**
- **NEVER run UPDATE, DELETE, INSERT, ALTER, DROP** without explicit user permission
- Only use SELECT queries for validation
- Always add `LIMIT` to prevent large result sets
- Do not log or display the password in output

### Curl Execution

When firing curls for test scenarios:

1. **Always capture HTTP status code:**
   ```bash
   RESPONSE=$(curl -s -w "\n%{http_code}" {{CURL_ARGS}})
   HTTP_CODE=$(echo "$RESPONSE" | tail -1)
   BODY=$(echo "$RESPONSE" | sed '$d')
   echo "HTTP $HTTP_CODE"
   echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
   ```

2. **Extract values from responses for chaining:**
   ```bash
   # Extract inspection_id from response
   INSPECTION_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('data',{}).get('id',''))" 2>/dev/null)
   ```

3. **Generate unique test data per run:**
   ```bash
   TIMESTAMP=$(date +%s)
   APP_FORM_ID="af-qa-${TIMESTAMP}"
   SUBJECT_ID="QA-KA01XX${TIMESTAMP: -4}"
   ```

4. **Timeout protection:** Add `--connect-timeout 10 --max-time 30` to all curls

### Jenkins

**CRITICAL: NEVER trigger a build without explicit user permission.**

Authentication (see the `jenkins` skill for full details):
```bash
source ~/.zshrc 2>/dev/null
: "${JENKINS_URL:?Set JENKINS_URL in ~/.zshrc}"
JENKINS_AUTH="$JENKINS_USER:$JENKINS_TOKEN"  # from ~/.zshrc
```

#### Pre-QA: Deploy latest code

Before running QA, ensure the latest code is deployed. Ask user if they want to deploy.

```bash
# 1. Check last build status
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{{SERVICE}}-stage/lastBuild/api/json?tree=number,result,building,timestamp" | \
  python3 -c "import json,sys,datetime; d=json.load(sys.stdin); print(f'Build #{d[\"number\"]} {\"BUILDING\" if d.get(\"building\") else d.get(\"result\",\"?\")} at {datetime.datetime.fromtimestamp(d[\"timestamp\"]/1000).strftime(\"%Y-%m-%d %H:%M\")}')"

# 2. Trigger stage build (REQUIRES USER PERMISSION)
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
curl -s -X POST -u "$JENKINS_AUTH" -H "Jenkins-Crumb: $CRUMB" "$JENKINS_URL/job/{{SERVICE}}-stage/build"

# 3. Poll build status (check every 30s)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{{SERVICE}}-stage/lastBuild/api/json?tree=number,result,building"

# 4. Check console logs on failure (last 100 lines)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{{SERVICE}}-stage/lastBuild/consoleText" | tail -100
```

#### Post-deploy health check

After deploy completes, wait 60s for ECS health check grace period, then:
```bash
# Health check (retry up to 5 times with 15s interval)
for i in 1 2 3 4 5; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "{{HOST}}/actuator/health")
  echo "Attempt $i: HTTP $STATUS"
  [ "$STATUS" = "200" ] && break
  sleep 15
done
```

#### Deploy multiple services

Some QA scenarios need dependencies deployed first. Deploy in order (downstream before upstream):
1. Downstream/dependency services first (as listed in the task file's `## Deploy` section)
2. The main service under test
3. Wait 60s for health check grace period
4. Run preflight

#### Monitor ongoing build

```bash
# Check if build is still running
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{{SERVICE}}-stage/lastBuild/api/json?tree=building,result" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('BUILDING' if d.get('building') else d.get('result','UNKNOWN'))"

# Stream logs (progressive)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{{SERVICE}}-stage/lastBuild/progressiveText?start=0"
```

#### Update SFN after deploy

SFN definition is not auto-deployed — must be updated manually after code deploy:
```bash
aws stepfunctions update-state-machine \
  --state-machine-arn "{{SFN_ARN}}" \
  --definition "$(cat {{SFN_JSON_PATH}})" \
  --region {{REGION}}
```

## Common Failure Patterns

These are generic patterns — task files define feature-specific troubleshooting.

| HTTP Code | Meaning | Diagnosis |
|-----------|---------|-----------|
| `417` | Scheduler EXPECTATION_FAILED | Job type not registered |
| `5xx` | Internal server error | Check Loki for stack trace |
| `412` | Precondition failed | Upstream dependency state mismatch |
| `400` | Bad request to downstream | Missing headers or mandatory fields |
| `States.Timeout` | SFN state timed out | Consumer not processing — check queue depth + DLQ |
| `States.TaskFailed` | SFN task failed | Consumer threw unhandled exception |

## Task File Format

Each task file under `tasks/` must follow this structure:

```markdown
## Environment
(hosts, SFN ARN, AWS region, default headers, Loki service name,
 Jenkins job names, SFN JSON path, DB host/port/name/user/SSM password path)

## Deploy
(deploy order, Jenkins job curls, health check, SFN update command)

## Preflight
(numbered list of feature-specific checks with curl/CLI commands)

## Scenarios
### {scenario-name}
#### Steps
| # | Name | Action | Wait | Validate |
(step table — action is curl template name, validate is what to check)

## Curl Templates
(named curl blocks with {{PLACEHOLDER}} substitution)

## Expected States
(map: step → expected DB status, SFN state, log patterns)

## DB Validation Queries
(ready-to-use SELECT queries for each validation point)

## Loki Validation Patterns
(loki_query calls for error checks and step completion)

## Troubleshooting
(feature-specific failure patterns and fixes)

## Status Reference
(state transition diagram for the feature)

## SFN State Machine Reference
(state flow summary)
```

## Generating Unique Test Data

For each test run, generate unique identifiers to avoid collisions:
- `APP_FORM_ID`: `af-qa-{timestamp}` (e.g., `af-qa-1716728400`)
- `USER_ID`: use a dedicated test user (from task file)
- `SUBJECT_ID`: `QA-{random}` (e.g., `QA-KA01XX9999`)
