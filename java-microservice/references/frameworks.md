# Java service frameworks

Verified 2026-08. **Framework and library versions below come from Maven Central
`maven-metadata.xml`** — registry facts, not blog claims. Behavioural claims cite primary
sources (JEPs, official migration guides) where one exists; anything that could not be
confirmed says so in place rather than being guessed.

## Comparison

| Framework | Version (Maven Central, 2026-08) | DI model | Startup (JVM) | Startup (native) | Native maturity | Ecosystem | Best fit |
|---|---|---|---|---|---|---|---|
| **Spring Boot** | **4.1.0** (Framework **7.0.8**) | Runtime reflection + growing AOT | ~2–4 s | ~104 ms | Mature but heaviest | **Largest by far** | Default choice. Complex business apps; teams valuing ecosystem/hiring. |
| **Micronaut** | **5.1.10** | **Compile-time DI/AOT**, no runtime reflection | ~0.3–0.7 s | ~50 ms | Excellent — native-first by design | Medium | Serverless/Lambda, cold-start-sensitive, low memory. |
| **Quarkus** | **3.38.0** | **Build-time augmentation** + CDI/ArC | ~0.5–1 s | ~50 ms | Excellent — core design bet | Large, fast-growing | Kubernetes-native; best native footprint; superb dev loop. |
| **Helidon** | **4.5.1** (SE + MP) | SE: manual · MP: CDI | Fast | Good | Solid | Small–medium | **Virtual-thread-first blocking** model as a deliberate choice. |
| **Vert.x** | **5.1.5** | None built in | Fast | Good (manual outside Quarkus) | Mature | Medium | Event-driven infrastructure: proxies, gateways, brokers. |
| **Dropwizard** | Stable | Guice (optional) | Moderate | Not a goal | n/a | Small, stable | "Boring and observable"; debuggable at 3am. |
| **Javalin** | Active | **None** — explicit | Very fast | Good (thin) | n/a | Small, growing | Small APIs; Express-like; no DI magic wanted. |
| **Ktor** (Kotlin) | Active | Koin etc. | Fast | Good | Solid | Medium, Kotlin-only | Kotlin-first teams; coroutine server **+ matching client**. |
| **Spark Java** | **DEPRECATED** | None | Fast | n/a | n/a | Shrinking | Legacy only — use Javalin instead. |

### Supporting library versions (Maven Central, 2026-08)

| Library | Version | Note |
|---|---|---|
| HikariCP | **7.1.0** | |
| Hibernate ORM | **7.4.5.Final** | 8.0.0.Beta1 exists — not for production |
| Flyway | **13.1.0** | |
| Micrometer | **1.17.0** | |
| Resilience4j | **2.4.0** | |
| Lettuce | **7.6.0.RELEASE** | the Redis client to prefer |
| Redisson | **4.6.1** | distributed locks |
| **Spring Cloud AWS** | **4.1.0** | **major bump from 3.x** — see messaging.md |
| JUnit | **6.1.2** | |
| Mockito | **5.23.0** | |
| AssertJ | **3.27.7** | 4.0.0-M1 is a preview |
| Testcontainers (Java) | **2.0.5** | **major bump from 1.x** |
| WireMock | **3.13.2** | 4.0.0-beta exists |

### There is no Spring Boot LTS

A common and costly misconception. **Every Spring Boot minor gets the same ~12 months of
OSS support**, with a new minor every 6 months — no release is designated LTS. As of
2026-08 only **4.0 and 4.1** are in open-source support. If you need longer, that's a
commercial support contract, not a version choice. Plan for a minor upgrade roughly
annually rather than expecting to sit on one release for years.

**Read the numbers with suspicion.** They mix hardware, JDKs, workloads and
methodologies and are **not directly comparable**. The most rigorous public,
reproducible benchmark is Ivan Franchin's
`ivangfr/web-reactive-jvm-native-cds-aot-virtual-threads`, which runs comparable
variants under one harness. Most "framework benchmark" listicles recycle numbers from
years-old versions. **Benchmark your own workload** before making a cold-start-driven
architectural decision.

## Spring Boot 4.x

### Baseline

- **Minimum Java: 17** per the official migration guide and
  `docs.spring.io/spring-boot/system-requirements.html` (Boot 4.1 states Java 17
  minimum, compatible to **26**). **Java 21/25 are recommended, not required.**
  Numerous blog posts claim "Java 21 minimum" — that contradicts primary docs; trust
  the docs. The one real Java-21 trigger is **jOOQ 3.20**, which itself requires 21 —
  a dependency requirement, not a framework floor.
