---
name: troubleshooter
description: Systematic troubleshooting skill for customer-reported bugs, production incidents, development issues, and infrastructure problems. Guides investigation through media analysis, user context lookup, log analysis, metrics review, and deployment history.
---

# Troubleshooter Skill

Systematic methodology for investigating and debugging issues across multiple categories: customer-reported bugs (with screenshots/videos), production incidents, development problems, and infrastructure issues.

**Before first use**, map the placeholder tool names below (`{{...}}`) to whatever's actually available in your environment — a logs platform, a metrics/observability platform, a code search tool, an incident management tool, a support-ticket tool, a product-analytics tool, a CI tool, etc. Once mapped, replace the placeholders in your working copy so the skill reads naturally for your stack.

## When to Invoke This Skill

Invoke this skill when:
- Customer reports a bug (via support ticket, chat, or direct report) with or without screenshots/videos
- Production service outage or performance degradation occurs
- Build failures or test failures need investigation
- Infrastructure issues (cloud resources, databases, containers) require debugging
- User explicitly asks to "troubleshoot", "debug", "investigate", or "help with an issue"

## Quick Reference: Investigation Checklist

**Phase 1**: Triage → Classify issue type → Analyze media (if available) → Gather context
**Phase 2**: User Context → Profile → Events → Transactions (customer bugs only)
**Phase 3**: Technical → Logs → Metrics → Code → Deployments (parallel when possible)
**Phase 4**: Historical → Similar issues → Active incidents
**Phase 5**: Root Cause → Synthesize → Hypothesize → Validate
**Phase 6**: Communicate → Summarize → Recommend → Document

---

## Tool Selection by Investigation Phase

### Phase 1: Triage & Context
- **Media**: image analysis, video analysis, document analysis, object-storage access
- **Tickets**: `{{support-ticket-tool}}` (e.g. Zendesk/Freshdesk MCP), team chat search
- **Team/service context, known issues, runbooks**: `kb` skill (`/kb search`)

### Phase 2: User Context (Customer Bugs)
- **Core**: `{{user-account-tool}}`, `{{product-analytics-tool}}` (e.g. Mixpanel/Amplitude), `{{feature-flag-tool}}`
- **Domain-specific**: if your product has multiple lines of business, keep a `references/README.md` listing domain-specific investigation tools per line of business — this skill's generic phases apply regardless

### Phase 3: Technical Investigation
- **Logs**: `{{logs-platform}}` (e.g. Loki, CloudWatch, Elasticsearch)
- **Metrics**: `{{metrics-platform}}` (e.g. Datadog, Prometheus/VictoriaMetrics)
- **Code**: `{{code-search-tool}}` (flow/service search, architecture docs, dependency graph)
- **Changes**: `{{ci-tool}}`, git history, `{{feature-flag-tool}}`

### Phase 4: Historical Context
- **Knowledgebase**: `kb` skill (`/kb search`) — past incidents, fixes, runbooks (check first)
- **Search**: team chat search, issue tracker (e.g. Jira), `{{code-search-tool}}` (doc search)
- **Incidents**: `{{incident-management-tool}}` (e.g. PagerDuty, Opsgenie, Zenduty), `{{metrics-platform}}`

---

## Core Investigation Methodology

### Phase 1: Issue Triage & Context Gathering

#### Step 1: Classify Issue Type

Determine the category:
- **Customer Bug**: User-reported issue, often with screenshots/videos, specific to a user or transaction
- **Production Incident**: Service outage, errors, performance degradation affecting multiple users
- **Development Issue**: Build failures, test failures, code bugs during development
- **Infrastructure Issue**: Cloud resources, databases, container clusters, networking problems

#### Step 2: Analyze Media FIRST (If Available)

When screenshots, videos, or documents are provided, **analyze media before asking questions**.

**Extract from Media**:
- ✓ Affected service/component (UI elements, screen names)
- ✓ Error symptoms (error messages, visual bugs)
- ✓ Timeframe (timestamps in media or metadata)
- ✓ User identifier (user ID, phone, email if visible)

