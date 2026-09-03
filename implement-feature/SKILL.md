---
name: implement-feature
description: Use when executing a large feature implementation from a spec or design doc. Covers phased step-by-step coding with test gates, design change handling, doc sync, and progress tracking. Use when user says "implement this", "start coding", "build this feature", or references an implementation plan with steps.
---

# Implementation Execution Workflow

## Overview

End-to-end workflow for implementing large features with Claude Code: break a spec into phased steps, code each step with test gates, handle design changes mid-flight, keep docs/Confluence in sync, and track progress across conversations.

## When to Use

- Feature requires 5+ new files across multiple layers (facade, entity, manager, consumer)
- Implementation plan exists with steps/checkpoints
- External service integration (placeholders → real later)
- Multiple conversations expected (progress must persist)
- User says "implement this", "start step X", "build this feature"

## When NOT to Use

- Single file changes, bug fixes, config tweaks → just do it
- Design/spec creation → use `tech-design-doc` skill instead
- Pure refactoring with no new behavior → no phased approach needed

---

## Phase 1: Understand Before Coding

**Never code without reading existing patterns first.**

Before the first step, explore:

```
1. Existing facades → how do they extend BaseFacade? What's the header/retry pattern?
2. Existing entities → what does BaseEntity provide? Annotations? Audit fields?
3. Existing DAOs → JpaRepository? Custom queries? What naming convention?
4. Existing managers → interface + impl pattern? What managers do status updates?
5. Existing consumers → @SqsListener pattern? ON_SUCCESS deletion? JobAttributes wrapper?
6. Existing WFEntries → what does BaseWorkflowEntry provide? What's inherited?
7. Build system → module names (settings.gradle), Java version, test framework
8. Properties → naming convention for baseurl/apptoken, queue names
9. SSM/deployment config → where are env vars defined? (codepipeline/configs/common.yaml)
```

**Output:** Mental model of conventions. Quote exact file paths and patterns.

---

## Phase 2: Break Into Phased Steps

**Order matters. Dependencies flow downward. Each phase is independently testable.**

```
Phase 1: EXTERNAL FACADES
  Why first: No domain dependency. Only need DTOs + config. Testable with mocked RestTemplate.
  Pattern: Extend BaseFacade, @Retryable, @CircuitBreaker, @Trace
  
Phase 2: DOMAIN FOUNDATION
  Enums → DB migration (Flyway) → Entities + DAOs → DTOs + WFEntry
  Why this order: Enums first (referenced everywhere), DB before entities, DTOs last (need enums)
  
Phase 3: BUSINESS LOGIC
  Managers (schedule, process, handle) → SQS consumers
  Pattern: Interface + Impl. Use existing managers for status updates, events.
  
Phase 4: ORCHESTRATION
  SFN JSON → Workflow consumers → Event consumers → Partner consumers
  
Phase 5: ROUTING + APIs
  Feature flag routing → REST endpoints → Config seeding
  
Phase 6: TESTING
  SLTs → SFN path testing
  
Phase 7: REAL INTEGRATION
  Replace placeholders with real HTTP calls
```

### Step Structure

Each step must have:

```
## Step N: [Name]

**What:** One sentence
**Files:** List of files to create/modify
**Depends on:** Previous step numbers
**Gate:** What must pass before moving to next step

[YOU] tag if human action needed (AWS, staging, DB, team coordination)
```

---

## Phase 3: Execute Step-by-Step

### Per-Step Execution Pattern

```
1. Read existing similar code (find the pattern to follow)
2. Write the code (match conventions exactly)
3. Compile: ./gradlew :module:compileJava
4. Plan tests using GWT method (see Test Planning below)
5. Write tests per the plan
6. Run new tests: ./gradlew :module:test --tests "path.to.NewTest"
7. Run ALL tests: ./gradlew :module:test (verify no regression)
8. Mark step done
```

### Test Planning (GWT Method)

**Don't just "write some tests." Systematically plan test cases per method before writing any test code.**

For each public method in new/modified classes:

**Step 1: Branch Analysis** — List every decision point in the method:
```
- if/else branches
- null checks (Objects.isNull, isEmpty, isBlank)
- switch cases + default
- try/catch blocks (what exceptions can be thrown?)
- early returns (guard clauses)
- loop boundaries (empty list, single item, multiple items)
- external service responses (success, failure, null, timeout)
```

**Step 2: GWT Plan** — Write Given/When/Then for each branch:
```
Method: schedule(ScheduleRequest request)

Tier A (critical path — always test):
  1. Given: no existing scheduled job
     When: schedule() called
     Then: new DB row created, external scheduler called, ID returned

  2. Given: existing SCHEDULED job for same entity+type
     When: schedule() called
     Then: old job invalidated, new job created

Tier B (error/edge cases — test unless trivial):
  3. Given: external scheduler returns null (idempotent 409)
     When: schedule() called
     Then: fallback ID used, no exception

  4. Given: external scheduler throws exception
     When: schedule() called
     Then: exception propagates, DB row NOT committed (@Transactional rollback)

Tier C (trivial — skip):
  5. Given: request has all fields populated
     When: schedule() called
     Then: all fields mapped correctly to entity
     [SKIP — covered implicitly by Tier A tests]
```

