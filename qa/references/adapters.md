# Adapter Reference

Concrete commands for every adapter type the task file can declare. The task file names
a type and supplies the config keys; this file supplies the command.

Every snippet uses `{{PLACEHOLDER}}` for config the task file provides. Nothing here is
run unless the task file declares that adapter.

Each adapter section gives:
- **Config keys** — what the task file must supply
- **Reachability** — the preflight check
- **Read probes** — status / state / evidence queries
- **Write actions** — only where the adapter is used to *drive* the system (event
  injection, signals). Gated by the tier rules in SKILL.md.

---

## health

### `http-endpoint`
Config: `url`, optional `expect_status` (default 200), `expect_body_contains`.
```bash
curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 "{{url}}"
```
Retry loop for post-deploy grace periods:
```bash
for i in $(seq 1 "{{retries:-5}}"); do
  S=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "{{url}}" || echo 000)
  [ "$S" = "{{expect_status:-200}}" ] && { echo "healthy after $i"; break; }
  echo "attempt $i: $S"; sleep "{{interval:-15}}"
done
```

### `k8s-readiness`
Config: `context`, `namespace`, `selector`.
```bash
kubectl --context {{context}} -n {{namespace}} get pods -l {{selector}} \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{.status.containerStatuses[0].ready}{"\n"}{end}'
```

### `tcp`
Config: `host`, `port`.
```bash
nc -z -w 5 {{host}} {{port}} && echo open || echo closed
```

---

## api

### `http` / `rest`
Config: `base_url`, `headers` (map), optional `auth_cmd` (prints a token).

Canonical call with status capture and chaining:
```bash
TOKEN=$({{auth_cmd}})            # omit if no auth
RESP=$(curl -sS -w '\n%{http_code}' --connect-timeout 10 --max-time 30 \
  -X {{method}} "{{base_url}}{{path}}" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  {{extra_headers}} {{body_flag}})
CODE=$(printf '%s' "$RESP" | tail -1)
BODY=$(printf '%s' "$RESP" | sed '$d')
echo "HTTP $CODE"; printf '%s' "$BODY" | jq . 2>/dev/null || printf '%s\n' "$BODY"
```
Extract a chained value:
```bash
ORDER_ID=$(printf '%s' "$BODY" | jq -r '{{jq_path}} // empty')
```

### `graphql`
Config: `endpoint`, `headers`.
```bash
curl -sS -X POST "{{endpoint}}" -H 'Content-Type: application/json' {{extra_headers}} \
  -d "$(jq -nc --arg q '{{query}}' --argjson v '{{variables}}' '{query:$q,variables:$v}')" | jq .
```
GraphQL returns 200 on errors — always assert on `.errors == null`, never on status alone.

### `grpc`
Config: `target`, `proto_dir` or reflection, `service`, `method`.
```bash
grpcurl -plaintext -import-path {{proto_dir}} -proto {{proto}} \
  -d '{{json_request}}' {{target}} {{service}}/{{method}}
# reflection-enabled servers:
grpcurl -plaintext -d '{{json_request}}' {{target}} {{service}}/{{method}}
```

---

## workflow

The workflow probe answers three questions: **which execution**, **what state**, **did
it fail**. Every type below must support: find-execution-by-correlation-id, describe,
recent-history, and (where the engine allows) signal injection.

### `sfn` — AWS Step Functions
Config: `state_machine_arn`, `region`, optional `profile`.
```bash
# reachability
aws stepfunctions describe-state-machine --state-machine-arn {{state_machine_arn}} \
  --region {{region}} --query '{status:status,updated:updateDate}'

# find execution by name/correlation (execution name usually carries the RUN_ID)
aws stepfunctions list-executions --state-machine-arn {{state_machine_arn}} \
  --region {{region}} --max-results 50 \
  --query "executions[?contains(name,'$RUN_ID')].[name,status,executionArn]" --output text

# state
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --region {{region}} \
  --query '{status:status,start:startDate,stop:stopDate}'

# current/recent states
aws stepfunctions get-execution-history --execution-arn "$EXEC_ARN" --reverse-order \
  --max-results 20 --region {{region}} \
  --query 'events[?type==`TaskStateEntered`||type==`TaskStateExited`||type==`ExecutionFailed`].{t:type,s:stateEnteredEventDetails.name||stateExitedEventDetails.name,ts:timestamp}'

# stuck detection
aws stepfunctions list-executions --state-machine-arn {{state_machine_arn}} \
  --status-filter RUNNING --region {{region}} --query 'length(executions)'
```
Signal injection: SFN has no native signal — a paused `waitForTaskToken` state is
resumed via `send-task-success`, or by publishing to the queue its consumer reads.
```bash
aws stepfunctions send-task-success --task-token "$TOKEN" --output '{{json}}' --region {{region}}
```
Failure decoding: `States.Timeout` (nothing resumed the wait — check the bus and DLQ),
`States.TaskFailed` (unhandled exception in the task — check logs),
`States.Runtime` (definition/IO shape error), `States.DataLimitExceeded` (payload > 256KB).

