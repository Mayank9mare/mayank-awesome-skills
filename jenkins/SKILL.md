---
name: jenkins
description: Interact with Jenkins CI/CD — list jobs, trigger builds, view logs, monitor queue, check build status, and manage deployments.
user-invocable: true
---

# Jenkins CI/CD Skill

Interact with a Jenkins instance via its REST API.

## CRITICAL SAFETY RULE

**NEVER trigger any Jenkins build, deployment, stop, create/delete job, or any state-changing POST request without the user's EXPLICIT permission.** Always ask and wait for confirmation before any write operation. This is non-negotiable — Jenkins actions affect shared infrastructure and real environments.

Read-only GET requests (list jobs, view logs, check status, get config) are safe and do not require permission.

## When to Use

- User says "trigger build", "deploy", "check build", "jenkins", "pipeline status"
- User asks about build logs, failures, queue status, or deployment progress
- User wants to trigger a deployment to a given environment
- User asks "is the build passing", "what failed", "show me the logs"

## Authentication

All requests use HTTP Basic Auth. Credentials and the Jenkins base URL are sourced from env vars in `~/.zshrc` (`JENKINS_URL`, `JENKINS_USER`, `JENKINS_TOKEN`) — never hardcode them in this file:

```bash
source ~/.zshrc 2>/dev/null
: "${JENKINS_URL:?Set JENKINS_URL in ~/.zshrc}"
: "${JENKINS_USER:?Set JENKINS_USER in ~/.zshrc}"
: "${JENKINS_TOKEN:?Set JENKINS_TOKEN in ~/.zshrc}"
JENKINS_AUTH="$JENKINS_USER:$JENKINS_TOKEN"
```

Every curl command below uses: `curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/..."`

## CSRF Token (Required for POST/DELETE)

Jenkins requires a crumb for state-changing operations:

```bash
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
# Then add header: -H "Jenkins-Crumb: $CRUMB"
```

---

## API Reference

### 1. Search/List Jobs

Find jobs by name pattern:

```bash
# Search for jobs matching a keyword
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/api/json?tree=jobs[name,color,url]" | \
  python3 -c "import json,sys; [print(f\"{j['name']} ({j.get('color','?')})\") for j in json.load(sys.stdin)['jobs'] if 'KEYWORD' in j['name'].lower()]"
```

Colors: `blue`=success, `red`=failure, `yellow`=unstable, `disabled`=disabled, `blue_anime`=building

### 2. Get Job Details

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/api/json" | \
  python3 -c "