**Step 3: Tier Selection**
```
Tier A: Critical path + happy path — ALWAYS write these
Tier B: Error handling, edge cases, boundary conditions — ALWAYS write these
Tier C: Simple field mapping, trivial getters, obvious delegation — SKIP
```

**Step 4: Write Tests** — One test method per GWT case. Use `should{Expected}When{Condition}` naming:
```java
@Test void shouldCreateNewJobWhenNoExistingScheduled() { ... }
@Test void shouldInvalidateOldJobWhenExistingScheduled() { ... }
@Test void shouldUseFallbackIdWhenSchedulerReturnsNull() { ... }
@Test void shouldPropagateExceptionWhenSchedulerFails() { ... }
```

**Step 5: Assertion Quality Check** — After writing, verify:
```
- [ ] No test uses only assertTrue(true) or assertNotNull(result)
- [ ] Every test has at least one specific field assertion (assertEquals, containsEntry, etc.)
- [ ] Side effects verified with verify() — not just return values
- [ ] Exception tests use assertThatThrownBy with .isInstanceOf AND .hasMessage/matches
- [ ] Mock setup is minimal — only mock what this test needs, not everything
```

### When to Apply Full GWT vs Quick Tests

```
Full GWT (all 5 steps):
  - Manager methods with business logic (3+ branches)
  - Consumer methods with validation + external calls
  - Facade methods with error handling

Quick tests (just happy path + one error):
  - Simple delegation methods (manager.notifyLob → calls notificationManager)
  - DTO builders, enum mappings
  - Config beans
```

### Convention Checklist

```
- [ ] Objects.nonNull() instead of != null
- [ ] @Slf4j, @Service/@Component, @FieldDefaults(level = AccessLevel.PRIVATE)
- [ ] @Autowired field injection (follow existing codebase, even if constructor injection is "better")
- [ ] PropertyNamingStrategy.SnakeCaseStrategy (not PropertyNamingStrategies)
- [ ] @JsonIgnoreProperties(ignoreUnknown = true) on all DTOs
- [ ] @Builder(toBuilder = true) on DTOs
- [ ] Javadocs on interface methods (plain text, no HTML tags)
- [ ] @Trace on facade methods (Datadog)
- [ ] @Retryable on facade methods that call external services
- [ ] Test class naming: {ClassName}Test with @ExtendWith(MockitoExtension.class)
- [ ] Test methods: should{Expected}When{Condition}
```

---

## Phase 4: Handle Design Changes

**Design changes WILL happen mid-implementation. Handle them systematically.**

When a requirement changes:

```
1. STOP coding
2. Discuss the change — understand impact
3. Update CODE first (DTOs, facades, managers — whatever is affected)
4. Compile + test to verify code change works
5. Launch 3 PARALLEL agents to update docs:
   - Agent 1: Spec (SPEC.md)
   - Agent 2: Implementation Plan (IMPLEMENTATION_PLAN.md)
   - Agent 3: Steps (STEPS.md)
6. Wait for all agents to complete
7. Update Confluence (if accessible)
8. Verify consistency: grep for stale references across all docs
9. Resume coding
```

### Common Design Changes and Their Blast Radius

| Change | Code Impact | Doc Impact |
|--------|------------|------------|
| External service owns ZIP/processing | Remove facade method + DTOs | Spec flow, impl plan pseudocode, steps description |
| Assets dynamic from partner (not static table) | WFEntry simplified, preEnrichment flow | Spec, config seeding SQL, data model section |
| New comm type / rename | Enum change | Spec comms section, impl plan comms section |
| Remove a queue | DAO query, consumer, properties | Queue provisioning list, queue count everywhere |
| Change invalidation strategy | Manager logic, DAO queries, migration | Spec comms design, handleFired pseudocode |

---

## Phase 5: Track Progress

**Save progress after every checkpoint. Survives compaction.**

### Memory File Template

```markdown
---
name: {Feature} Implementation Progress
description: Tracks steps done, files created, design decisions made.
type: project
---

## Progress (as of {date})
### Completed: Steps X, Y, Z
### Remaining: Steps A, B, C

### Files Created/Modified
- path/to/File.java — NEW/MODIFIED (description)

### Design Decisions
1. Decision — Why — Impact

### Build Status
- Java version needed
- Test count + all green
- Any known issues
```

Update MEMORY.md index with a pointer to this file.

---

## Phase 6: Periodic Review Cycles