### `temporal`
Config: `address`, `namespace`, optional `tls_cert`/`tls_key`, `workflow_type`.
```bash
# reachability
temporal operator namespace describe --namespace {{namespace}} --address {{address}}

# find by correlation — prefer a searchable workflow id containing RUN_ID
temporal workflow list --namespace {{namespace}} --address {{address}} \
  --query "WorkflowType='{{workflow_type}}' AND WorkflowId STARTS_WITH '$RUN_ID'" -o json

# state
temporal workflow describe --workflow-id "$WF_ID" --namespace {{namespace}} \
  --address {{address}} -o json | jq '{status:.workflowExecutionInfo.status, taskQueue:.workflowExecutionInfo.taskQueue}'

# history tail
temporal workflow show --workflow-id "$WF_ID" --namespace {{namespace}} \
  --address {{address}} -o json | jq '[.events[] | {id:.eventId,type:.eventType}] | .[-20:]'

# stuck/open executions
temporal workflow list --namespace {{namespace}} --address {{address}} \
  --query "ExecutionStatus='Running'" -o json | jq 'length'
```
Signal injection — this is the clean way to drive Temporal wait states in a test:
```bash
temporal workflow signal --workflow-id "$WF_ID" --name {{signal_name}} \
  --input '{{json}}' --namespace {{namespace}} --address {{address}}
```
Also useful in QA: `temporal workflow cancel|terminate` (lifecycle class),
`temporal workflow reset --type LastWorkflowTask` (replay/determinism class).
Failure decoding: `WorkflowExecutionFailed` (activity exhausted retries — read
`.failure.cause`), `WorkflowTaskTimedOut` (worker down or poisoned task),
`ActivityTaskTimedOut` with `StartToClose` (activity slower than budget),
`Terminated` (someone killed it — usually a prior cleanup).

### `cadence`
Config: `address`, `domain`. Same shape as Temporal via `cadence --do {{domain}} workflow describe|list|signal`.

### `airflow`
Config: `base_url`, `dag_id`, `auth`.
```bash
# reachability + dag state
curl -sS -u "{{auth}}" "{{base_url}}/api/v1/dags/{{dag_id}}" | jq '{paused:.is_paused,active:.is_active}'
# run state
curl -sS -u "{{auth}}" "{{base_url}}/api/v1/dags/{{dag_id}}/dagRuns/{{run_id}}" | jq '.state'
# task instances
curl -sS -u "{{auth}}" "{{base_url}}/api/v1/dags/{{dag_id}}/dagRuns/{{run_id}}/taskInstances" \
  | jq '[.task_instances[] | {id:.task_id,state:.state,try:.try_number}]'
# trigger (write — tier-gated)
curl -sS -u "{{auth}}" -X POST "{{base_url}}/api/v1/dags/{{dag_id}}/dagRuns" \
  -H 'Content-Type: application/json' -d '{"dag_run_id":"'"$RUN_ID"'","conf":{{conf}}}'
```

### `camunda` (Zeebe / Camunda 8)
Config: `address`, `process_id`, optional `operate_url`.
```bash
zbctl --address {{address}} status
zbctl --address {{address}} create instance {{process_id}} --variables '{{json}}'
zbctl --address {{address}} publish message --correlationKey "$RUN_ID" --name {{msg_name}} --variables '{{json}}'
# state via Operate API
curl -sS "{{operate_url}}/v1/process-instances/search" -H 'Content-Type: application/json' \
  -d '{"filter":{"bpmnProcessId":"{{process_id}}"},"size":20}' | jq '.items[] | {key,state}'
```

### `argo` (Argo Workflows)
Config: `namespace`, `context`.
```bash
argo list -n {{namespace}} --context {{context}} -o json | jq '[.[] | {name:.metadata.name,phase:.status.phase}]'
argo get "$WF_NAME" -n {{namespace}} -o json | jq '{phase:.status.phase,message:.status.message}'
argo resubmit|terminate "$WF_NAME" -n {{namespace}}
```

