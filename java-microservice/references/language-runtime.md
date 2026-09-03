# Java language & JVM runtime for services

Verified 2026-08. Current LTS: **Java 25** (GA 2025-09-16, 5+ years support,
succeeds 21). Items below are marked FINAL / PREVIEW / INCUBATING / REMOVED —
respect those markers; shipping a preview feature needs `--enable-preview`, which
pins your runtime to the exact JDK minor version.

## Choosing a Java version

| Version | Status | Use when |
|---|---|---|
| **25** | **LTS**, current | Default for new services. |
| 21 | LTS, still supported | Existing services; virtual threads available. |
| 17 | LTS, nearing end of broad support | Migrate off. Framework support is dropping. |
| 11 / 8 | Legacy | Migration project, not a choice. |
| 26+ | Non-LTS, 6-month cadence | Only if you can upgrade every 6 months. |

Non-LTS releases get 6 months of updates. For services, track LTS unless you have
continuous-upgrade discipline.

## Virtual threads (Project Loom) — FINAL since 21

A virtual thread is a JVM-scheduled thread mounted onto a small pool of platform
carrier threads. When it blocks on I/O, it **unmounts** and the carrier runs
something else. Result: blocking, readable, sequential code with the scalability
of async — without the reactive programming tax.

```java
// One virtual thread per task. Cheap: millions are feasible.
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    for (var id : ids) {
        executor.submit(() -> handle(id));   // blocking calls inside are FINE
    }
}   // close() waits for all submitted tasks
```

In Spring Boot, one property switches the web server and `@Async` to virtual threads:

```properties
spring.threads.virtual.enabled=true
```

### Pinning — much less of a problem in 25 than the old advice suggests

A pinned virtual thread cannot unmount, so it holds its carrier thread and you
lose the benefit.

- **`synchronized` blocks used to pin. JEP 491 (JDK 24) fixed this** — virtual
  threads can now unmount while holding a monitor. Advice telling you to replace
  every `synchronized` with `ReentrantLock` is **outdated for 24+**. On 21, that
  advice still applies.
- Still pins on 25: **native frames** (JNI calls), and class-initialisation
  blocking.
- Diagnose with `-Djdk.tracePinnedThreads=full` (21) or JFR's
  `jdk.VirtualThreadPinned` event.

### When virtual threads are the WRONG answer

- **CPU-bound work.** Virtual threads don't add cores. Use a bounded
  `ForkJoinPool`/fixed pool sized to the core count. Millions of virtual threads
  doing math is millions of context switches for no gain.
- **Thread pool used as a semaphore.** Lots of code relies on a fixed pool to *limit
  concurrency* against a fragile dependency. Swap in unbounded virtual threads and
  you remove the limiter and stampede the dependency. Replace the pool with an
  explicit `Semaphore` — express the limit, don't imply it.
- **Connection pools become the new bottleneck.** 10,000 virtual threads and a
  HikariCP pool of 10 means 9,990 threads queueing on the pool. Virtual threads
  move the constraint; they don't remove it. Resize deliberately.
- **`ThreadLocal`-heavy code.** Per-thread state across millions of threads is a
  memory problem. Use `ScopedValue` instead (see below).

### Scoped values — FINAL in 25

The virtual-thread-safe replacement for most `ThreadLocal` usage: immutable,
bounded to a dynamic scope, and inherited by child threads in a structured scope.

```java
private static final ScopedValue<String> REQUEST_ID = ScopedValue.newInstance();

ScopedValue.where(REQUEST_ID, requestId).run(() -> {
    // anything called here, on this thread or a structured child, sees REQUEST_ID
    service.process();
});
// outside the scope the binding no longer exists — no cleanup bug possible
```

Prefer it over `ThreadLocal` for request-scoped context (correlation IDs, auth
principal, tenant) in any virtual-thread codebase. Unlike `ThreadLocal` there is
no `remove()` to forget.

### Structured concurrency — **PREVIEW in 25 (JEP 505)**