**Don't wait until the end to review. Review at checkpoints to catch compounding issues early.**

### When to Trigger a Review

```
- Every 5 steps completed (or at a natural phase boundary)
- After a design change that touched 3+ files
- Before starting a new phase (e.g., moving from facades → managers)
- When the user explicitly asks for review
- Before the final integration/SLT step
```

### Review Scope

Each review should cover ALL code written since the last review (or all code if first review):

```
P0 (Critical):  Logic bugs, missing DB persists, data loss, security issues
P1 (High):      Missing error handling, wrong status transitions, test gaps on critical paths
P2 (Medium):    Inconsistencies, missing edge case tests, config issues, deprecated APIs
P3 (Low):       Style, naming, minor improvements
```

### Review Checklist

```
- [ ] Every DB write that changes state is actually persisted (not just in-memory)
- [ ] DB constraints won't fail under normal lifecycle (unique keys, foreign keys)
- [ ] SFN input/output variable names match what code produces
- [ ] All SFN queue references have matching consumers
- [ ] All consumers use consistent timezone (ZoneOffset.UTC)
- [ ] @Transactional on methods with multiple DB operations
- [ ] String constants match between SFN JSON, consumers, and managers
- [ ] Config properties in application.properties have SSM keys in common.yaml
- [ ] All new facade methods have tests (success, error, edge cases)
- [ ] All new manager methods have tests (happy path, rejection, boundary)
- [ ] No orphaned code (unused DAO methods, dead imports)
- [ ] Placeholder methods are tracked in remaining steps
- [ ] Workflow ResultPath on wait states uses scoped path (not "$") when consumer sends partial data
- [ ] Trace data end-to-end across workflow state boundaries — verify every $.field reference resolves
```

### Review Output Format

Organize findings by severity (P0-P3). For each finding:
- File + line number
- What's wrong
- Suggested fix
- Impact if unfixed

### Post-Review Action

```
1. Fix all P0 immediately — these are production blockers
2. Fix P1 before moving to next phase — these cause subtle bugs
3. Log P2/P3 as tasks — fix during cleanup or next session
4. Re-run ALL tests after fixes
5. Save updated progress to memory
```

---

## Patterns Catalog

### Facade (External Service Client)

```java
@Slf4j
@Component
@Validated
public class ServiceFacade extends BaseFacade {

    @Value("${service.baseurl}")
    private String baseUrl;

    @Trace
    @Retryable(value = { ManagerException.class }, backoff = @Backoff(delay = 100, multiplier = 1.5))
    @CircuitBreaker(name = "circuitBreakerServiceName")
    public ResponseType methodName(RequestType request) {
        try {
            ResponseEntity<ResponseType> response = restTemplate.exchange(
                constructUri(baseUrl + PATH, null),
                HttpMethod.POST,
                getEntityWithBodyAndHeaders(constructHeaders(), request),
                ResponseType.class
            );
            if (Objects.isNull(response.getBody())) {
                throw invalid_response.getBuilder("Facade", "method", "null").build();
            }
            return response.getBody();
        } catch (HttpClientErrorException e) {
            // Handle specific status codes (409 = idempotent, etc.)
        } catch (RestClientException e) {
            throw web_client_call_failed.getBuilder("Facade", "method").build();
        }
    }
}
```

### Entity

```java
@Data @Entity @SuperBuilder @AllArgsConstructor @NoArgsConstructor
@Table(name = "table_name")
@EqualsAndHashCode(callSuper = true)
@Audited @AuditOverride(forClass = BaseEntity.class)  // if audit needed
@DynamicUpdate
@FieldDefaults(level = AccessLevel.PRIVATE)
public class MyEntity extends BaseEntity {
    // BaseEntity provides: id, createdAt, createdBy, updatedAt, lastModifiedBy, version
    
    @NotBlank String someField;
    
    @NotNull @Enumerated(value = EnumType.STRING)
    SomeEnum enumField;
    
    @Convert(converter = HashMapConverter.class) @Column(columnDefinition = "json")
    LinkedHashMap<String, Object> jsonField;
    
    @Builder.Default Boolean isActive = true;
}
```

### DAO

```java
@Validated @Repository
public interface MyDAO extends BaseDAO<MyEntity, Long> {
    // Spring Data derived queries
    Optional<MyEntity> findByFieldAndIsActiveTrue(String field);
    List<MyEntity> findByFieldAndStatus(String field, StatusEnum status);
}
```

### Manager (Interface + Impl)

```java
// Interface
@Validated
public interface IMyManager {
    /** Javadoc — plain text, use {@link} for cross-references */
    ResultEntry doSomething(@NotNull @Valid InputEntry input);
}

// Implementation
@Service @Slf4j @FieldDefaults(level = AccessLevel.PRIVATE)
public class MyManager implements IMyManager {
    @Autowired SomeDAO dao;
    @Autowired SomeFacade facade;
    
    @Override
    public ResultEntry doSomething(InputEntry input) { ... }
}
```