### `none`
Feature has no orchestrator. Skip all workflow probes; rely on `api` + `store` for state.

---

## queue

Used for two things: **evidence** (depth, DLQ, consumer lag) and **injection**
(simulating a partner webhook, a callback, a timer fire, a duplicate delivery).

### `sqs`
Config: `queue_url`, `dlq_url`, `region`.
```bash
# depth + in-flight
aws sqs get-queue-attributes --queue-url {{queue_url}} --region {{region}} \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --query 'Attributes'
# DLQ sweep (assert zero)
aws sqs get-queue-attributes --queue-url {{dlq_url}} --region {{region}} \
  --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text
# read a DLQ message without consuming it permanently
aws sqs receive-message --queue-url {{dlq_url}} --region {{region}} --max-number-of-messages 5 \
  --visibility-timeout 0 --query 'Messages[].Body'
# inject (write — tier-gated)
aws sqs send-message --queue-url {{queue_url}} --region {{region}} --message-body '{{json}}'
# FIFO injection needs the dedup/group ids — key dedup on RUN_ID to control replay
aws sqs send-message --queue-url {{queue_url}} --region {{region}} --message-body '{{json}}' \
  --message-group-id "{{group}}" --message-deduplication-id "$RUN_ID-{{n}}"
```

### `pubsub` — GCP Pub/Sub
Config: `project`, `topic`, `subscription`, `dlq_subscription`.
```bash
gcloud pubsub subscriptions describe {{subscription}} --project {{project}} --format='value(name,ackDeadlineSeconds)'
# undelivered backlog (via monitoring, Pub/Sub has no direct depth call)
gcloud monitoring time-series list --project {{project}} \
  --filter='metric.type="pubsub.googleapis.com/subscription/num_undelivered_messages" AND resource.labels.subscription_id="{{subscription}}"' \
  --format='value(points[0].value.int64Value)' 2>/dev/null
# DLQ sweep — pull without acking
gcloud pubsub subscriptions pull {{dlq_subscription}} --project {{project}} --limit 5 --format=json
# inject (write — tier-gated)
gcloud pubsub topics publish {{topic}} --project {{project}} --message '{{json}}' \
  --attribute="run_id=$RUN_ID{{,extra_attrs}}"
```
Ordering: only guaranteed with `--ordering-key` on a subscription created with message
ordering enabled — required for out-of-order tests to mean anything.

### `kafka`
Config: `bootstrap`, `topic`, `dlq_topic`, `group`, optional `config_file` (SASL/TLS).
```bash
CFG="--command-config {{config_file}}"      # omit for plaintext
# reachability + topic exists
kafka-topics.sh --bootstrap-server {{bootstrap}} $CFG --describe --topic {{topic}}
# consumer lag — the real health signal
kafka-consumer-groups.sh --bootstrap-server {{bootstrap}} $CFG --describe --group {{group}}
# tail recent messages (evidence)
kafka-console-consumer.sh --bootstrap-server {{bootstrap}} --topic {{topic}} \
  --from-beginning --max-messages 20 --timeout-ms 10000 --property print.key=true
# DLQ sweep
kafka-console-consumer.sh --bootstrap-server {{bootstrap}} --topic {{dlq_topic}} \
  --max-messages 5 --timeout-ms 5000
# inject (write — tier-gated); key controls partition, which controls ordering
printf '%s\n' '{{key}}:{{json}}' | kafka-console-producer.sh --bootstrap-server {{bootstrap}} \
  --topic {{topic}} --property parse.key=true --property key.separator=:
```
For ordering/race tests: same key ⇒ same partition ⇒ ordered. Different keys give you
*no* ordering guarantee — which is exactly how you construct an out-of-order test.

### `rabbitmq`
Config: `mgmt_url`, `vhost`, `queue`, `dlq`, `auth`.
```bash
curl -sS -u "{{auth}}" "{{mgmt_url}}/api/queues/{{vhost}}/{{queue}}" | jq '{ready:.messages_ready,unacked:.messages_unacknowledged,consumers:.consumers}'
curl -sS -u "{{auth}}" "{{mgmt_url}}/api/queues/{{vhost}}/{{dlq}}" | jq '.messages_ready'
# inject (write — tier-gated)
curl -sS -u "{{auth}}" -X POST "{{mgmt_url}}/api/exchanges/{{vhost}}/{{exchange}}/publish" \
  -H 'Content-Type: application/json' \
  -d '{"properties":{},"routing_key":"{{rk}}","payload":{{json_string}},"payload_encoding":"string"}'
```