- Jakarta EE 11, Servlet 6.1. Kotlin **2.3** (Serialization 1.11) in 4.1. GraalVM
  native-image v25+ for native builds. Requires **Spring Framework 7.0.8+**.

### New in 4.1 (worth knowing)

**First-class gRPC support.** Previously a third-party starter; now three modules —
`spring-boot-grpc-server`, `spring-boot-grpc-client`, `spring-boot-grpc-test` — backed by
Spring gRPC 1.1.0 and grpc-java 1.80.0. Run a standalone Netty-backed server, or expose
gRPC over HTTP/2 through the Servlet integration. If you were reaching for a community
starter to do gRPC on Spring, stop.

**Lazy JDBC connections** — directly relevant to pool exhaustion:

```properties
# Wraps the auto-configured DataSource in LazyConnectionDataSourceProxy, so a
# physical connection is only checked out when a statement actually executes.
spring.datasource.connection-fetch=lazy      # `eager` restores the old behaviour
```

Why it matters: a `@Transactional(readOnly = true)` method that ends up not querying
(cache hit, early return) previously still held a connection for its whole duration.
Under load that's pool capacity burned on nothing. This is a genuinely useful default to
flip on a read-heavy service — measure before and after.

**Async context propagation for `@Async`**, so observability and security context flow
across the async boundary instead of silently vanishing — a long-standing source of
"traces stop at the @Async call" confusion.

### Removals in 4.1 that will bite

- **Everything deprecated in 4.0 is removed.** Clear 4.0 deprecation warnings *before*
  upgrading, not after.
- **The `layertools` jar mode is REMOVED.** If your Dockerfile uses
  `java -Djarmode=layertools -jar app.jar extract`, it breaks. Use
  `java -Djarmode=tools -jar app.jar extract --layers` instead — see packaging-deploy.md.
- `-DskipTests` no longer skips AOT processing of tests; the Maven plugin now honours
  only `maven.test.skip`.
- Apache Derby integration deprecated (the Derby project retired) — move to H2/HSQL.
- If you set JPA bootstrap mode to lazy, the auto-configured bootstrap executor on
  `LocalContainerEntityManagerFactoryBean` is no longer set.

### What breaks moving 3.x → 4.x

- **Modular auto-configuration.** The monolithic `spring-boot-autoconfigure` (grew past
  2 MB by 3.5) is split into focused modules; you now declare a starter per technology —
  e.g. **`spring-boot-starter-webmvc` replaces `spring-boot-starter-web`**.
  `spring-boot-starter-classic` restores the old fat-classpath behaviour as a migration
  escape hatch (plus `-test-classic`, `-autoconfigure-classic`).
- **Undertow support removed entirely** — starter and embedded option both gone, a
  consequence of the Servlet 6.1 baseline. Migration guides tend to undersell this.
- **Jackson 3** replaces Jackson 2 (new group ID). Boot 4 auto-configures
  format-specific mappers (`JsonMapper`, `XmlMapper`), so **defining a bare
  `ObjectMapper` bean no longer fully customises serialisation.**
- **Spring Security 7** DSL rewrite. Spring Data 2025.1. Hibernate 7.1/7.2. **JUnit 6**
  in the test starters.
- **~88% of APIs deprecated across 2.x/3.x are now removed.** Clear every deprecation
  warning on 3.5 *before* upgrading.
- `spring.factories` auto-configuration registration was already replaced by
  `META-INF/spring/...AutoConfiguration.imports` back in 2.7/3.x — long settled.

### Virtual threads: still opt-in

```properties
spring.threads.virtual.enabled=true
```

Not default-on anywhere in 4.x. It switches the web server's request handling and
`@Async`/`TaskExecutor` defaults. It does **not** make blocking libraries
non-blocking, and library-internal `synchronized` on a hot path can still hurt (see
the HikariCP/Logback note below).

### API versioning — new in 4.0

```java
@RestController
@RequestMapping("/orders")
class OrderController {
    @GetMapping(path = "/{id}", version = "1.2+")
    OrderV2 get(@PathVariable String id) { ... }
}
```

Configured with an `ApiVersionConfigurer` bean; header-, path- and media-type-based
resolution are supported. Replaces hand-rolled `RequestCondition`s and
gateway-level version routing.

### Null-safety