### SQS Consumer

```java
@Slf4j @Service @Validated
@FieldDefaults(level = AccessLevel.PRIVATE)
public class MyConsumer {
    @Autowired IMyManager manager;

    @Trace
    @SqsListener(value = "${queues.my-queue}", deletionPolicy = ON_SUCCESS)
    public void handleEvent(@Payload JobAttributes<PayloadType> jobAttributes) {
        manager.process(jobAttributes.getJsonObject());
    }
}
```

### Test

```java
@ExtendWith(MockitoExtension.class)
class MyManagerTest {
    @Mock SomeDAO dao;
    @Mock SomeFacade facade;
    @InjectMocks MyManager manager;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(manager, "configValue", "test");
    }

    @Nested
    class MethodName {
        @Test
        void shouldDoExpectedWhenCondition() {
            when(dao.findById(1L)).thenReturn(Optional.of(entity));
            Result result = manager.method(input);
            assertThat(result.getField()).isEqualTo("expected");
            verify(facade).externalCall(any());
        }
    }
}
```

---

## Placeholder Strategy

For external services not yet built:

```java
// PLACEHOLDER — returns mock until {service} builds {endpoint}
@Trace
public ResponseType method(RequestType request) {
    log.warn("PLACEHOLDER: method called for id={}", request.getId());
    ResponseType response = new ResponseType();
    response.setSuccess(true);
    response.setData(DataType.builder().field("placeholder").build());
    return response;
}
```

Track placeholders in the steps doc. Step N (future) swaps them for real HTTP calls.

---

## [YOU] Tags

Mark steps requiring human action:

```
**[YOU] BEFORE THIS PHASE:** Infra must provision 12 SQS queues + 12 DLQs in dev.

Step 14: SFN JSON — **[YOU] Create state machine in AWS from this JSON. Note the ARN.**

Step 20: Config Seeding — **[YOU] Run seed SQL against dev DB.**
```

Collect all [YOU] items in a summary table at the top of the steps doc.

---

## Phase 7: Production Deployment Plan

**Before the feature is "done", create a deployment runbook.**

Large features touch multiple services, infra, and config. A deployment plan prevents "we forgot to create the queues" in prod. Generate it as a `PRODUCTION_DEPLOYMENT_STEPS.md` in the repo's `docs/` folder.

### What to Include

```
1. Deployment Order — which service goes first? (usually: infra → downstream → upstream)
2. Infra Provisioning — queues, topics, state machines, buckets, with exact names + settings
3. IAM/Permissions — which role needs what access on which resource
4. Config/SSM Parameters — every env var, with expected values
5. DB Migrations — auto (Flyway) vs manual seed SQL, with exact statements
6. Per-Service Deploy — what to deploy, what to verify post-deploy, risk to existing flows
7. Smoke Test — verify existing flows still work BEFORE enabling new feature
8. Feature Enable — flip the config/flag that activates the new flow
9. E2E Test — full new flow test with verification at each step
10. Monitoring — what to watch, for how long, what dashboards
11. Rollback Plan — how to disable without redeploy, how to clean up stuck state
```

### Key Principles

```
- Deploy infra BEFORE code — queues/SFN must exist before consumers start listening
- Deploy downstream BEFORE upstream — dependent services must be ready before the caller sends traffic
- Start with feature DISABLED — seed config as inactive, enable after smoke test
- Rollback = config disable, not redeploy — if V2 is broken, flip is_active=0, V1 continues
- Additive changes don't need rollback — new endpoints, new consumers, new queues are safe
```

### Deployment Checklist Template

```
- [ ] Infra: All queues/DLQs created
- [ ] Infra: State machine created, ARN noted
- [ ] Infra: IAM roles updated for all services
- [ ] Config: SSM parameters set
- [ ] DB: Seed data inserted (feature INACTIVE)
- [ ] Deploy: Downstream services deployed + verified
- [ ] Deploy: Upstream service deployed + migration verified
- [ ] Smoke: Existing flows still work
- [ ] Enable: Feature config activated
- [ ] Test: New flow end-to-end passes
- [ ] Monitor: Watch period complete, DLQs empty, no errors
- [ ] Alerts: All alerts configured and verified
```

### Alerts & Monitoring Checklist

Include an alerts section in the deployment plan. Cover all 4 layers:

```
1. INFRA ALERTS (DLQs, queue depth)
   - Every DLQ should alert on messages > 0 (something failed max retries)
   - Main queue depth alert if messages pile up (consumer may be down)
   - Severity: P1 for critical path queues, P3 for comms/notification queues

2. WORKFLOW ALERTS (SFN / orchestrator)
   - Execution failed, timed out, throttled
   - Executions stuck (running > expected max duration)

3. APPLICATION ALERTS (service metrics)
   - Error rate on new endpoints
   - Latency spikes on external service calls
   - Specific log patterns for known failure modes ("no task token", "handleTerminal failed")

4. BUSINESS ALERTS (domain-level health)
   - Entities stuck in non-terminal state beyond expected duration
   - Scheduled jobs in FAILED status
   - Cap/limit reached events (informational)
```