### `eventbridge`
Config: `bus_name`, `region`.
```bash
aws events describe-event-bus --name {{bus_name}} --region {{region}} --query 'Name'
aws events list-rules --event-bus-name {{bus_name}} --region {{region}} --query 'Rules[].{n:Name,s:State}'
# inject (write — tier-gated)
aws events put-events --region {{region}} --entries \
  '[{"EventBusName":"{{bus_name}}","Source":"{{source}}","DetailType":"{{type}}","Detail":{{json_string}}}]'
```

### `nats` / JetStream
Config: `server`, `stream`, `subject`, `consumer`.
```bash
nats --server {{server}} stream info {{stream}} --json | jq '{msgs:.state.messages}'
nats --server {{server}} consumer info {{stream}} {{consumer}} --json | jq '{pending:.num_pending,ack_pending:.num_ack_pending}'
nats --server {{server}} pub {{subject}} '{{json}}'
```

### `none`
No bus. Injection steps must instead drive the system through its `api` adapter.

---

## store

**SELECT-only unless the user explicitly approves a write. Always bound with LIMIT.**
Credentials come from the task file's `## Credentials` section and are never printed.

### `mysql`
Config: `host`, `port`, `db`, `user`, `password_cmd`.
```bash
DB_PASS=$({{password_cmd}})
mysql -h {{host}} -P {{port}} -u {{user}} -p"$DB_PASS" {{db}} \
  --batch --raw -e "{{query}} LIMIT 50"
```

### `postgres`
Config: `host`, `port`, `db`, `user`, `password_cmd`, optional `sslmode`.
```bash
export PGPASSWORD=$({{password_cmd}})
psql -h {{host}} -p {{port}} -U {{user}} -d {{db}} -At -c "{{query}} LIMIT 50"
unset PGPASSWORD
```
Race-test helper — prove serialization actually happened:
```bash
psql ... -At -c "SELECT xmin, version, status FROM {{table}} WHERE ref = '$RUN_ID'"
```

### `dynamodb`
Config: `table`, `region`, optional `index`.
```bash
aws dynamodb get-item --table-name {{table}} --region {{region}} \
  --key '{"{{pk}}":{"S":"'"$RUN_ID"'"}}' --consistent-read | jq '.Item'
aws dynamodb query --table-name {{table}} --region {{region}} {{index_flag}} \
  --key-condition-expression '{{kce}}' \
  --expression-attribute-values '{{eav}}' --limit 50 --consistent-read \
  --query '{count:Count,items:Items}'
```
**Always `--consistent-read` in assertions.** Eventually-consistent reads make race
tests report phantom passes and phantom failures alike.

### `spanner`
Config: `project`, `instance`, `database`.
```bash
gcloud spanner databases execute-sql {{database}} --instance={{instance}} --project={{project}} \
  --sql="{{query}} LIMIT 50"
```

### `bigquery`
Config: `project`, `dataset`.
```bash
bq --project_id={{project}} query --nouse_legacy_sql --format=prettyjson \
  --max_rows=50 "{{query}}"
```
BigQuery is analytic and lags — never use it for settle-window assertions; use it for
after-the-fact reconciliation checks only.

### `firestore`
Config: `project`, `collection`.
```bash
gcloud firestore documents list --project={{project}} --collection-ids={{collection}} --limit=50 --format=json
# or, for query support:
curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://firestore.googleapis.com/v1/projects/{{project}}/databases/(default)/documents/{{collection}}?pageSize=50"
```

### `mongodb`
Config: `uri_cmd`, `db`, `collection`.
```bash
mongosh "$({{uri_cmd}})" --quiet --eval \
  'db.getSiblingDB("{{db}}").{{collection}}.find({{filter}}).limit(50).toArray()'
# exactly-once assertion
mongosh "$({{uri_cmd}})" --quiet --eval \
  'db.getSiblingDB("{{db}}").{{collection}}.countDocuments({{filter}})'
```

### `redis` (state/lock inspection)
Config: `host`, `port`, `auth_cmd`.
```bash
redis-cli -h {{host}} -p {{port}} --no-auth-warning -a "$({{auth_cmd}})" GET "{{key}}"
redis-cli ... TTL "{{lock_key}}"     # distributed-lock races: is the lock actually held?
```

---

## object