Spring Framework 7 / Boot 4 adopt **JSpecify** (`@NullMarked`, `@Nullable`,
`@NonNull`), replacing the old `org.springframework.lang` annotations. Migrate
application annotations to JSpecify's package.

### Testing: `@MockBean` is REMOVED

Not deprecated — **removed**. Use Mockito's `@MockitoBean` / `@MockitoSpyBean`
(introduced in Boot 3.4 as the forward path). Suites still on `@MockBean` **fail to
compile** against Boot 4's test starter.

```java
@SpringBootTest
class OrderServiceTest {
    @MockitoBean PaymentClient paymentClient;
    @Autowired  OrderService  orderService;

    @Test
    void chargesOnCheckout() {
        when(paymentClient.charge(any())).thenReturn(Result.success());
        assertThat(orderService.checkout(cart)).isEqualTo(OrderStatus.PAID);
    }
}
```

### Spring Cloud AWS 3.x — SQS

```java
@SqsListener(value = "${queues.orders}",
             acknowledgementMode = SqsListenerAcknowledgementMode.ON_SUCCESS)
public void handleOrder(@Valid @Payload Order order) { ... }
```

`acknowledgementMode` (`ON_SUCCESS` default / `ALWAYS` / `MANUAL`) replaces the 2.x
container-level `deletionPolicy`.

**Current: `io.awspring.cloud:spring-cloud-aws-sqs` 4.1.0** (Maven Central, 2026-08).
Match the major to your Boot major — 4.x needs Boot 4.0+, 3.x pairs with Boot 3.x. Notes
on the 3.x → 4.x move:

- **The `acknowledgementMode` API is unchanged in shape** — no breaking rename analogous
  to 2.x's `deletionPolicy` → `acknowledgementMode`. Annotation attribute, injected
  `Acknowledgement`/`BatchAcknowledgement`, and
  `SqsTemplate.builder().configure(o -> o.acknowledgementMode(…))` all carry forward.
- **Spring Integration AWS was merged into Spring Cloud AWS** in the 4.x line.
- **New `@SqsHandler`** lets one `@SqsListener` dispatch to several handler methods by
  payload type — useful for a queue carrying a small union of message shapes.
- Nullability annotations migrated to **JSpecify**, matching Framework 7 / JUnit 6 /
  Micronaut 5.
- Jackson 3 support landed during the 4.0 RC cycle (4.0.0-M1 was Jackson 2 only).

### The real 3.x → 4.x breaking changes

**There is no single "SQS migration guide" page** — the changes are scattered across GitHub
release notes and RC changelogs. What's confirmed:

- **The platform baseline is the actual forcing function.** SCA 4.0 requires **Spring Boot
  4.0.0 + Spring Cloud 5.0.0** (Framework 7). You cannot adopt SCA 4.x while on Boot 3.x —
  so this is a consequence of the Boot upgrade, not an independent decision.
- **AWS SDK v2 minimum raised to 2.39.0** (DAX client 2.0.6).
- **Jackson 3**: converter internals move `com.fasterxml.jackson.*` → `tools.jackson.*`. If
  you wired a custom `ObjectMapper` or subclassed `SqsMessagingMessageConverter`, that's a
  compile break.
- **`AwsClientCustomizer`**: deprecated variants removed.
- **STS credentials provider is now lazy** — configured only when `spring.cloud.aws.sts.*`,
  a system property, or an env var is explicitly set. Previously more eager, so a service
  that relied on implicit STS setup can silently lose its credentials provider.
- **JSpecify nullability** affects Kotlin callers who implement or subclass SCA interfaces —
  compile-time null-safety changes.
- **New (additive)**: automatic SQS request batching; `spring-cloud-aws-starter-imds` added
  to the BOM. Note `SqsTemplate#sendMany()` caps at 10 messages — an SQS API limit, not new.

**No renamed or removed `spring.cloud.aws.sqs.*` properties were found** for 3.x→4.x, and
no changed `SqsMessageListenerContainerFactory` or `SqsTemplate` method signatures. Treat
the container-factory and batch-listener APIs as carrying forward.

One trap: property renames like `maxNumberOfMessages`→`maxMessagesPerPoll` and
`waitTimeout`→`pollTimeout` circulate in migration write-ups, but those belong to the
**separate `spring-cloud-stream-binder-sqs` project** aligning its naming to SCA — **not**
to SCA core. Don't apply them to a plain `@SqsListener` service.