**Media Types**:
- **Screenshots**: image analysis → Extract error messages, UI state, text from dialogs
- **Videos**: video analysis → Extract key frames, interaction flow, error sequence
- **Documents**: document analysis → Extract error details, logs, specifications
- **Support tickets**: `{{support-ticket-tool}}` → Fetch ticket, download attachments, extract descriptions
- **Chat/object storage**: team chat search or object-storage access → Download media, check message context

#### Step 3: Gather Remaining Context

Prompt for missing information only when media analysis cannot provide:
- **User Identifier**: User ID, phone number, or email (for customer bugs)
- **Timeframe**: When the issue occurred (exact time or time range)
- **Affected Service/Component**: Which service, API, or screen
- **Error Symptoms**: Visible symptom description

#### Step 3b: Consult the Work Knowledgebase (kb skill)

Before diving into logs/metrics, search the team knowledgebase for relevant context — it
often holds the answer faster than raw investigation. Invoke: `/kb search <service or symptom>`

Use it to pull:
- **Service ownership / SPOC** — who owns the affected service, escalation path
- **Known issues / past incidents** — has this exact symptom been seen before, and how was it fixed
- **Runbooks / architecture notes** — service dependencies, common failure modes, config quirks
- **Project context** — recent changes, ongoing migrations, feature flags

If the kb returns a known root cause or runbook, fold it into the investigation and verify it
against live signals (logs/metrics) rather than treating it as fact — kb entries can be stale.

---

### Phase 2: User & Transaction Context

**Skip this phase IF**:
- Issue is infrastructure-related (no user involved)
- Issue affects all users system-wide (not user-specific)
- Logs already reveal clear root cause

#### Step 4: Look Up User Profile

Use `{{user-account-tool}}` to retrieve account details:
- Account status, user segment, registration date
- Account-level flags or restrictions
- Recent activity summary

#### Step 5: Analyze User Behavior & Events

Use `{{product-analytics-tool}}` to search user events:
- Event tracking, funnels, user journey
- Focus on timeframe around the issue
- Identify unusual patterns, failed actions, incomplete flows
- Check feature flags and experiments with `{{feature-flag-tool}}`

#### Step 6: Review Transaction Details (If Applicable)

When the issue involves a transaction:
- Look up transaction/order history for the user
- Fetch detailed transaction information (payment state, order state)
- Identify failed steps or rollback operations

---

### Phase 3: Technical Investigation

**Parallelize Steps 7-10 when possible** to save time.

#### Step 7: Search Application Logs

Use `{{logs-platform}}` to query logs:
- Filter by user_id, phone number, or transaction ID
- Focus on timeframe ±30 minutes from issue occurrence
- Look for ERROR, WARN, or EXCEPTION level logs
- Identify stack traces, error codes, failure messages

**Tips**: Start with error logs → Look for correlation IDs → Check for timeouts, null pointers, validation failures

**Example**: `{service="payment-service"} |= "user_id=12345" |= "ERROR"`

#### Step 8: Review System Metrics

Use `{{metrics-platform}}` to check:
- Response times (latency spikes)
- Error rates (HTTP 5xx, 4xx)
- Request volumes (traffic spikes/drops)
- Resource utilization (CPU, memory, disk I/O)
- Database query performance

Compare metrics to baseline behavior.

#### Step 9: Understand Code & Architecture

Use `{{code-search-tool}}` to understand the system:
- Flow/service search → Find flows, services, APIs related to the issue
- Document search → Search architecture documentation
- Dependency graph → Understand service dependencies and data flow

#### Step 10: Check Recent Deployments & Changes

Investigate whether recent changes caused the issue:
- `{{ci-tool}}` → Check recent deployments to affected service
- Git history → Review recent PRs merged
- `{{feature-flag-tool}}` → Check feature flag updates
- Correlate deployment timing with issue occurrence

---

### Phase 4: Pattern Recognition & Historical Context

**Skip this phase IF**:
- Root cause is already validated
- Time-critical incident requiring immediate mitigation

#### Step 11: Search for Similar Historical Issues

Search communication and issue tracking:
- `kb (/kb search <symptom>)` → Search the work knowledgebase FIRST for past incidents, runbooks, and known fixes
- Team chat search → Search for similar bug reports
- Issue tracker (e.g. Jira) → Query for related bugs or incidents
- `{{code-search-tool}}` (document search) → Check documentation for known issues or workarounds
- Look for incident postmortems or root cause analyses

