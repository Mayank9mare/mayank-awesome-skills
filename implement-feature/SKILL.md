---
name: implement-feature
description: Use when executing a large feature implementation from a spec or design doc. Covers phased step-by-step coding with test gates, design change handling, doc sync, and progress tracking, and maintains four living docs alongside the code — decision.md (every decision with options, pros/cons, trade-offs), flow.md (entrypoints, call chain, exits, LLD, Mermaid/Excalidraw diagrams), review.md (plain-English review guide with ordered, linked files) and bugs.md (found / fixed / open bugs). Use when user says "implement this", "start coding", "build this feature", or references an implementation plan with steps.
---

# Implementation Execution Workflow

## Overview

End-to-end workflow for implementing large features with Claude Code: break a spec into phased steps, code each step with test gates, handle design changes mid-flight, keep docs/Confluence in sync, and track progress across conversations.

Throughout, keep **four living docs** in `docs/{feature}/` up to date *as you go*, not at the end:

| Doc | Answers | Template |
|---|---|---|
| `decision.md` | What did we choose, what did we reject, what are we trading away? | [templates/decision.md](templates/decision.md) |
| `flow.md` | Where does it start, what calls what, how can it end, what's the LLD? | [templates/flow.md](templates/flow.md) |
| `review.md` | What changed, in plain words, and in what order should I read it? | [templates/review.md](templates/review.md) |
| `bugs.md` | What broke, what's fixed, and what's still open? | [templates/bugs.md](templates/bugs.md) |

See **Living Feature Docs** below for exactly when each one gets updated.

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

**Once the steps are planned:** create `docs/{feature}/decision.md`, `flow.md`, `review.md` and `bugs.md` from `templates/` and seed them (see **Living Feature Docs**).

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
8. Update living docs:
   - decision.md: any choice made in this step (options, pros/cons, trade-offs)
   - flow.md: new or changed entrypoints, calls, exits, LLD, diagrams
   - review.md: this step's files, in reading order, with "what to check"
   - bugs.md: anything that broke along the way (open or fixed)
9. Mark step done
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
7. Living docs: new decision.md entry (old one → "Superseded by Dn"),
   re-sync flow.md (+ regenerate Excalidraw), update review.md, re-scope affected bugs.md entries
8. Update Confluence (if accessible)
9. Verify consistency: grep for stale references across all docs
10. Resume coding
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

### Living Docs
- docs/{feature}/decision.md — D1..Dn (Proposed: list any awaiting the user)
- docs/{feature}/bugs.md — open: B…, fixed: B…
- flow.md / review.md last synced at step N

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
1. Log EVERY finding in bugs.md first (P0/P1 → HIGH, P2 → MEDIUM, P3 → LOW)
2. Fix all P0 immediately — these are production blockers
3. Fix P1 before moving to next phase — these cause subtle bugs
4. P2/P3 stay OPEN in bugs.md — fix during cleanup or next session
5. Re-run ALL tests after fixes; mark fixed bugs FIXED with fix + regression-test links
6. Save updated progress to memory
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

## Living Feature Docs

**The user reviews the work through these four docs, so they must never fall behind the code.**
Create all four in `docs/{feature-slug}/` right after Phase 2 (steps are planned), from the
templates in `templates/`. Fill them in progressively; a half-filled doc that's accurate beats a
complete one that's stale.

All code references use **clickable relative links with line numbers**:
`[OrderManager.create](../../src/main/java/.../OrderManager.java#L60)`. Since the docs live
two levels deep, paths start with `../../`. Re-check line numbers whenever the file changes.

### When to update which doc

| Event | decision.md | flow.md | review.md | bugs.md |
|---|---|---|---|---|
| Phase 2 done (steps planned) | Log the up-front decisions (layering, data model, sync vs async…) | Skeleton: paragraph + entrypoints + planned diagram | TL;DR + planned file order | Create empty |
| You pick between ≥ 2 reasonable options (library, pattern, schema, retry policy, where code lives, following vs breaking a convention) | **New entry** | — | — | — |
| A step adds/changes an entrypoint, call, branch, exit, table, event | — | **Update** call chain / exits / LLD | Add/adjust file rows | — |
| A step is completed | — | Bump "Last synced" | Add the step's files in reading order + "what to check" | — |
| A test fails for a real (non-typo) reason, a review finds an issue, the user reports one | — | Note the affected exit | — | **New entry** (OPEN) |
| A bug is fixed | — | Fix the exit/flow if it changed | Update Known issues | Move to FIXED + fix link + regression test |
| Design change (Phase 4) | **New entry**, mark the old one *Superseded by Dn* | **Update** | **Update** | Close/re-scope bugs it affects |
| Feature complete | All *Proposed* entries resolved or listed for the user | Final sync, diagrams verified | Final pass: diff stats, test count, verify-locally commands | Every entry has a status |