Before a real migration, read the 4.x release notes and the version-specific reference
manual at `docs.awspring.io` — the release notes are the most complete public source, and
they are not exhaustive. See messaging.md for consumer design.

## Micronaut

**Compile-time DI is the whole differentiator.** `@Singleton`, `@Inject`,
`@Controller` are processed by annotation processors at *build* time, emitting bean
definitions as bytecode. Consequences:

- No runtime reflection for DI → GraalVM's closed-world analysis has almost nothing
  to guess, which is why native builds are so reliable.
- No classpath-scanning phase at boot → fast startup, low memory.
- Missing/ambiguous dependencies are **compile errors**, not runtime
  `NoSuchBeanDefinitionException`.

```java
@Controller("/orders")
public class OrderController {
    private final OrderService service;

    public OrderController(OrderService service) {   // constructor injection
        this.service = service;
    }

    @Get("/{id}")
    public Order get(String id) { return service.findById(id); }
}

@Singleton
class OrderService { Order findById(String id) { ... } }
```

**Micronaut Data** validates and generates queries at compile time (JDBC-first or
JPA-backed behind the same `@Repository` interface), so a bad query-method name fails
the build. **Micronaut Serde** is compile-time serialisation that outperforms
reflection-based Jackson Databind (vendor-cited gains roughly 7–31% depending on
workload) and avoids reflection in native images.

### Micronaut 5.x — what changed from 4.x

Released May 2026; **5.1.10** current. This is a deliberate modernisation onto the
current JVM baseline rather than a redesign — the compile-time DI/AOT model is unchanged.

- **Java 25 baseline.** Groovy 5 and Kotlin 2.3 are also baselined. That means you cannot
  adopt Micronaut 5 on an older JDK — plan the JDK upgrade first.
- **Context propagation moved to JDK `ScopedValue`**, replacing older ThreadLocal-based
  propagation. Consistent with a virtual-thread-first design, and the reason it needs 25.
- **JSpecify** adopted as the nullability model — the same convergence happening across
  Spring Framework 7, Spring Cloud AWS 4.x and JUnit 6. If you annotate nullability, move
  to JSpecify's package.

### Upgrading 4.x → 5.x — the breaking changes

There **is** an official guide: the `micronaut-core` GitHub wiki page **"Update to
Micronaut 5"**, which fans out to ~45 per-module breaking-change pages. Start there. And
**use the OpenRewrite recipe** — `org.openrewrite.java.micronaut.Micronaut4to5Migration`
composes the 3→4 migration, the Java 25 upgrade, the Gradle wrapper bump and version bumps
in one pass. Mechanical changes should not be done by hand.

**Support removed outright:**
- **RxJava 2 — dropped entirely.** If your codebase still uses RxJava 2 reactive types,
  this is the blocker to resolve first.
- **MicroStream removed**, replaced by **EclipseStore** — a migration, not a rename.

**Silent behaviour changes — the dangerous category:**
- **Micronaut Data embedded-field naming strategy changed.** Embedded fields now need an
  explicit `@MappedProperty("column_name")` to keep their previous column names. Get this
  wrong and your entities map to columns that don't exist — or worse, the wrong ones.
  Escape hatch: `micronaut.data.embedded.naming.strategy=LEGACY`.
- **`jakarta.annotation.Priority` is now mapped** to bean/filter ordering. If your code
  already carried that annotation for another reason, filter order can change under you.
- **Micronaut Serialization 3.0** realigns defaults toward Jackson Databind behaviour:
  `micronaut.serde.deserialization.subtypes-require-default-impl` flips **false → true**
  (polymorphic deserialisation now *requires* a configured default impl instead of falling
  back to the supertype), and **explicit `null` for a non-nullable property now fails
  deserialisation** instead of being silently skipped. Both change what your API accepts.

**Module/dependency moves (compile breaks, easy to fix):**
- JSR-250 security annotations (`@RolesAllowed`, `@PermitAll`, `@DenyAll`) moved from
  `micronaut-security-annotations` → **`micronaut-security-processor`**.
- EclipseStore annotations similarly `...-annotations` → `...-processor`.
- Micronaut Views: Turbo extracted to `micronaut-views-turbo`; **`@TurboView` →
  `@TurboStreamView`**.
- Testcontainers artifact IDs gained the `testcontainers-` prefix (e.g.
  `org.testcontainers:junit-jupiter` → `org.testcontainers:testcontainers-junit-jupiter`) —
  the same rename as Testcontainers-Java 2.0 (see testing.md).