### `s3`
Config: `bucket`, `prefix`, `region`.
```bash
aws s3api list-objects-v2 --bucket {{bucket}} --prefix "{{prefix}}$RUN_ID" --region {{region}} \
  --query '{count:KeyCount,keys:Contents[].{k:Key,size:Size,t:LastModified}}'
aws s3api head-object --bucket {{bucket}} --key "{{key}}" --region {{region}} \
  --query '{size:ContentLength,type:ContentType,etag:ETag}'
aws s3 cp "s3://{{bucket}}/{{key}}" - --region {{region}} | head -c 2000
```

### `gcs`
Config: `bucket`, `prefix`, `project`.
```bash
gcloud storage ls --project={{project}} "gs://{{bucket}}/{{prefix}}$RUN_ID*" --long
gcloud storage objects describe "gs://{{bucket}}/{{key}}" --project={{project}} \
  --format='value(size,contentType,generation)'
gcloud storage cat "gs://{{bucket}}/{{key}}" | head -c 2000
```
`generation` is the object version — a second generation on a key that should be written
once is an exactly-once violation.

### `azure-blob`
Config: `account`, `container`, `prefix`.
```bash
az storage blob list --account-name {{account}} --container-name {{container}} \
  --prefix "{{prefix}}$RUN_ID" --query '[].{n:name,size:properties.contentLength}' -o json
az storage blob show --account-name {{account}} --container-name {{container}} --name {{key}} \
  --query '{size:properties.contentLength,etag:properties.etag}'
```

---

## logs

Two queries matter: **error sweep** (`level=error AND run_id`) and **step confirmation**
(`step keyword AND run_id`). Every type below must express both.

The single most important thing: **filter by the run's correlation id**, never by time
alone. Time-only queries pick up other people's traffic and produce false failures.

### `loki`
Config: `url`, `query_api` (default `/loki/api/v1/query_range`), `selector`, `auth`.
```bash
START=$(date -u -v-{{minutes}}M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "-{{minutes}} minutes" +%Y-%m-%dT%H:%M:%SZ)
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -sS "{{url}}{{query_api}}" {{auth_flag}} \
  --data-urlencode 'query={{selector}} |~ "(?i)error|exception" |~ "'"$RUN_ID"'"' \
  --data-urlencode "start=$START" --data-urlencode "end=$END" --data-urlencode 'limit=50' \
  | jq -r '.data.result[].values[][1]' | head -50
```
Filters: `|~` regex include (multiple are ANDed), `!~` exclude, `| json | field="x"`
for structured logs.

### `cloudwatch`
Config: `log_group`, `region`.
```bash
aws logs filter-log-events --log-group-name {{log_group}} --region {{region}} \
  --start-time $(( ($(date +%s) - {{minutes}}*60) * 1000 )) \
  --filter-pattern "\"$RUN_ID\" \"ERROR\"" --max-items 50 \
  --query 'events[].message' --output text
```
Insights, when you need structure:
```bash
QID=$(aws logs start-query --log-group-name {{log_group}} --region {{region}} \
  --start-time $(( $(date +%s) - {{minutes}}*60 )) --end-time $(date +%s) \
  --query-string "fields @timestamp,@message | filter @message like /$RUN_ID/ and level='ERROR' | limit 50" \
  --query 'queryId' --output text)
sleep 3; aws logs get-query-results --query-id "$QID" --region {{region}}
```

### `gcp-logging`
Config: `project`, `resource_filter`.
```bash
gcloud logging read \
  '{{resource_filter}} AND severity>=ERROR AND textPayload:"'"$RUN_ID"'"' \
  --project={{project}} --limit=50 --freshness={{minutes}}m --format='value(timestamp,severity,textPayload,jsonPayload.message)'
```
For structured logs prefer `jsonPayload.run_id="'"$RUN_ID"'"` over substring matching.

### `elasticsearch` / OpenSearch
Config: `url`, `index`, `auth`.
```bash
curl -sS "{{url}}/{{index}}/_search" {{auth_flag}} -H 'Content-Type: application/json' -d "$(jq -nc --arg r "$RUN_ID" '{
  size:50, sort:[{"@timestamp":"desc"}],
  query:{bool:{must:[{match_phrase:{message:$r}},{terms:{"level":["ERROR","FATAL"]}}],
  filter:[{range:{"@timestamp":{gte:"now-{{minutes}}m"}}}]}}}')" | jq -r '.hits.hits[]._source.message'
```