Also create a **dashboard** with: throughput, workflow health, external service latency, queue/DLQ depths, and business metrics.

---

## Quick Reference: Build Commands

```bash
# Compile single module
JAVA_HOME=/path/to/jdk17 ./gradlew :module-name:compileJava

# Run specific test
./gradlew :module-name:test --tests "package.ClassName"

# Run all tests
./gradlew :module-name:test

# Publish to local Maven (for shared libs)
cd /path/to/lib && ./gradlew publishToMavenLocal
```

## Code Quality Standards

### Javadocs

Write javadocs on **all public interfaces and their methods**. Follow these rules:

```
- Plain text only — NO HTML tags (<p>, <br>, <ul>, etc.)
- Use {@link ClassName} for cross-references
- Use {@code value} for inline code
- First sentence = one-line summary (shows in IDE hover)
- @param and @return only when non-obvious
- Document business intent, not mechanical description
```

**Good:**
```java
/**
 * Schedule a job to execute at a future time. If a SCHEDULED job already
 * exists for the same entity+type, it is invalidated before the new one
 * is created (eager dedup).
 *
 * @param request contains entityId, jobType, scheduledAt
 * @return the created entry with external job ID populated
 * @see #reschedule for updating an existing job's time
 */
JobEntry schedule(@NotNull @Valid ScheduleRequest request);
```

**Bad:**
```java
/** <p>This method schedules a job.</p> */  // HTML tags
/** Calls the schedule method. */           // mechanical, useless
```

**Where to write javadocs:**
- Interface methods (always — this is the contract)
- Complex private methods (only if logic is non-obvious)
- Enums with non-obvious values
- NOT on simple getters/setters, NOT on test methods

### Design Patterns & Practices

Apply these patterns when they fit the problem — don't force them:

**Factory Pattern (static registration)**
```
Use when: Multiple implementations selected at runtime by a composite key (e.g., type + category → handler)
Pattern: Static Map<String, Class<? extends Handler>> + register() in static block + getInstance(context, key)
Why: Open for extension (new handler = new class + register call), closed for modification (factory untouched)
```

**Interface + Impl Separation**
```
Use when: Business logic that may have multiple implementations or needs mockability
Pattern: IManager (interface with javadocs + validation annotations) → ManagerImpl (impl with @Service)
Why: Enables @Mock injection in tests, clear contract definition, swappable implementations
```

**Eager + Lazy Invalidation**
```
Use when: Scheduled events/jobs that may become stale before delivery
Eager: Invalidate on known lifecycle events (reschedule, status change, cancellation)
Lazy: Check preconditions at delivery time (entity still active? cooloff period? newer version exists?)
Why: Eager catches the common case; lazy is the safety net for races and edge cases
```

**Universal Enums at Service Boundaries**
```
Use when: Multiple partners/providers with different wire formats
Pattern: Define universal enums in a shared core lib. Each adapter maps to/from partner-specific formats.
         The consuming service only ever sees the enum, never partner-specific strings.
Why: New partner = new adapter code only, zero changes in the consumer
DB-backed: Store the mapping in a DB table (source_value, provider, target_value) with cached reverse lookup.
         New values = DB row insert, not code change.
```

**Workflow Error Code Contract**
```
Use when: Workflow catch/retry blocks route based on error type (e.g., SFN Catch, SQS DLQ routing)
Pattern: Send failure with an explicit error string that exactly matches the workflow's catch clause.
         Never rely on generic error codes (like "process_failed") when the workflow expects a specific one.
Why: Mismatch = workflow catches it as generic failure instead of routing to the correct handler
```

**Workflow ResultPath: Never Use "$" on Wait States**
```
Use when: Workflow has "wait" states where external consumers call respondSuccess with partial data
Pattern: Use a scoped ResultPath (e.g., "$.user_action_result") so the response MERGES into existing state
         instead of REPLACING it. Only use ResultPath "$" on Task states where the consumer returns the
         FULL state object (all fields needed by downstream states).
Why: ResultPath "$" replaces the ENTIRE workflow state with whatever respondSuccess sends. If the external
     consumer sends {partner_decision: "ACCEPTED"}, all other state fields (inspection_details, workflow_id,
     app_form, etc.) are permanently lost. Downstream states that reference $.inspection_details_entry will
     fail with a runtime path resolution error.
Rule of thumb:
  - Task states (consumer returns full WFEntry): ResultPath "$" is safe
  - Wait states (external event sends partial data): ResultPath "$.scoped_key" is required
```