**HTTP layer:** HTTP/3 promoted to **stable** on Netty. The **multipart/form handling was
refactored** to a lower-level, server-independent API — the most likely breakage for
anything doing file uploads or form binding. Micronaut GraphQL now returns HTTP 400 on
malformed GraphQL JSON.

**If you use Jackson directly** rather than Serde: `micronaut-jackson-databind` moves to
**Jackson 3** (3.1.3 in the platform BOM), i.e. `com.fasterxml.jackson.*` →
`tools.jackson.*`. Micronaut recommends the OpenRewrite recipe
`org.openrewrite.java.jackson.UpgradeJackson_2_3`.

**Build baseline:** Java **25**, Kotlin 2.3.21, KSP 2.3.7, Groovy 5, Gradle 9.5.0,
Micronaut Gradle Plugin 5.0.0, Shadow → `com.gradleup.shadow`.

The ~45 per-module sub-pages were not individually reviewed — the above is what the hub
page states directly. Check the sub-page for any module you actually depend on.

## Quarkus 3.38.x

**Build-time augmentation**: bean resolution, proxy generation, config binding and
reflection metadata are computed during the build. That's *why* the native footprint
is the smallest here.

- **Dev mode** (`quarkus dev`): live reload plus **continuous testing** — tests re-run
  in the background as you save. Genuinely its best feature.
- **ArC**: a build-time-optimised CDI container (not runtime-reflective Weld), giving
  the CDI programming model without CDI's traditional cost.
- **RESTEasy Reactive**: Jakarta REST built reactive-first on Vert.x, but supports the
  synchronous model transparently.
- **Dev Services**: auto-provisions Postgres/Kafka/Redis via Testcontainers in dev and
  test, torn down automatically. Zero config if Docker/Podman is present.

```java
@Path("/orders")
public class OrderResource {
    @Inject OrderRepository repo;

    @GET @Path("/{id}")
    public Order get(@PathParam("id") Long id) { return repo.findById(id); }
}

@Entity
public class Order extends PanacheEntity {   // active-record flavour
    public String customerId;
    public static List<Order> findByCustomer(String id) {
        return list("customerId", id);
    }
}
```

**Panache** comes in **active-record** (entity extends `PanacheEntity`, static
finders) and **repository** (`PanacheRepository<T>`, entities stay plain — better when
you want persistence logic out of the entity) flavours. **Mutiny** (`Uni<T>`/`Multi<T>`)
is the reactive toolkit.

**Quarkus 4 is not released.** 3.x is current (3.38.0); **Quarkus 4.0 Beta 1 targets
September 2026**. Don't plan on 4.x today.

### "Panache Next" is now Quarkus Data Hibernate — and it's experimental

The unified-Panache effort was **renamed in March 2026** to **Quarkus Data Hibernate**
(extension `io.quarkus:quarkus-hibernate-panache-next`, first released Feb 2026), aligning
it with the **Jakarta Data 1.0** standard.

What it changes: unifies blocking + reactive + stateful + stateless Hibernate sessions in
one module; **moves query operations off the entity and onto a repository**; adds
type-safe, build-time-validated query annotations.

Three things to know before touching it:

- **It is explicitly experimental** — names, packages, classes and API can all still
  change. Not for production.
- **No backward compatibility with classic Panache.** It's a new module, not a drop-in
  upgrade. A `quarkus-update` recipe is tracked to mechanically migrate most call sites
  (`Person.find()` → `Person_.repo().find()`).
- **Classic `quarkus-hibernate-orm-panache` remains stable and supported.** There is no
  forced migration, so the correct action today is usually "stay put and watch".

### Spring compatibility extensions — stable, but understand what they are

`quarkus-spring-di`, `quarkus-spring-web`, `quarkus-spring-data-jpa` (plus
`-data-rest`, `-security`, `-cache`, `-scheduled`, Spring Boot properties and Spring Cloud
Config Client). Both `spring-di` and `spring-web` are listed **Status: stable** on
quarkus.io, supported by Red Hat & IBM, tracking current Quarkus. **Not deprecated, not
maintenance-mode** — so using them as a migration path is sound.

**The architectural point that matters most: no Spring `ApplicationContext` ever starts.**
Spring classes and annotations are read as **build-time metadata only**; injection is done
entirely by Quarkus's own CDI engine (ArC / Jakarta CDI 4.1). This is
*annotation-surface* compatibility, not runtime Spring compatibility — dropping an
arbitrary Spring library on the classpath does nothing. Teams that assume otherwise lose
days.