If you find a fix or root cause that's NOT yet in the kb, consider saving it with `/kb add` so the
next investigation is faster.

**Search Keywords**: Error messages, exception class names, affected features, user-visible symptoms

#### Step 12: Check for Active Incidents

Use `{{incident-management-tool}}` to check incident management:
- Active incidents and alerts
- Related monitoring notifications
- Whether multiple users are affected simultaneously
- Service health dashboards (`{{metrics-platform}}`)

---

### Phase 5: Root Cause Hypothesis & Validation

#### Step 13: Synthesize Findings

Correlate all gathered information:
- Logs, metrics, and user behavior timeline
- Sequence of events leading to failure
- Which component or service failed first
- Causation vs correlation

#### Step 14: Form Root Cause Hypothesis

Hypothesize based on evidence:
- **Code bug**: Logic error, null pointer, race condition
- **Configuration issue**: Wrong env var, missing config
- **Infrastructure issue**: Resource exhaustion, network failure
- **Dependency failure**: Third-party API down, database timeout
- **Data issue**: Invalid state, corrupted data

#### Step 15: Validate Hypothesis

Gather additional evidence:
- Look for supporting evidence in logs or metrics
- Check whether hypothesis explains all symptoms
- Identify counter-evidence that disproves hypothesis
- Refine hypothesis if needed

---

### Phase 6: Solution & Communication

#### Step 16: Summarize Investigation Results

Create clear summary:
- **Issue Description**: What happened and who was affected
- **Root Cause**: Why it happened (validated hypothesis)
- **Evidence**: Key logs, metrics, or code references
- **Timeline**: When issue started and key events
- **Impact**: Scope (single user, multiple users, all users)

#### Step 17: Provide Recommendations

Suggest next steps:
- **Immediate Fix**: Quick workaround or mitigation
- **Permanent Solution**: Code fix, configuration change, infrastructure update
- **Preventive Measures**: Monitoring, alerts, tests to prevent recurrence
- **Escalation**: Identify who to involve for further expertise

#### Step 18: Document Findings (If Significant)

- Create or update documentation with findings
- Add to known issues list if not immediately fixable
- Update runbooks with troubleshooting steps
- Share lessons learned with the team

---

## Adaptive Investigation Workflow

**All Issues Start Here**:
1. Classify Issue Type → 2. Analyze Media (if available) → 3. Gather Context

**Then Branch by Issue Type**:

**Customer Bug**: → Phase 2 (User Context) → Phase 3 (Technical: Logs + Metrics + Code in parallel) → Phase 4 (Historical) → Phase 5 (Root Cause) → Phase 6 (Communicate)

**Production Incident**: → Check Active Incidents → Phase 3 (Metrics → Logs → Deployments in parallel) → Phase 5 (Root Cause) → Phase 6 (Mitigation)

**Development Issue**: → Phase 3 (Build/Test Logs → Code Changes → Code Analysis) → Phase 5 (Root Cause) → Phase 6 (Fix)

**Infrastructure Issue**: → Phase 3 (Resource Health → Metrics → Configuration → Changes) → Phase 5 (Root Cause) → Phase 6 (Fix)

---

## When to Use Sequential Thinking

Invoke a sequential/step-by-step reasoning tool when:
- Root cause unclear after completing investigation phases
- Multiple conflicting pieces of evidence need reconciliation
- Complex dependency chains require multi-step reasoning
- Hypothesis validation requires exploring multiple scenarios

Do NOT use for:
- Straightforward issues with clear evidence
- Time-critical incidents requiring immediate action

---

## When Investigation Stalls (Error Handling)

### Media Analysis Fails
- **Fallback**: Ask user directly for context (user ID, timeframe, service)
- Check if media is corrupted or unsupported format
- Try alternative analysis approach (e.g., manual inspection if OCR fails)

### User Lookup Returns Nothing
- Verify identifier format (user_id vs phone vs email)
- Check if user is in different environment (staging vs prod)
- Expand search to include archived or deleted accounts

### No Logs Found
- Expand timeframe (±2 hours instead of ±30 minutes)
- Check if service logs to different system or has different name
- Verify log retention period hasn't expired
- Use `{{code-search-tool}}` to find correct service name