import json,sys
d=json.load(sys.stdin)
lb=d.get('lastBuild',{})
print(f\"Job: {d['name']}\")
print(f\"Buildable: {d['buildable']}\")
print(f\"Status: {d['color']}\")
print(f\"Last Build: #{lb.get('number','?')}\")
print(f\"URL: {d['url']}\")
"
```

### 3. Get Build History

```bash
# Last 10 builds with result and duration
curl -s -u "$JENKINS_AUTH" \
  "$JENKINS_URL/job/{JOB_NAME}/api/json?tree=builds[number,result,timestamp,duration]{0,10}" | \
  python3 -c "
import json,sys,datetime
for b in json.load(sys.stdin)['builds']:
    ts=datetime.datetime.fromtimestamp(b['timestamp']/1000).strftime('%Y-%m-%d %H:%M')
    dur=f\"{b['duration']//1000}s\"
    print(f\"#{b['number']} {b['result'] or 'BUILDING':8} {ts} ({dur})\")
"
```

### 4. Get Build Details

```bash
# Specific build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/{BUILD_NUMBER}/api/json"

# Last build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastBuild/api/json"

# Last successful build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastSuccessfulBuild/api/json"

# Last failed build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastFailedBuild/api/json"
```

### 5. Get Console Logs

```bash
# Full console output
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/{BUILD_NUMBER}/consoleText"

# Last build logs (tail last 100 lines)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastBuild/consoleText" | tail -100

# Progressive log (for streaming/polling)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastBuild/progressiveText?start=0"
```

### 6. Trigger Build (No Parameters)

```bash
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
curl -s -X POST -u "$JENKINS_AUTH" -H "Jenkins-Crumb: $CRUMB" \
  "$JENKINS_URL/job/{JOB_NAME}/build"
# Returns HTTP 201 if queued successfully
```

### 7. Trigger Build with Parameters

```bash
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
curl -s -X POST -u "$JENKINS_AUTH" -H "Jenkins-Crumb: $CRUMB" \
  "$JENKINS_URL/job/{JOB_NAME}/buildWithParameters?PARAM1=value1&PARAM2=value2"
```

### 8. Get Job Parameters Definition

```bash
curl -s -u "$JENKINS_AUTH" \
  "$JENKINS_URL/job/{JOB_NAME}/api/json?tree=property[parameterDefinitions[name,type,defaultParameterValue[value],description]]" | \
  python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in d.get('property',[]):
    for pd in p.get('parameterDefinitions',[]):
        default=pd.get('defaultParameterValue',{}).get('value','')
        print(f\"  {pd['name']}: {pd.get('type','')} (default: {default})\")
"
```

### 9. Check Build Queue

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/queue/api/json" | \
  python3 -c "
import json,sys
q=json.load(sys.stdin)
items=q.get('items',[])
print(f'Queue: {len(items)} items')
for i in items:
    task=i.get('task',{}).get('name','?')
    why=i.get('why','')
    blocked=i.get('blocked',False)
    print(f\"  {task} — {'BLOCKED' if blocked else 'WAITING'}: {why}\")
"
```

### 10. Stop/Abort a Build

```bash
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
curl -s -X POST -u "$JENKINS_AUTH" -H "Jenkins-Crumb: $CRUMB" \
  "$JENKINS_URL/job/{JOB_NAME}/{BUILD_NUMBER}/stop"
```

### 11. Get Job Config (XML)

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/config.xml"
```

### 12. List Agents/Nodes

```bash
curl -s -u "$JENKINS_AUTH" \
  "$JENKINS_URL/computer/api/json?tree=computer[displayName,offline,idle,numExecutors]" | \
  python3 -c "
import json,sys
for c in json.load(sys.stdin)['computer']:
    status='OFFLINE' if c['offline'] else ('IDLE' if c.get('idle') else 'BUSY')
    print(f\"  {c['displayName']}: {status} (executors: {c.get('numExecutors','?')})\")
"
```

### 13. List Views

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/api/json?tree=views[name,url]" | \
  python3 -c "import json,sys; [print(v['name']) for v in json.load(sys.stdin)['views']]"
```

### 14. Jobs in a View

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/view/{VIEW_NAME}/api/json?tree=jobs[name,color]" | \
  python3 -c "import json,sys; [print(f\"{j['name']} ({j['color']})\") for j in json.load(sys.stdin)['jobs']]"
```

### 15. Jobs in a Folder

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{FOLDER_NAME}/api/json?tree=jobs[name,color]" | \
  python3 -c "import json,sys; [print(f\"{j['name']} ({j['color']})\") for j in json.load(sys.stdin)['jobs']]"
```

### 16. Nested Job (Job inside Folder)

```bash
# Access: /job/{FOLDER}/job/{JOB_NAME}/api/json
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{FOLDER}/job/{JOB_NAME}/api/json"
```

### 17. User Info

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/user/{USERNAME}/api/json"
```

---

## Common Workflows

### Deploy to Stage

```bash
# 1. Find the stage job
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/api/json?tree=jobs[name]" | python3 -c "import json,sys; [print(j['name']) for j in json.load(sys.stdin)['jobs'] if 'SERVICE-stage' in j['name'].lower()]"

# 2. Check last build status
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{SERVICE}-stage/lastBuild/api/json?tree=number,result,timestamp"

# 3. Trigger build
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; print(json.load(sys.stdin)['crumb'])")
curl -s -X POST -u "$JENKINS_AUTH" -H "Jenkins-Crumb: $CRUMB" "$JENKINS_URL/job/{SERVICE}-stage/build"

# 4. Monitor build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{SERVICE}-stage/lastBuild/api/json?tree=number,result,building"
```

### Investigate Build Failure

```bash
# 1. Get last failed build
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastFailedBuild/api/json?tree=number,timestamp"

# 2. Get console output (last 200 lines)
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastFailedBuild/consoleText" | tail -200

# 3. Get git changes that caused it
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/{JOB_NAME}/lastFailedBuild/api/json?tree=changeSets[items[author[fullName],msg,commitId]]"
```

### Check All Failing Jobs in a View

```bash
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/view/{VIEW_NAME}/api/json?tree=jobs[name,color]" | \
  python3 -c "import json,sys; [print(j['name']) for j in json.load(sys.stdin)['jobs'] if j.get('color','').startswith('red')]"
```

---

## Job Naming Conventions

Job names commonly follow a `{service}-{environment}` pattern, e.g. `payments-stage`, `payments-prod`. Confirm the actual naming convention for your Jenkins instance the first time you use this skill, and note it here for next time.

## Notes

- **Tree parameter**: Use `?tree=field1,field2[subfield]` to select specific fields and reduce response size
- **URL encoding**: `[` → `%5B`, `]` → `%5D` in query params
- **Build ranges**: Use `{start,end}` suffix on builds array, e.g. `builds[number]{0,5}` for first 5
- **Timeouts**: Add `--connect-timeout 10 --max-time 30` for reliability
- **Console logs can be large**: Always pipe through `tail -N` or `head -N`