Quarkus positions these as a **migration accelerator**: get running on Quarkus with
familiar annotations, then refactor toward native CDI / Jakarta REST / Panache. The
spring-di guide says users are "encouraged to use CDI annotations" — encouragement toward
the native API, not a deprecation of the shim.

**`spring-di` — what maps:** `@Autowired`→`@Inject` · `@Qualifier`→`@Named` ·
`@Value`→`@ConfigProperty` (no expression language) ·
`@Component`/`@Service`/`@Repository`→`@Singleton` · `@Configuration`→`@ApplicationScoped` ·
`@Bean`→`@Produces` · `@Scope` → the matching CDI scope.

**`spring-di` — explicitly NOT supported:**

| Unsupported | Why / what to do |
|---|---|
| `@ComponentScan` | No-op. Quarkus build-time-scans everything; there's no visibility boundary to declare. |
| `@Import` | No CDI counterpart. |
| `@Conditional` | **Ignored** — DI resolves at build time. Use build profiles. |
| Name-based bean→field fallback matching | Must use `@Named` explicitly. |
| `Set<Bean>` / `Map<String,Bean>` injection | Only `List<Bean>` works (gets the `@All` qualifier). |
| `@Autowired(required = false)` | Use CDI `Instance<T>` + `isResolvable()`. |
| `BeanPostProcessor`, `ApplicationContext` | Never invoked / never exists. |
| Spring Boot test features | Use native Quarkus testing. |

**`spring-web` — what maps:** `@RestController`, `@RequestMapping`,
`@GetMapping`/`@PostMapping`/`@PutMapping`/`@DeleteMapping`, `@PathVariable`,
`@RequestParam`, `@RequestBody` — translated onto Jakarta REST (RESTEasy Reactive).

**`spring-web` limitations:** `@ExceptionHandler` works **only inside a
`@RestControllerAdvice` class**, not on controller methods; and it cannot take
Spring-specific parameter types — Spring's `WebRequest` must become
`HttpServletRequest`, which additionally drags in `quarkus-undertow`.

Per-extension limitation lists for `spring-data-jpa`, `-security` and `-cache` weren't
individually reviewed — check that extension's guide before depending on it.

## Helidon 4.x

Two genuinely different flavours: **SE** (lightweight, programmatic, no CDI — you wire
things in code) and **MP** (full MicroProfile: CDI, JAX-RS annotations).

**Níma** is the virtual-thread-first web server, and the architectural bet is
**blocking-by-design on virtual threads** — write straightforward blocking code, let
the JVM scheduler provide the concurrency that used to require a reactive runtime.
That's the sharpest contrast with Quarkus/Vert.x's reactive heritage and with Spring's
opt-in flag.

MP → SE migration is a substantial rewrite (dropping CDI/annotations for explicit
code); the asymmetry is worth knowing before choosing a flavour.

## Vert.x 5.0.x

**Multi-reactor**: by default **2 event loops per core**, each single-threaded. Nothing
may block an event loop; genuinely blocking work goes to a **worker verticle** or an
executor.

**Do virtual threads make it obsolete? No — they complement it.** The event loop owns
I/O multiplexing, event ordering and back-pressure, which are scheduling/correctness
properties virtual threads don't subsume. What virtual threads add is a
sequential-looking programming model on top, instead of chaining
`Future.compose()`/`onSuccess()`.

```java
@ApplicationScoped
public class OrderEventListener {
    @ConsumeEvent("order.created")
    @RunOnVirtualThread                 // blocking-looking code, no event-loop pinning
    void onCreated(Order order) { inventoryService.reserve(order); }
}
```

Constraint: methods returning `Uni`/`Multi`/`CompletionStage` **cannot** use
`@RunOnVirtualThread` — they're already non-blocking by construction. The annotation
exists precisely for blocking-style code.

Choose Vert.x directly (not via Quarkus) when you need control over the threading
model itself — infrastructure software rather than CRUD services — and accept
hand-rolling DI.

## The smaller options

**Dropwizard** — bundles Jetty + Jersey + Jackson + Logback opinionatedly, with
built-in metrics and health checks. YAML config, `java -jar app.jar server config.yml`.
Choose when "unchanged in five years and debuggable on call" beats DX.