### `datadog`
Config: `site`, `api_key_cmd`, `app_key_cmd`, `query`.
```bash
curl -sS "https://api.{{site}}/api/v2/logs/events/search" \
  -H "DD-API-KEY: $({{api_key_cmd}})" -H "DD-APPLICATION-KEY: $({{app_key_cmd}})" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg r "$RUN_ID" '{filter:{query:("{{query}} status:error " + $r),from:"now-{{minutes}}m",to:"now"},page:{limit:50}}')" \
  | jq -r '.data[].attributes.message'
```

### `splunk`
Config: `url`, `auth_cmd`, `index`.
```bash
curl -sS -u "$({{auth_cmd}})" "{{url}}/services/search/jobs/export" \
  -d "search=search index={{index}} \"$RUN_ID\" (ERROR OR Exception) earliest=-{{minutes}}m" \
  -d output_mode=json | jq -r '._raw? // empty'
```

---

## metric

Optional but valuable: a scenario that passes functionally while doubling a counter is
still a bug.

### `prometheus`
Config: `url`.
```bash
curl -sS --get "{{url}}/api/v1/query" --data-urlencode 'query={{promql}}' | jq '.data.result'
# delta across a step: capture before and after, assert the difference
```

### `cloudwatch-metrics`
Config: `namespace`, `region`.
```bash
aws cloudwatch get-metric-statistics --namespace {{namespace}} --metric-name {{metric}} \
  --region {{region}} --start-time "$(date -u -v-10M +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 60 --statistics Sum \
  --dimensions {{dimensions}} --query 'Datapoints[].Sum'
```

### `gcp-monitoring`
```bash
gcloud monitoring time-series list --project {{project}} \
  --filter='metric.type="{{metric_type}}"' --format='value(points[0].value)'
```

---

## ci

Used only to answer "is the code under test actually deployed" and, with explicit
permission, to deploy it. **Never trigger a build or deploy without the user saying so
in this session.**

### `jenkins`
Config: `url`, `job`, `auth_cmd`.
```bash
AUTH=$({{auth_cmd}})
# last build state
curl -sS -u "$AUTH" "{{url}}/job/{{job}}/lastBuild/api/json?tree=number,result,building,timestamp" \
  | jq '{n:.number,result:(if .building then "BUILDING" else .result end),ts:.timestamp}'
# trigger (REQUIRES EXPLICIT PERMISSION)
CRUMB=$(curl -sS -u "$AUTH" "{{url}}/crumbIssuer/api/json" | jq -r .crumb)
curl -sS -X POST -u "$AUTH" -H "Jenkins-Crumb: $CRUMB" "{{url}}/job/{{job}}/build"
# console tail on failure
curl -sS -u "$AUTH" "{{url}}/job/{{job}}/lastBuild/consoleText" | tail -100
```

### `github-actions`
Config: `repo`, `workflow`.
```bash
gh run list --repo {{repo}} --workflow {{workflow}} --limit 5 \
  --json databaseId,status,conclusion,headSha,createdAt
gh run view "$RUN" --repo {{repo}} --log-failed | tail -100
# deployed-vs-HEAD drift
gh api repos/{{repo}}/deployments --jq '.[0].sha' 
# trigger (REQUIRES EXPLICIT PERMISSION)
gh workflow run {{workflow}} --repo {{repo}} --ref {{ref}}
```

### `gitlab-ci`
```bash
curl -sS -H "PRIVATE-TOKEN: $({{token_cmd}})" \
  "{{url}}/api/v4/projects/{{project_id}}/pipelines?ref={{ref}}&per_page=5" \
  | jq '[.[] | {id,status,sha}]'
```

### `argocd`
```bash
argocd app get {{app}} -o json | jq '{sync:.status.sync.status,health:.status.health.status,rev:.status.sync.revision}'
```

---

## Credential Refresh

Cloud credentials expire mid-run. The task file's `## Credentials` section declares a
refresh command per adapter family; run it yourself on an auth error and retry the
probe once before failing the step.

```bash
# AWS: expired token surfaces as ExpiredTokenException / InvalidClientTokenId
{{aws_refresh_cmd}}                      # e.g. aws sso login --profile X, saml2aws login, aws-okta
aws sts get-caller-identity --query Account --output text

# GCP: surfaces as "Reauthentication required" / invalid_grant
{{gcp_refresh_cmd}}                      # e.g. gcloud auth application-default login
gcloud auth list --filter=status:ACTIVE --format='value(account)'

# Azure
az account get-access-token >/dev/null && az account show --query id -o tsv
```
Use a generous Bash timeout (90s) — SSO round-trips are slow. If the refresh needs
interactive MFA it cannot satisfy, ask the user to run it via `!` rather than looping.