**Separate Consumers for Separate Flows**
```
Use when: Building a new version (V2) of an existing flow in the same service
Pattern: New consumer class + new queue. NEVER modify existing V1 consumer.
Why: Zero V1 blast radius. Independent deployability. Clear ownership.
```

**DB-Backed Config Over Hardcoded Maps**
```
Use when: Mapping values that may change per-partner or grow over time (IDs, labels, locations)
Pattern: DB table + cached lookup (with TTL or startup-load). Reverse lookup built from same table.
Why: New entry = DB row insert, not code deployment. Works for N partners without N switch statements.
```

### Terminal State Handling

When closing/deactivating an entity:
```
1. ALWAYS persist isActive=false to DB — not just set it in-memory
2. Use a method that persists + creates an audit event in one transaction
3. Invalidate all scheduled jobs/timers/comms for the entity
4. Cancel external scheduled jobs — best-effort, don't fail if already expired
5. Verify with a test that asserts the DB write happened (mock verify on update/save)
```

### Timezone Consistency

```
- Pick one timezone convention (usually UTC) and use it everywhere
- ALWAYS use LocalDateTime.now(ZoneOffset.UTC) — never bare LocalDateTime.now()
- This applies to: timestamps, cooloff checks, scheduled times, invalidation times
- Inconsistency causes silent drift (e.g., 5.5h in IST environments)
```

---

## Phase 8: Review Artifacts

**After implementation is complete and tests pass, generate three review documents in `docs/`.** These make the work reviewable by humans and catch issues before production.

### 8.1 — `docs/fixes.md` (Bug Tracker)

**Purpose:** Living document tracking all bugs found during development and review. Updated continuously as bugs are found and fixed.

**When to create:** After the first review cycle (Phase 6) finds bugs. Update after every subsequent fix.

**Structure:**

```markdown
# {Feature} — Bug Fixes

All bugs found during end-to-end flow review.

## VALIDATED AND FIXED

| ID | Original Issue | Status |
|---|---|---|
| ~~H1~~ | Description of the bug | **FIXED** — how it was fixed, file:line |

## OPEN BUGS

### HIGH — Blocks testing/production

### H{N}. {Title}
**File:** `path/to/File.java:line`
**Fix:** Concrete fix description

### MEDIUM — Could cause issues

### LOW — Minor improvements

## Summary

| Severity | ID | Issue | Status |
|---|---|---|---|
| ~~HIGH~~ | ~~H1~~ | ~~description~~ | **FIXED** |
| LOW | L1 | description | OPEN |
```

**Key rules:**
- Bugs get IDs: H1-Hn (HIGH), M1-Mn (MEDIUM), L1-Ln (LOW)
- Fixed bugs stay in the doc (strikethrough) — they're audit trail
- Each bug has exact file:line reference
- Summary table at the bottom for quick scanning
- Include the review pass number ("Fifth review — Full codebase audit results")

### 8.2 — `docs/testing_strategy.md` (Stage/E2E Test Plan)

**Purpose:** Step-by-step guide for manually testing the feature on stage. Someone unfamiliar with the code should be able to follow this and verify the feature works.

**When to create:** After all HIGH/MEDIUM bugs are fixed, before stage testing begins.

**Structure:**

```markdown
# {Feature} — Stage Testing Strategy

## Prerequisites
- [ ] Blocker bugs fixed (reference fixes.md IDs)
- [ ] Infra verified (queues, SFN, DB migration)
- [ ] Config seeded (DB rows, SSM params)
- [ ] Upstream services deployed

## P1. Infra Verification
  List every queue, SFN, table with verification commands (AWS CLI, SQL)

## Test Scenarios

### T1. Happy Path — Full lifecycle
  Step-by-step: trigger → each state → terminal
  At each step: what to check (DB state, SQS messages, SFN console, logs)
  Expected outcome

### T2. Lapse/Timeout Path
  How to trigger: wait for timeout or manually fire the scheduler
  Expected: SFN catches → terminal handler → status LAPSED

### T3. Cancellation Path
  How to trigger: call cancel endpoint
  Expected: SFN catches → terminal handler → status CANCELLED

### T4. Reinspection Loop
  How to trigger: partner sends REINSPECTION
  Expected: document processing service reset → new upload cycle → resubmit

### T5. Edge Cases
  What if SFN is between states when lapse fires?
  What if partner sends decision for V1 inspection?
  What if documents are empty?

## Verification Queries
  SQL queries to check DB state at each stage
  AWS CLI commands to check SFN execution state
  Log patterns to grep for success/failure
```

**Key rules:**
- Prerequisites section references fixes.md bug IDs
- Each test scenario has: trigger method, step-by-step verification, expected outcome
- Include actual AWS CLI commands, SQL queries, curl commands
- Cover happy path, error paths, edge cases, and integration boundaries
- Include rollback verification (disable feature, verify V1 still works)