**Javalin** — minimalist: no DI, no annotation magic, no reflective routing. Just
`Handler` and `Context`. The actively maintained **successor to Spark Java**.

```java
Javalin app = Javalin.create().start(7070);
app.get("/orders/{id}", ctx -> ctx.json(service.findById(ctx.pathParam("id"))));
```

**Ktor** — Kotlin-first on coroutines (not reactive streams, not virtual threads). Its
differentiator over every Java-only option: a **matching HTTP client** on the same
coroutine model, so server and outbound calls share one idiom.

**Spark Java** — **deprecated**, superseded by Javalin (partly by former Spark
maintainers). Its static-`Spark.get()` design made testing and multi-instance hosting
awkward. Don't start here.

## Jakarta EE / MicroProfile — the spec layer

**MicroProfile 6.0** (on Jakarta EE 10 Core Profile) standardises Telemetry 1.0,
OpenAPI 3.1, Rest Client 3.0, Config 3.0, Fault Tolerance 4.0, Metrics 5.0, JWT Auth
2.1, Health 4.0. **6.1** bumps Config 3.1, Metrics 5.1, Telemetry 1.1.

How they interlock: Fault Tolerance uses CDI interceptors to implement `@Retry`,
`@CircuitBreaker`, `@Timeout`, `@Bulkhead`, `@Fallback`; Config supplies external
overrides for their parameters (change `maxRetries` without a code change); Jakarta
REST is the entry point those annotations wrap.

Implementations: **Open Liberty** (the ratifying RI for MP 4.1/5.0/6.0), Payara,
Helidon MP, Quarkus, WildFly — note WildFly's Micrometer choice blocked full MP 6.0
compatibility for a period; check its current matrix.

**For new cloud-native work prefer Jakarta EE 11 + MicroProfile 7.x**, which adds
**Jakarta Data 1.0** — a portable repository abstraction comparable to Spring Data /
Micronaut Data / Panache, but as a standard.

Choose the pure spec route (Open Liberty/Payara/WildFly) when you have app-server
operational expertise **and** cross-implementation portability is a real requirement,
not a slogan.

## Decision guide

- **Default to Spring Boot 4.x.** Ecosystem depth, docs and hiring pool usually
  outweigh a framework-level performance edge for business applications — even though
  it is neither the fastest-starting nor the smallest here.
- **Quarkus** when: Kubernetes with tight memory/cold-start budgets, best native
  footprint for least tuning, or you want the dev-mode + continuous-testing loop badly
  enough to learn Panache/ArC.
- **Micronaut** when: AWS Lambda / serverless specifically, or you want Spring-like
  ergonomics with much less runtime magic.
- **Helidon SE** when: you want virtual-thread-first blocking as a design choice
  rather than a flag on a reflection-heavy framework, and accept a smaller community.
- **Vert.x directly** when: building infrastructure (proxy, gateway, broker) and you
  need the threading model itself.
- **Dropwizard** when: operational stability and 3am debuggability outrank DX.
- **Javalin** when: the service is small enough that conventions are pure overhead.
- **Ktor** when: Kotlin end-to-end and you want one coroutine idiom for server + client.
- **Not Spark Java** for anything new.

## Spring AI 2.0 — if the service calls an LLM

**GA'd 12 June 2026** and is becoming the de facto Java LLM abstraction. Two facts matter
before you add the dependency:

**It has a hard dependency on Spring Boot 4.0+.** You cannot adopt Spring AI 2.0 on Boot
3.x. Combined with **Spring Boot 3.5 / Framework 6.2 reaching end of life on 30 June
2026**, that turns "we'd like to try Spring AI" into "we need to finish the Boot 4
migration first" — plan accordingly rather than discovering it mid-sprint.

**2.0 is a breaking redesign, not an additive release.** From 1.x:

- **The built-in tool-execution loop was removed from every `ChatModel`**
  (`ToolExecutionEligibilityChecker` is gone). Tool calling now happens *outside* the
  model: `ChatClient` + `ToolCallingAdvisor`, or drive `DefaultToolCallingManager`
  yourself. Any 1.x code that relied on the model transparently executing tools stops
  working.
- **`ChatClient` is now the primary API**; `ChatModel` is a lower-level building block.
  Write against `ChatClient`.
- MCP annotation packages renamed/relocated; Jackson 2→3; `ToolContext` conversation
  history removed; Vertex AI narrowed to `spring-ai-vertex-ai-embedding` only; ZhipuAI
  removed.