### Metrics Show No Anomaly
- Check if metrics are delayed or still processing
- Verify metric query syntax and service name
- Look at wider timeframe for intermittent issues
- Check if issue is isolated to specific users (not visible in aggregates)

### Contradictory Evidence
- Reconcile conflicting data with careful step-by-step reasoning
- Consider timing differences (logs vs metrics timestamps)
- Check if multiple issues occurred simultaneously
- Validate data source accuracy

### Root Cause Still Unclear
- Document what has been ruled out
- Escalate to domain experts
- Create detailed timeline of all findings
- Use step-by-step reasoning for complex cases

---

## Key Principles

### Be Systematic
Follow investigation phases in order. Document findings at each step.

### Be Evidence-Based
Support conclusions with logs, metrics, or code references. Avoid speculation. Distinguish hypothesis from validated root cause.

### Be Efficient
Parallelize investigation when possible (check logs AND metrics simultaneously). Start with high-signal data sources. Escalate early if expertise is needed.

### Be User-Focused
Prioritize user impact assessment. Provide clear communication suitable for technical and non-technical audiences. Suggest workarounds for affected users.

---

## Common Pitfalls to Avoid

❌ **Jumping to Conclusions**: Do not assume root cause without evidence
❌ **Ignoring Timeline**: Always correlate findings with issue timeframe
❌ **Missing User Context**: For customer bugs, always look up user details
❌ **Skipping Metrics**: Logs alone do not show performance degradation
❌ **Forgetting Deployments**: Recent changes are often the culprit
❌ **Not Checking Similar Issues**: Save time by learning from past incidents
❌ **Serial Investigation**: Parallelize logs, metrics, code checks when possible

---

## Example Investigation Flow

**Scenario**: Customer reports "Payment failed" with screenshot showing error dialog.

1. **Classify**: Customer bug, payment flow
2. **Analyze Screenshot** (image analysis):
   - Error: "Transaction timeout"
   - Screen: Payment confirmation (from UI)
   - Timestamp: 14:30 local time
   - User ID visible: "12345"
3. **Context**: All extracted from media - no prompting needed
4. **User Profile** (`{{user-account-tool}}`): Active account, no restrictions
5. **User Events** (`{{product-analytics-tool}}`): Reached gateway, initiated payment, no completion
6. **Transaction History**: 3 failed attempts with same timeout
7. **Logs** (`{{logs-platform}}`): Timeout exception from gateway after 30s
8. **Metrics** (`{{metrics-platform}}`): Latency spike to 35s at 14:30 (normal: 2-3s)
9. **Deployments** (`{{ci-tool}}`): No recent deployments
10. **Infrastructure**: Third-party gateway shows degraded performance 14:25-14:45
11. **Root Cause**: Third-party payment gateway performance issues
12. **Recommendation**: Monitor gateway, implement retry logic with exponential backoff, add circuit breaker

**Key Takeaway**: Media analysis extracted user ID, timeframe, service, and error automatically.

---

## Realistic Example: Production Incident with Complications

**Scenario**: API latency spike reported by monitoring alert at 10:30 AM.

1. **Classify**: Production incident, API performance
2. **Active Incidents** (`{{incident-management-tool}}`): No active incidents
3. **Metrics** (`{{metrics-platform}}`): Latency spike starting 10:15 AM on checkout API
4. **Logs** (`{{logs-platform}}`): Query for "checkout-service" returns empty results
   - **Recovery**: Search `{{code-search-tool}}` for correct service name → Find "checkout-processor-v2"
   - **Retry**: Logs now show database timeout errors
5. **Code** (`{{code-search-tool}}` flow search): Find recent PR for DB query optimization
6. **Deployments** (`{{ci-tool}}`): Deployment at 10:00 AM (timing correlates!)
7. **Git**: Review PR diff → Optimized query missing index
8. **Root Cause**: New query optimization missing database index causing full table scans
9. **Immediate Fix**: Rollback deployment
10. **Permanent Solution**: Add missing index, redeploy
11. **Prevention**: Add database query performance tests to CI/CD

**Key Takeaway**: Investigation hit dead end (wrong service name), recovered by checking the code search tool, found root cause in recent deployment.