### 8.3 — `docs/manual_review.md` (Code Review Guide)

**Purpose:** Comprehensive walkthrough of all V2 code for a reviewer who hasn't seen it before. Follows the data flow end-to-end with exact file links, line numbers, code snippets, and verification checklists.

**When to create:** After implementation is complete and all tests pass. Before PR review.

**Structure:**

```markdown
# {Feature} — Manual Code Review Guide

**Branch:** `feature/TICKET-ID-name`
**Base:** `master`
**Total diff:** ~N insertions across M files

## File Index (click to open)
  Clickable relative links to every file, grouped by layer:
  - SFN definitions
  - Domain model (entries, enums)
  - Core business logic (managers)
  - SQS consumers
  - Controllers
  - External facades
  - DB migration + entity + DAO

## Architecture Overview
  ASCII diagram of the full flow

## Phase 1: {Orchestration layer}
  ### Step 1.1 — {File}
  **File:** [FileName.java](../relative/path/to/File.java)
  State-by-state or method-by-method walkthrough
  Tables with line numbers, field names, what to verify
  - [ ] Checkbox items for each verification point
  Items marked **VERIFY** (correctness-critical) or **QUESTION** (design decision)

## Phase 2-N: {Each layer in flow order}
  Same pattern: file link → code snippets → line-by-line tables → checklists

## Quick Reference
  File → Flow Position map (clickable links)
  Status transition diagram (ASCII)

## Known Open Items
  | ID | Severity | Issue | File:Line | Recommendation |

## Review Questions to Resolve
  Numbered list of open design questions found during review
```

**Key rules:**
- **Every file reference is a clickable relative link** — `[FileName.java](../path/to/File.java)`
- Follow the data flow order, NOT the file tree order — reviewer should understand what happens first
- Include actual code snippets for critical sections (not just descriptions)
- Line-by-line tables for complex methods: `| Lines | Action | What to verify |`
- **VERIFY** = correctness-critical, must check. **QUESTION** = design decision worth discussing
- Cross-reference SFN field names ↔ Java field names ↔ `@JsonNaming` serialization
- Edge case analysis for each method (what if null? what if external service fails? race conditions?)
- File Index at top with 30+ clickable links grouped by layer
- Quick Reference table at bottom with file→flow mapping (also clickable)

### When to Generate These Docs

```
Timeline during implementation:

fixes.md        — Start after first review cycle, update continuously
                   Every bug found → add entry. Every fix → mark FIXED.

testing_strategy.md — Create after all HIGH/MEDIUM bugs are fixed
                      Before requesting stage access or starting manual testing.

manual_review.md    — Create after all code is complete and tests pass
                      Before PR review or team walkthrough.
                      Must have clickable file links and line numbers.
```

### Generating with Parallel Agents

When the user asks to "create review docs" or "prepare for review", launch 3 parallel agents:

```
Agent 1: Create/update fixes.md — read all V2 code, find bugs, categorize by severity
Agent 2: Create testing_strategy.md — build test scenarios from SFN flow + edge cases
Agent 3: Create manual_review.md — walk through every file in flow order with line numbers
```

Each agent needs the full file list and flow understanding. Provide the architecture diagram and file index to each.

---

## Phase 9: Test Coverage Audit

**After all tests pass, audit coverage gaps BEFORE considering the feature done.**

The biggest test blind spot in feature work is: **tests written alongside code only cover what the developer was thinking about.** They miss:
- Consumer/controller dispatch layers (the "boring" delegation code that silently breaks when signatures change)
- Facade error handling (null body, null data, network failures — every external call)
- Edge cases in private helpers that get exercised through specific state combinations

### Mandatory Coverage Checklist

For every new/modified file, verify a test exists covering **each category**:

```
For each PUBLIC METHOD:
  ├── Happy path (correct output, correct side effects, correct status)
  ├── Every null/empty guard clause (null input, null nested field, empty list)
  ├── Every if/else branch (including the else that "can't happen")
  ├── Every catch block (what happens when the dependency throws?)
  ├── Boundary conditions (off-by-one on caps, exactly-at-limit)
  └── Side effect verification (verify DB writes, external calls, with ArgumentCaptor)

For SQS CONSUMERS specifically:
  ├── Happy path: manager called → respondSuccess with correct taskToken + result
  ├── Error path: manager throws → respondFailure with correct taskToken + exception
  ├── Blank/null taskToken: exception rethrown (not swallowed silently)
  └── Verify the EXACT same entry object flows through (no accidental copy/transform)

For FACADES (external service clients):
  ├── Success: valid response body with data → returns expected object
  ├── Null response body → throws ManagerException
  ├── Null response data → throws ManagerException
  ├── RestClientException → throws ManagerException (or returns null — document which!)
  ├── Specific HTTP status codes (409 idempotent, 404 not found)
  └── Headers constructed correctly (use ArgumentCaptor on HttpEntity)

For MANAGERS with terminal/invalidation logic:
  ├── Best-effort operations (scheduler cancel): verify failure is swallowed, downstream steps still execute
  ├── Transactional boundaries: verify DB write doesn't happen when external call fails before it
  ├── Status resolution: test ALL switch cases including default
  └── Priority rules: when multiple fields are set, verify which one wins
```