`StructuredTaskScope` gives you "these subtasks share a lifetime": if one fails,
siblings are cancelled; the parent cannot return before children finish.

**It is still a preview API in Java 25** — its fifth preview round, JEP 505. That means
`--enable-preview` at compile *and* run time, which pins you to that exact JDK minor
version. It continues to move: JEP 525 targets JDK 26, JEP 533 (seventh preview) targets
JDK 27. Do not build production code on it yet unless you accept re-writing on each
upgrade.

```java
// Java 25 shape: StructuredTaskScope is a SEALED INTERFACE (changed from JDK 24's
// subclassable class), and completion policy comes from a Joiner.
try (var scope = StructuredTaskScope.open(
        StructuredTaskScope.Joiner.<String>awaitAllSuccessfulOrThrow())) {

    Subtask<String> user  = scope.fork(() -> userService.find(id));
    Subtask<String> perms = scope.fork(() -> permService.find(id));

    scope.join();                       // waits for both; propagates the first failure
    return new Profile(user.get(), perms.get());
}   // leaving the block guarantees no orphaned subtasks
```

The API shape has changed on nearly every preview round — `open()`/`Joiner` replaced the
older `ShutdownOnFailure`/`ShutdownOnSuccess` subclass spellings, and the sealed-interface
redesign landed in 25. **Check your exact JDK's javadoc before writing against it**; any
example older than a few months is probably wrong.

Until it stabilises, the boring alternative for fan-out/fan-in is a virtual-thread
executor plus `Future`s, or `CompletableFuture.allOf` — less elegant, no preview flag.

## Garbage collectors

| GC | Pause profile | Heap overhead | Choose when |
|---|---|---|---|
| **G1** (default) | tens of ms, predictable-ish | moderate | Default. Balanced throughput/latency. Region-based, handles most services fine. |
| **Generational ZGC** | **sub-10ms**, concurrent | higher (colored pointers, remembered sets) | Latency-sensitive APIs, large heaps (GBs–TBs). The go-to for tail latency. |
| **Shenandoah** | low, concurrent | moderate-high | ZGC alternative; **generational mode added JEP 521 in 25, opt-in**. |
| **Parallel** | long STW, best throughput | low | Batch/offline jobs where throughput beats latency. |
| **Serial** | long STW | lowest | Tiny heaps, single-core, minimal footprint containers. |
| **Epsilon** | never collects | n/a | Testing/benchmarking only. Will OOM by design. |

```sh
# Latency-sensitive API. On JDK 24+ there is only ONE ZGC (generational), so
# -XX:+UseZGC is the whole flag. Do NOT add -XX:+ZGenerational — see below.
-XX:+UseZGC

# Throughput batch worker
-XX:+UseParallelGC

# Generational Shenandoah (25+, opt-in — not the default Shenandoah mode)
-XX:+UseShenandoahGC -XX:ShenandoahGCMode=generational
```

### Two ZGC facts that blog posts routinely get wrong

**1. `-XX:+ZGenerational` is obsolete — stop passing it.** JEP 474 (JDK 23) made
generational the *default* ZGC mode; **JEP 490 (JDK 24) removed the non-generational
mode entirely.** On 24/25 there is only generational ZGC, so the flag is redundant at
best and a removed-option warning (or startup failure, depending on the JDK) at worst.
Any snippet that still pairs it with `UseZGC` predates JDK 24.

**2. ZGC is NOT the JVM's default collector. G1 still is.** JEP 474/490 settled the
*generational-vs-non-generational* question **inside** ZGC — they did not promote ZGC to
the JVM default. You must still opt in with `-XX:+UseZGC`. This is one of the most
commonly repeated errors in third-party writeups; if a source tells you Java 25 "made
ZGC the default", it is wrong.

Generational ZGC splits young/old so it collects mostly-young objects without scanning
the whole heap — the reason it superseded the original design.

## Compact object headers — JEP 519, PRODUCT option in 25

```sh
-XX:+UseCompactObjectHeaders    # no longer needs UnlockExperimentalVMOptions in 25
```