- JSpecify null-safety with compile-time enforcement via NullAway.

For observability, prefer **one** instrumentation layer — the OTel Java agent for
HTTP/DB spans, *or* Spring AI's Micrometer observations bridged to OTel for
`ChatModel`/`VectorStore` spans, *or* manual OTel GenAI-semconv spans. Stacking them
double-counts. And put prompt/completion text in span **events**, never attributes:
attributes are indexed and size-limited, so raw prompts there mean PII in your index.

## Cross-cutting notes

**Build**: Gradle (Kotlin DSL preferred for IDE/type-safety; version catalogs
`libs.versions.toml`; convention plugins) vs Maven (BOM for version alignment;
enforcer for build-time constraints). Multi-module rationale is identical in both:
isolate build/test boundaries, enable partial rebuilds, govern versions centrally.

**HikariCP under virtual threads** — the mental-model fix: **pool size ≠ thread
count.** Virtual threads decouple request concurrency from DB-connection concurrency,
so 50,000 virtual threads still only need as many connections as the database can
usefully serve. Hikari's default of **10** becomes a bottleneck once virtual threads
let you drive far more in-flight requests.

**There is no benchmark-blessed number, and HikariCP's maintainers say so** — the official
wiki's position is that pool sizing is deployment-specific. Published guidance for
virtual-thread services clusters at **20–50 per instance** (32/40/50 all appear in
practitioner guides). Treat that as a starting range, then size to what your database can
actually serve: `(db max_connections × 0.8) / instance_count`.

**The anti-pattern, with a real citation.** HikariCP issue **#2151** documents someone
setting `maximumPoolSize=3000`, `minimumIdle=2000` to "match" virtual-thread concurrency
and then reporting that virtual threads had *hurt* performance. Oversizing is the cause,
not the cure: thousands of connections means constant context switching plus thousands of
backend processes on the database. **Never size the pool to the thread count.**

Two HikariCP-specific practices that matter more once threads are cheap:

- **`minimumIdle == maximumPoolSize`** — a fixed-size pool. HikariCP's own recommendation:
  its "Prime Directive" is that user threads should block on *the pool*, never on
  connection creation. A pool that grows and shrinks reintroduces creation latency exactly
  when you're busiest.
- **`connectionTimeout` is your backpressure knob.** With virtual threads, excess
  concurrency queues harmlessly on the pool instead of exhausting OS threads — that's the
  intended behaviour. `connectionTimeout` decides how long a request waits before failing
  with `SQLTransientConnectionException`. Set it deliberately: too long and you convert a
  saturated pool into cascading timeouts upstream; too short and you shed load you could
  have served.

Classic starting formula, still a reasonable floor: `(cores × 2) + effective_spindles`.
The deadlock-avoidance rule also still applies — if a task needs *N* connections
simultaneously, the pool must be large enough that concurrent tasks cannot deadlock
holding one each.

**Pinning, honestly**: a documented production freeze combined Java 21 + virtual
threads + HikariCP + Logback, where Logback's internal `synchronized` logging path
pinned carrier threads under load and starved the scheduler. **JEP 491** (JDK 24,
removes `synchronized` pinning) did **not** prove a silver bullet in at least one
follow-up benchmark — some of these problems are library-internal design, not just the
JVM mechanism. Hikari's `ConcurrentBag` also relies on `ThreadLocal` fast paths that
are less effective when every request is a fresh virtual thread. **Agroal** is a
Loom-native pool alternative designed for this from the start.

**Testing**: JUnit 5 (JUnit 6 in Boot 4 starters), AssertJ, Mockito
(`@MockitoBean`), Testcontainers, WireMock, ArchUnit (layering rules as executable
tests), Awaitility (`await().until(...)` instead of sleep loops).

**Observability**: OTel Java **agent** (bytecode instrumentation, zero source change)
vs manual SDK instrumentation — agent is lower effort and usually sufficient; manual
buys business-meaningful span boundaries at a maintenance cost. Micrometer is the
standard metrics facade across Spring/Quarkus/Micronaut → Prometheus. Structured JSON
logging is the 2026 baseline.

**Native image vs CDS/AOT**: native buys the fastest cold start and lowest memory, at
the cost of build time, closed-world reflection constraints and worse debugging. Worth
it for serverless billed on cold start, CLIs, and density-sensitive deployments. For a
normally warm, horizontally scaled service, **CDS + AOT cache usually delivers most of
the startup win with none of the native tooling tax** — try those first.