### How to Run the Audit

```
1. List all V2 source files (grep for V2, new enums, new consumers, new facades)
2. For each file: does a *Test.java exist? → if not, CRITICAL gap
3. For each test file: count test methods vs public methods in source
   Rule of thumb: ≥2 tests per public method (happy + error minimum)
4. For each public method: list every branch → verify a test exists for each
5. Run with coverage (jacoco): flag any method with <80% branch coverage
```

### Common Test Gaps Found in Feature Work

| What gets missed | Why | Fix |
|---|---|---|
| Consumer dispatch tests | "It just delegates, what could go wrong?" | Signature changes, taskToken handling, exception routing — all break silently |
| Facade null/error tests | "The mock always returns valid data" | Every `if (Objects.isNull(response.getBody()))` is an untested branch |
| Reinspection/loop paths | Tests cover first-pass only, not the loop-back | Add tests with reinspection status + reinspection assets in metadata |
| Delta filtering logic | New filtering code doesn't break existing tests because they don't cover that branch | Always add dedicated tests when adding conditional filtering |
| confirmV2Selection-style methods | cancelV2 was tested, so confirmV2 "looks the same" | Each method has unique error behavior — test independently |
| Private helper edge cases | Tested only via happy-path callers | Test boundary inputs: null metadata, non-List type in JSON, cap exactly at limit |

### Test Backfill Strategy

When you discover coverage gaps after implementation:

```
1. Prioritize by blast radius: consumers > managers > facades > helpers
2. Write tests in the MAIN working directory (not worktrees)
3. Compile + run after EACH new test file (don't batch — catch errors early)
4. Use JAVA_HOME override if project needs a specific JDK version
5. Verify with: grep -c "@Test" path/to/TestFile.java (quick count)
```

---

## Common Mistakes

| Mistake | Fix |
|--------|-----|
| Coding before reading existing patterns | Explore agent first. Match conventions exactly. |
| Moving to next step with failing tests | Fix before proceeding. Broken tests compound. |
| Design change → update code but forget docs | Launch parallel agents to update all docs simultaneously. |
| Stale references after removing a feature | Grep across all docs for the removed term. |
| Adding TODO comments | Wire the real thing or leave the method empty. Track placeholders in the steps doc. |
| Null check style inconsistent with codebase | Follow the codebase convention (Objects.nonNull vs != null). Check what existing code uses. |
| HTML tags in javadocs | Plain text. Use {@link} and {@code} only. |
| Creating DTOs in the wrong module | Check where similar DTOs live. Shared DTOs → shared lib. |
| Not saving progress to memory | Save at every checkpoint. Context is lost on compaction. |
| Forgetting env config for new properties | Every new property in application config needs an env var / SSM key entry. |
| Setting state in memory but not persisting | Always verify the DB write happened. Use methods that persist + create events. |
| Workflow variable name mismatch | Grep workflow JSON for every variable reference and verify it exists in the input. |
| DB unique constraint on mutable status column | Status transitions create duplicates. Use code-level dedup, not DB constraints on columns that change. |
| Workflow failure with wrong error code | Catch clauses must exactly match the error string. Verify the wire value. |
| Timezone inconsistency | Always use UTC explicitly. Bare now() uses JVM default timezone. |
| Bypassing manager layer with direct DAO access | Managers add validation, auditing, events. Only bypass for performance-critical reads. |
| Partner-specific strings leaking to consumer | Map to universal enums at the adapter boundary. |
| Importing from wrong/shaded package | Verify imports use the canonical package, not a shaded/relocated copy. |
| ResultPath "$" on wait states | External consumers send partial data — use scoped ResultPath to merge, not replace. |
| Only reviewing files in isolation | Trace data end-to-end across state boundaries. Field name mismatches are invisible in per-file review. |
| New interface impl without reading existing impls | Interface signatures don't encode units, conventions, or transformation logic. Read ALL existing implementations before writing a new one — the contract is in the code, not the signature. |
| Tests pass but coverage is shallow | Tests written alongside code only cover the developer's mental model. Audit every file for a test, then audit every branch for a test case. Consumer tests are most commonly missing. |
| Skipping consumer/facade unit tests | "It's just delegation" — but taskToken handling, null token rethrow, exception routing, and header construction all break silently. Write 3 tests per consumer method minimum. |
| Test backfill in worktrees | Worktrees diverge from the main branch. Always write and run tests in the main working directory. |