**What counts as a decision:** anything a reviewer might ask "why did you do it this way?" about.
Trivial choices that just follow an existing codebase convention don't need an entry, but
*breaking* a convention always does. When the decision is genuinely the user's (product
behaviour, public API shape, cost), log it as **Proposed**, ask, and update the entry with
the answer.

### decision.md rules

- One entry per decision: **Context → Options (table with pros & cons) → Decision → Trade-offs
  accepted → Consequences → Revisit if**. Always at least two options, because a decision with one
  option isn't a decision.
- Trade-offs are stated concretely ("+1 DB read per request" rather than "slightly slower").
- Never delete or rewrite history. Reversals get a new entry, and the old one is marked superseded.
- Link the decision from the code it shapes in review.md, so reviewers see the *why* next to the *what*.

### flow.md rules

- Write the **one-paragraph story** first, in plain English. If you can't write it, the design isn't clear yet.
- **Entrypoints:** every trigger (HTTP route, queue/topic consumer, cron, CLI, event handler,
  UI action) with its guard (auth, flag).
- **Call chain:** a numbered, indented walk per entrypoint; each line is a link plus what it
  reads, writes, calls or publishes. Real function names, real line numbers.
- **Exits:** every way the flow ends: success, idempotent replay, each validation/error
  return, each exception that escapes, retries exhausted, DLQ. Give each one the caller's result
  and the state left behind.
- **LLD:** components and responsibilities, key signatures, a sequence diagram, a state machine
  if there are statuses, the data model, errors/retries/idempotency, transaction boundaries, config/flags.

#### Diagrams: Mermaid always, Excalidraw when it earns it

- **Mermaid inline** for every diagram (renders on GitHub and in IDEs, diff-able).
- **Excalidraw** in addition when the diagram has more than ~6 nodes, crosses services or async
  boundaries, or the user asks. Use the locally installed `excalidraw-cli`:

  ```bash
  excalidraw ref --raw                     # element format, palette, sizing rules (read once per session)
  # write the elements array to docs/{feature}/diagrams/flow.json, then:
  excalidraw create docs/{feature}/diagrams/flow.json \
    -o docs/{feature}/diagrams/flow.excalidraw --no-checkpoint
  ```

  - Use labeled shapes (`"label": {"text": …}`) and arrows bound with `startBinding`/`endBinding`.
  - Colour by role (blue = entrypoints, purple = logic, teal = storage, orange = external,
    red = error exits) and keep it consistent across the feature's diagrams.
  - Commit both the `.json` source and the `.excalidraw` output; link both from flow.md.
  - Regenerate after any flow change; the JSON source is what you edit.
  - **`excalidraw export` uploads to excalidraw.com and creates a public link. Only run it if the
    user explicitly asks.**

### review.md rules

- **TL;DR first**, in 3–5 sentences of simple English: what the feature does, the shape of the
  change, and the riskiest spot.
- **Reading order follows the data flow**, not the file tree: schema → domain types → core logic →
  entrypoints → async workers → tests. Each row has a link, what the file does in simple words,
  what to check, and its size. Mark the 1–3 files that deserve most attention with ⭐.
- List the files that can be skipped (generated, renames, trivial DTOs).
- For each important file: *in simple words*, *why it's built this way* (links to decision.md),
  *look closely at* (linked line ranges), and **VERIFY** / **QUESTION** checkboxes.
- End with Proposed decisions needing the user's call, open bugs from bugs.md, and exact
  verify-locally commands.

### bugs.md rules

- IDs `B1, B2, …` in order of discovery, never reused. Severity HIGH / MEDIUM / LOW.
- Every entry: where (link), symptom, repro, root cause (or hypotheses), proposed fix, and the
  affected exit in flow.md.
- On fix: strike through the entry, link the fix's lines, and **link a regression test**. A fix
  without a test isn't done.
- Status is one of OPEN, FIXED, DEFERRED (link a ticket), or WON'T FIX (link a decision).
- Log bugs you found and fixed within the same step too. They show the user where the
  tricky parts were.

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