Shrinks object headers from 128 to 64 bits on 64-bit JVMs. On object-dense
workloads (lots of small objects — think caches, large collections of small DTOs)
this is a straight heap-footprint reduction and thus fewer GCs. Low risk, good
payoff; benchmark your own workload but expect a win.

## Container awareness — get this right or nothing else matters

The JVM reads cgroup limits, but **only if you let it express the heap as a
percentage**.

```sh
# WRONG in a container: a fixed heap that ignores the pod's actual limit
-Xmx2g

# RIGHT: scale with whatever the container was given
-XX:MaxRAMPercentage=75.0
-XX:InitialRAMPercentage=50.0
```

Why 75% and not 100%: the JVM needs non-heap memory inside the same cgroup —
metaspace, code cache, thread stacks, direct byte buffers, GC structures, the JVM
itself. Give the heap ~70–80% of the container limit and leave the rest.

`-XX:+UseContainerSupport` is **on by default**; you'd only ever disable it.
`-XX:ActiveProcessorCount=N` overrides detected CPU count — needed occasionally
when cgroup CPU detection misleads pool sizing. cgroup v2 is detected automatically
on modern kernels.

### Starting flag sets

```sh
# (a) Latency-sensitive API pod
-XX:MaxRAMPercentage=75 -XX:InitialRAMPercentage=50 \
-XX:+UseZGC \
-XX:+UseCompactObjectHeaders \
-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/heapdump.hprof \
-XX:+ExitOnOutOfMemoryError \
-XX:StartFlightRecording=maxsize=256m,maxage=1h,settings=profile

# (b) Throughput batch worker
-XX:MaxRAMPercentage=80 -XX:+UseParallelGC \
-XX:+HeapDumpOnOutOfMemoryError -XX:+ExitOnOutOfMemoryError

# (c) Small memory-constrained pod (<512Mi)
-XX:MaxRAMPercentage=70 -XX:+UseSerialGC \
-XX:+UseCompactObjectHeaders -Xss512k \
-XX:+ExitOnOutOfMemoryError
```

`-XX:+ExitOnOutOfMemoryError` matters in Kubernetes: a JVM limping along
post-OOM serves errors while staying "alive". Better to die and let the
orchestrator restart it. Pair with `HeapDumpOnOutOfMemoryError` writing to a
mounted path so you can diagnose after the fact.

## Startup: CDS, AOT, native image

Ordered by effort:

1. **AppCDS / Class Data Sharing** — cheapest real win. Archive loaded classes so
   the next JVM maps them instead of parsing. Java 25 simplifies AOT cache creation
   and can reuse **method-execution profiles from a previous run** so the JIT warms
   up faster.
   ```sh
   java -XX:AOTMode=record -XX:AOTConfiguration=app.aotconf -jar app.jar   # training run
   java -XX:AOTMode=create -XX:AOTConfiguration=app.aotconf -XX:AOTCache=app.aot -jar app.jar
   java -XX:AOTCache=app.aot -jar app.jar                                  # production
   ```
   Verify exact flag spellings against your JDK — Project Leyden's surface is
   still settling across 24/25.
2. **Spring Boot layered jars / buildpacks** — better Docker layer caching, faster
   deploys. No runtime change.
3. **GraalVM native image** — ~50–100ms startup, big RSS reduction, but: long
   builds (minutes), reflection/proxy config required, some libraries unsupported,
   and no JIT peak-throughput. Worth it for serverless/scale-to-zero and hard
   memory budgets. Usually **not** worth it for a long-running service where CDS
   plus AOT already fixed startup.
4. **jlink** custom runtime — smaller base image if you're not on native.

## Language features usable on 25

**FINAL** — use freely:

```java
// Records: transparent immutable carriers. Replaces most DTO/value classes.
public record Money(BigDecimal amount, Currency currency) {
    public Money {                         // compact constructor for validation
        Objects.requireNonNull(amount);
        if (amount.signum() < 0) throw new IllegalArgumentException("negative");
    }
}

// Sealed interfaces: a closed set of subtypes the compiler can reason about.
public sealed interface PaymentResult
        permits Approved, Declined, Pending {}

// Pattern matching for switch + record patterns: exhaustive, no default needed.
String describe(PaymentResult r) {
    return switch (r) {
        case Approved(var txnId, var amt) -> "ok " + txnId + " " + amt;
        case Declined(var reason)         -> "declined: " + reason;
        case Pending p                    -> "pending " + p.retryAfter();
        // no default: sealed + exhaustive means adding a subtype BREAKS THE BUILD.
        // That is the feature — the compiler finds every site you must update.
    };
}

// Text blocks
var query = """
        SELECT id, name FROM users
        WHERE tenant_id = ? AND active = true
        """;

// Sequenced collections (21+): a real API for "first"/"last"/reversed
list.getFirst(); list.getLast(); list.reversed();
map.firstEntry();  // on SequencedMap

// Virtual threads, Scoped values — see above.
```

Also **permanent in 25**: compact source files and instance `main` methods, with a
new `IO` class in `java.lang` (implicitly imported), so `IO.println(...)` works in
a single-file program. Handy for scripts and teaching; irrelevant to service code.

**Still INCUBATING in 25**: the **Vector API** (10th round, waiting on Valhalla).
Don't ship on it.

**Stream Gatherers: FINAL since JDK 24 (JEP 485)** — available and stable in 25. They are
carried-forward functionality, not a new 25 feature, and they are not preview. Use them
freely for custom intermediate stream operations (windowing, folding, scanning) that the
built-in operators can't express:

```java
// fixed-size windows — previously required a hand-rolled collector or a third-party lib
List<List<Integer>> batches = ids.stream()
        .gather(Gatherers.windowFixed(100))
        .toList();
```

**Verify before use** — these are still moving between JDKs: `StructuredTaskScope`
(preview, JEP 505 in 25 — see above), primitive types in patterns, flexible constructor
bodies, module import declarations. Check your JDK's release notes; do not assume from a
blog post.

**Next LTS: Java 29, targeted September 2027** (two-year LTS cadence since 21). Java 25
is supported for 5+ years, so there is no urgency — but that's the horizon to plan the
next jump against.

## Diagnostics

```sh
# What's running, and cheap thread/heap facts
jcmd <pid> help
jcmd <pid> Thread.print                 # includes virtual thread info on 21+
jcmd <pid> GC.heap_info
jcmd <pid> VM.native_memory summary     # needs -XX:NativeMemoryTracking=summary

# JFR — always-on profiling, low overhead (~1-2%)
jcmd <pid> JFR.start name=diag settings=profile maxsize=256m maxage=1h
jcmd <pid> JFR.dump name=diag filename=/tmp/diag.jfr
jfr summary /tmp/diag.jfr
jfr view hot-methods /tmp/diag.jfr      # `jfr view` is the underused one

# Heap
jcmd <pid> GC.heap_dump /tmp/heap.hprof
```

Run JFR continuously in production with `-XX:StartFlightRecording` and bounded
`maxsize`/`maxage` — when an incident happens you want the recording to already
exist. Add `async-profiler` when you need flame graphs including native frames.

Useful JFR events for virtual threads: `jdk.VirtualThreadPinned`,
`jdk.VirtualThreadSubmitFailed`.

## Memory model & concurrency correctness, briefly

- `volatile` gives visibility and ordering, **not** atomicity. `volatile int i; i++`
  is still a race.
- Prefer `java.util.concurrent` over hand-rolled locking: `ConcurrentHashMap`,
  `LongAdder` (better than `AtomicLong` under high contention), `Semaphore`,
  `CompletableFuture`.
- Immutability (records + `List.copyOf`) removes most concurrency questions before
  they're asked.
- `CompletableFuture` remains useful for *composing* async results, but with virtual
  threads you rarely need it for *achieving* concurrency — plain blocking calls in
  virtual threads are simpler and easier to debug. Prefer structured concurrency
  for fan-out/fan-in.
- The `SecurityManager` is **removed**. Don't design around it.