**The living docs (`decision.md`, `flow.md`, `review.md`, `bugs.md`) already exist by now. Phase 8 is a final hardening pass over them, plus the stage test plan.** Everything lives in `docs/{feature}/`.

### 8.1 — Final pass on `bugs.md`

Run one last full review over all changed code (Phase 6 checklist) and log every finding. Then:
- Every entry has a status: OPEN / FIXED / DEFERRED / WON'T FIX.
- Every FIXED entry links its fix lines and a regression test.
- Note which review pass found each bug ("review pass 3 — full codebase audit").
- The Summary table at the top matches the body.

### 8.2 — `docs/{feature}/testing_strategy.md` (Stage/E2E Test Plan)

**Purpose:** Step-by-step guide for manually testing the feature on stage. Someone unfamiliar with the code should be able to follow this and verify the feature works.

**When to create:** After all HIGH/MEDIUM bugs are fixed, before stage testing begins.

**Structure:**

```markdown
# {Feature} — Stage Testing Strategy

## Prerequisites
- [ ] Blocker bugs fixed (reference bugs.md IDs)
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
- Prerequisites section references bugs.md IDs
- Each test scenario has: trigger method, step-by-step verification, expected outcome
- Include actual AWS CLI commands, SQL queries, curl commands
- Cover happy path, error paths, edge cases, and integration boundaries
- Include rollback verification (disable feature, verify V1 still works)

### 8.3 — Final pass on `review.md` (+ `flow.md`)

**Purpose:** someone who has never seen the code can review the whole change in one sitting, in
the right order, understanding each file in plain words before reading it.

Final-pass checklist:
- [ ] TL;DR is accurate for the *final* code, not the plan
- [ ] Header has the real branch, base, diff stats (`git diff --stat {base}...HEAD`) and test count
- [ ] Every changed file appears exactly once in the reading order (cross-check against `git diff --name-only {base}...HEAD`), or is listed under "skip or skim"
- [ ] Reading order follows the data flow; each file only depends on files above it
- [ ] Every link resolves and every `#Lnn` points at the line it describes (line numbers drift, so re-check)
- [ ] ⭐ files have "look closely at" line ranges and VERIFY / QUESTION checkboxes
- [ ] Field names are cross-checked across boundaries (workflow JSON ↔ Java fields ↔ JSON serialisation names)
- [ ] Proposed decisions from decision.md and open bugs from bugs.md are listed
- [ ] flow.md exits and call chain match the final code; Mermaid renders; Excalidraw regenerated from its JSON
- [ ] "How to verify locally" commands actually run

### When to Generate These Docs

```
Timeline during implementation:

decision.md / flow.md / review.md / bugs.md
                    — Created after Phase 2, updated at every step (see Living Feature Docs)
                      Final pass at Phase 8.

testing_strategy.md — Create after all HIGH/MEDIUM bugs are fixed
                      Before requesting stage access or starting manual testing.
```

### Generating with Parallel Agents

When the user asks to "prepare for review", launch 3 parallel agents (each given the file list, flow.md, and decision.md):

```
Agent 1: Final review pass → update bugs.md (read all changed code, find bugs, categorise by severity)
Agent 2: Create testing_strategy.md (scenarios from flow.md entrypoints + exits + edge cases)
Agent 3: Final pass on review.md + flow.md (re-verify every link/line number, ordering, TL;DR, diagrams)
```

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
| Writing decision/flow/review/bugs docs at the end | They're reconstructed from memory and miss the real reasons. Update them in the step where the thing happens. |
| Decision entry with one option, or vague trade-offs | Always ≥ 2 options with pros/cons; state trade-offs concretely ("+1 DB read/request", not "slightly slower"). |
| Rewriting a decision when it changes | Add a new entry and mark the old one "Superseded by Dn". The history is the point. |
| review.md in file-tree order | Order by data flow (schema → domain → logic → entrypoints → workers → tests) so each file only uses what's already been read. |
| Stale `#Lnn` links in docs | Line numbers drift on every edit. Re-verify links in the step that touched the file and in the Phase 8 final pass. |
| Fixing a bug without logging it | Log it in bugs.md even if fixed in the same step, with a regression-test link. |
| `excalidraw export` without asking | It uploads to excalidraw.com as a public link. Keep `.excalidraw` files local unless the user asks to share. |
