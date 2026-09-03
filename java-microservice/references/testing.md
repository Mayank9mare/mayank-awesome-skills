# Testing

## 1. The test pyramid

```
        /\
       /  \       E2E / contract  — few, slow, cross-service
      /----\
     /      \     Integration     — moderate, real infra via Testcontainers
    /--------\
   /          \   Unit            — many, fast, no I/O
  /____________\
```

Most of your test count and most of your CI time should sit at the bottom. A unit
test runs in milliseconds with no I/O; an integration test spins up a real
container and runs in seconds; an end-to-end/contract test crosses process and
service boundaries and runs in minutes. Invert this — more integration tests than
unit tests, or a thin unit layer propped up by dozens of slow `@SpringBootTest`
classes — and CI time balloons while the tests that should catch logic bugs fast
are instead catching them slowly. If a behavior can be verified without Spring
context, a database, or a network call, it belongs at the bottom of the pyramid,
not the top.

## 2. Unit tests — JUnit 5, AssertJ, and the constructor-injection payoff

```java
class OrderPricingCalculatorTest {

    private final TaxRateProvider taxRateProvider = mock(TaxRateProvider.class);
    private final OrderPricingCalculator calculator = new OrderPricingCalculator(taxRateProvider);

    @Test
    void addsTaxAtTheProvidedRate() {
        when(taxRateProvider.rateFor("IN")).thenReturn(new BigDecimal("0.18"));

        Price result = calculator.priceFor(new Order("IN", new BigDecimal("100.00")));

        assertThat(result.total()).isEqualByComparingTo("118.00");
        assertThat(result.taxComponent()).isEqualByComparingTo("18.00");
    }

    @Nested
    class WhenRateIsZero {
        @Test
        void totalEqualsSubtotal() {
            when(taxRateProvider.rateFor("US")).thenReturn(BigDecimal.ZERO);

            Price result = calculator.priceFor(new Order("US", new BigDecimal("50.00")));

            assertThat(result.total()).isEqualByComparingTo(result.subtotal());
        }
    }

    @ParameterizedTest
    @CsvSource({"0.00,false", "-1.00,true", "0.01,false"})
    void rejectsNegativeAmounts(String amount, boolean expectException) {
        var order = new Order("US", new BigDecimal(amount));
        if (expectException) {
            assertThatThrownBy(() -> calculator.priceFor(order))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("amount");
        } else {
            assertThatCode(() -> calculator.priceFor(order)).doesNotThrowAnyException();
        }
    }
}
```

**AssertJ over raw JUnit assertions** — `assertThat(x).isEqualTo(y)` reads as a
sentence and, critically, produces a real diff on failure (`expected: 118.00 but
was: 100.00`) rather than JUnit's bare `expected: <118.00> but was: <100.00>`
which barely improves on nothing for complex objects. Use
`isEqualByComparingTo` for `BigDecimal` — `isEqualTo` compares scale too, so
`100.00` and `100.0` fail equality despite being the same value.

**The constructor-injection payoff shows up exactly here.** `OrderPricingCalculator`
takes `TaxRateProvider` as a constructor parameter, not a field Spring injects by
reflection — so the test constructs it with `new OrderPricingCalculator(mock)`,
no Spring context, no `@Autowired`, no application context startup at all. Field
injection (`@Autowired private TaxRateProvider taxRateProvider;`) can *only* be
satisfied by a DI container or by reflection hacks in the test — it makes plain
`new` construction impossible and quietly forces every test for that class either
into a slow `@SpringBootTest` or into `ReflectionTestUtils.setField` workarounds.
Constructor injection is a testability decision as much as a style preference.

## 3. Mockito — and its anti-patterns

```java
@ExtendWith(MockitoExtension.class)
class NotificationServiceTest {

    @Mock EmailSender emailSender;
    @Captor ArgumentCaptor<Email> emailCaptor;
    @InjectMocks NotificationService service;   // constructs with mocks — fine for simple cases

    @Test
    void sendsWelcomeEmailWithCorrectSubject() {
        service.welcome(new User("a@example.com", "Ada"));

        verify(emailSender).send(emailCaptor.capture());
        assertThat(emailCaptor.getValue().subject()).isEqualTo("Welcome, Ada!");
    }
}
```

`MockitoExtension` gives you automatic mock initialization and — importantly —
**strict stubbing**: an unused `when(...)` stub fails the test with
`UnnecessaryStubbingException` instead of silently doing nothing. That failure is
a feature; it catches copy-pasted setup that no longer matches what the test
exercises.

Three anti-patterns that show up constantly:

- **Mocking types you don't own.** Mocking a JDK class or a third-party client
  directly (`mock(HttpClient.class)`) couples your test to that library's
  internal call shape rather than to a contract you control — when the library's
  API adds an overload or changes internal delegation, your mock's stubbed method
  silently stops matching what the real code calls, and the test stays green while
  the integration is actually broken. Wrap the third-party type behind your own
  interface and mock *that*.
- **Verifying implementation instead of behavior.** `verify(repo,
  times(1)).findById(id); verify(repo, times(1)).save(any());` locks the test to
  *how* the method is implemented, not *what* it produces — a refactor that
  fetches differently but still produces the correct outcome now fails a test
  that never cared about the outcome. Assert on the returned/observable result
  first; reach for `verify` only for genuine side effects (an email was sent, an
  event was published) that have no other observable trace.
- **Over-mocking a test into meaninglessness.** If every single collaborator is
  mocked and every mock is stubbedto return exactly what the assertion expects,
  the test verifies that Mockito returns what you told it to — not that your code
  does anything correct. If a test has no real logic left to fail, it's testing
  nothing.

## 4. Spring test slices

| Slice | Loads | Use for |
|---|---|---|
| `@WebMvcTest(OrderController.class)` | MVC layer only — controller, filters, `@ControllerAdvice` | Controller request/response mapping, validation, status codes |
| `@DataJpaTest` | JPA repositories + embedded/test DB config | Repository queries, custom `@Query` methods |
| `@JsonTest` | Jackson `ObjectMapper` + configured modules | Serialization edge cases (dates, custom serializers) |
| `@SpringBootTest` | Full application context | True integration tests, wiring verification — use sparingly |

Slices load a fraction of the context a full `@SpringBootTest` would, which is
both faster and a forcing function: if a controller test needs the full security
filter chain to make sense, that's a signal the controller has too many concerns
mixed in.

**`@MockBean` is REMOVED in Spring Boot 4** (deprecated through the Boot 3.4 line,
removed thereafter) — replaced by **`@MockitoBean`** and **`@MockitoSpyBean`**
from `org.springframework.test.context.bean.override.mockito`. The annotation
name changed but the intent is the same: replace a bean in the test context with
a Mockito mock/spy.

```java
@WebMvcTest(OrderController.class)
class OrderControllerTest {

    @Autowired MockMvcTester mvc;      // MockMvcTester (AssertJ-native) — current idiom
    @MockitoBean OrderService orderService;   // was @MockBean pre-Boot-4

    @Test
    void returns404WhenOrderMissing() {
        when(orderService.findById("missing")).thenThrow(new OrderNotFound("missing"));

        assertThat(mvc.get().uri("/orders/{id}", "missing"))
                .hasStatus(HttpStatus.NOT_FOUND);
    }
}
```

**Context caching, and how to not defeat it.** Spring's `TestContextManager` caches
application contexts keyed by their full configuration (active profiles,
`@MockitoBean`/`@MockitoSpyBean` overrides, property sources, imported
configuration classes) — a second test class with an *identical* key reuses the
already-started context instead of paying startup cost again. This is the single
biggest lever over suite wall-clock time on a codebase with more than a handful
of `@SpringBootTest`/slice classes.

You defeat it constantly without realizing:

```java
// Test class A
@MockitoBean OrderService orderService;

// Test class B — different mocked bean set = different cache key = new context started
@MockitoBean OrderService orderService;
@MockitoBean PaymentService paymentService;
```

Every distinct combination of mocked beans, active profiles, or
`@TestPropertySource` values is its own cache entry — five test classes each
mocking one different extra bean is five separately started contexts, not one
reused five times. Consolidate the set of mocked beans across test classes in the
same slice family where you reasonably can, and know that this — not the number
of `@Test` methods — is usually what makes a test module suddenly take four times
as long after someone adds "just one more" integration test class.

## 5. Testcontainers

> **Version note (Maven Central, 2026-08): Testcontainers-Java is at 2.0.5** — a **major**
> bump from the long-lived 1.x line, and the upgrade is not transparent:
> - **Artifact IDs were renamed** with a `testcontainers-` prefix, and **packages were
>   relocated** — so both your build coordinates *and* your imports change. A 1.x snippet
>   copied from an older guide will not compile.
> - **JUnit 4 was removed from core.** Testcontainers 2.0 no longer drags JUnit 4 in
>   transitively; if you still rely on the JUnit 4 `@Rule` integration you must opt into
>   that module explicitly. Most Spring Boot suites are on JUnit 5/6 and unaffected.
> - **Spring Boot's `@ServiceConnection` / `ContainerConnectionDetailsFactory` pattern is
>   unchanged** — that integration continues to work as documented below.
>
> Note the Go module (`testcontainers-go`) is still on a `v0.x` line — the 2.x major
> applies to Java only.

```java
@SpringBootTest
@Testcontainers
class OrderRepositoryIntegrationTest {

    @Container
    @ServiceConnection   // auto-wires spring.datasource.* — no manual @DynamicPropertySource needed
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withReuse(true);   // needs testcontainers.reuse.enable=true in ~/.testcontainers.properties

    @Autowired OrderRepository repository;

    @Test
    void persistsAndReloadsAnOrder() {
        Order saved = repository.save(new Order("US", new BigDecimal("42.00")));

        Optional<Order> found = repository.findById(saved.id());

        assertThat(found).isPresent();
        assertThat(found.get().total()).isEqualByComparingTo("42.00");
    }
}
```

`@ServiceConnection` (Spring Boot 3.1+) replaces the older, more verbose
`@DynamicPropertySource` boilerplate — it inspects the container type and wires
the matching Spring Boot connection properties automatically. `withReuse(true)`
keeps the container alive across test runs on a dev machine (opt-in via the
properties file) so you're not paying container-startup cost on every single test
run during active development; CI typically doesn't enable reuse since each run
is a fresh environment anyway.

For a container shared across many test classes without Spring's context-caching
mechanism doing it for you (e.g. non-Spring test setups, or a container too
expensive to start per class), the singleton-container pattern — a static
container started once in a base class or `static {}` block and never explicitly
stopped, relying on the Ryuk reaper to clean it up at JVM exit — avoids
per-class startup cost at the price of shared mutable state across tests, which
needs its own cleanup discipline (truncate tables between tests, don't rely on
container restart for isolation).

**Never use H2 (or any in-memory substitute) as a stand-in for your real
production database.** H2's SQL dialect, type coercion rules, and constraint
enforcement differ from PostgreSQL/MySQL/etc. in ways that are individually
subtle and collectively common: a query with Postgres-specific syntax (`ILIKE`,
`ON CONFLICT`, JSONB operators) simply doesn't exist in H2's grammar; a
constraint violation that Postgres enforces at the type level, H2 silently
coerces; a numeric overflow or truncation behaves differently. Tests pass against
H2 and the identical query breaks on the real database in production — that gap
is precisely the risk an integration test exists to catch, and H2 reintroduces it
while giving the appearance of coverage. Testcontainers running the actual
database engine costs a few extra seconds of container startup and removes this
entire class of false-positive test.

## 6. WireMock — fault injection

```java
@Test
void retriesOnFirstAttemptTimeout(WireMockRuntimeInfo wm) {
    stubFor(get("/users/42")
            .inScenario("retry-then-succeed")
            .whenScenarioStateIs(STARTED)
            .willReturn(aResponse().withFixedDelay(6000))   // exceeds our 5s read timeout
            .willSetStateTo("second-attempt"));

    stubFor(get("/users/42")
            .inScenario("retry-then-succeed")
            .whenScenarioStateIs("second-attempt")
            .willReturn(okJson("""{"id":"42","name":"Ada"}""")));

    User user = userClient.getUser("42");

    assertThat(user.name()).isEqualTo("Ada");
    verify(2, getRequestedFor(urlEqualTo("/users/42")));   // proves the retry actually fired
}
```

WireMock's value over a plain mock is that it exercises the **real HTTP
client and its resilience configuration** — the retry policy, circuit breaker,
timeout, and connection pool all run for real against an actual (local) socket,
rather than being bypassed by mocking the client interface. Faults worth
explicitly testing: fixed/random delay (timeout triggers correctly), connection
reset (`withFault(CONNECTION_RESET_BY_PEER)`), malformed response body, and a
sequence of failing-then-succeeding responses via WireMock's scenario state
machine (as above) to prove a retry configuration actually retries and a circuit
breaker actually opens after the configured failure threshold — configuration you
otherwise only find is wrong in production, under real transient failures.

## 7. Awaitility over `Thread.sleep`

```java
// ANTI-PATTERN
Thread.sleep(2000);   // guesses how long async processing takes
assertThat(orderStatusRepository.findById(orderId)).hasValueSatisfying(
        status -> assertThat(status.state()).isEqualTo(PROCESSED));
```

A fixed sleep is both slow and flaky in the same breath: too short and the test
fails intermittently under CI load when the async work happens to take longer
than the guess; too long and every run pays the full sleep even when the
condition was satisfied in the first 50ms. It's not a tradeoff between
speed and reliability — it loses on both axes simultaneously.

```java
await().atMost(Duration.ofSeconds(5))
       .pollInterval(Duration.ofMillis(100))
       .untilAsserted(() ->
           assertThat(orderStatusRepository.findById(orderId)).hasValueSatisfying(
                   status -> assertThat(status.state()).isEqualTo(PROCESSED)));
```

Awaitility polls the actual condition and returns the instant it's true —
typically dramatically faster than a worst-case sleep — while still bounding the
wait with `atMost` so a genuinely broken async path fails the test instead of
hanging it forever. Use `untilAsserted` (retries the assertion, surfaces the real
AssertJ failure message on final timeout) over `until` (a bare boolean predicate
with a generic timeout exception) for a debuggable failure.

## 8. ArchUnit — architecture as a test

```java
@AnalyzeClasses(packages = "com.example.myservice")
class LayeringRulesTest {

    @ArchTest
    static final ArchRule controllersDoNotAccessRepositoriesDirectly =
            noClasses().that().resideInAPackage("..controller..")
                    .should().dependOnClassesThat().resideInAPackage("..repository..");

    @ArchTest
    static final ArchRule servicesAreNamedConsistently =
            classes().that().resideInAPackage("..service..")
                    .should().haveSimpleNameEndingWith("Service");

    @ArchTest
    static final ArchRule noFieldInjection =
            noFields().should().beAnnotatedWith(Autowired.class);
}
```

A code review comment ("controllers shouldn't call repositories directly, go
through the service layer") is advice a reviewer has to remember to give on every
PR, forever, and it's silently unenforced the moment that reviewer is on leave.
The same rule as an ArchUnit test runs on every build and fails the build the
first time it's violated — it converts a convention that erodes over months of
team turnover into a fact the codebase can't drift away from. Worth writing for
the handful of rules that matter most: layering direction, package naming, no
field injection, no direct use of a deprecated internal API.

## 9. Test data — builders over shared fixtures

```java
// ANTI-PATTERN: a shared static fixture, mutated by whichever test runs first
class OrderFixtures {
    static Order STANDARD_ORDER = new Order("US", new BigDecimal("100.00"));
}
// Test A mutates STANDARD_ORDER's state, sets a discount... Test B runs after A
// (or in parallel) and inherits a mutated object it never asked for.
```

```java
// Builder — every test starts from a clean, explicit, readable state
public class OrderTestDataBuilder {
    private String country = "US";
    private BigDecimal amount = new BigDecimal("100.00");

    public static OrderTestDataBuilder anOrder() { return new OrderTestDataBuilder(); }

    public OrderTestDataBuilder withCountry(String country) { this.country = country; return this; }
    public OrderTestDataBuilder withAmount(String amount) { this.amount = new BigDecimal(amount); return this; }

    public Order build() { return new Order(country, amount); }
}

// In a test:
Order order = anOrder().withCountry("IN").withAmount("250.00").build();
```

A builder gives every test its own fully independent object graph, with sensible
defaults for the fields the test doesn't care about and explicit overrides for
the one or two fields it does — the test reads as "an order, but with country
IN" rather than requiring the reader to reconstruct the full object by hand. A
shared static fixture object, by contrast, is mutable global state smuggled into
your test suite: one test's incidental mutation becomes another test's confusing,
order-dependent failure, and the failure is often only reproducible when tests
run in a particular order or in parallel — exactly the kind of flake that eats a
whole afternoon to track down.

## 10. What NOT to test

- **Getters/setters and framework plumbing.** A generated getter that returns a
  field has no logic to be wrong; a test for it asserts that Java assignment
  works.
- **The framework itself.** Don't write a test asserting `@Transactional` rolls
  back a transaction — that's testing Spring, not your code. Do test that *your*
  method, under a failure condition, leaves the database in the state you expect
  — that's testing your logic using the framework's guaranteed behavior as a
  premise.
- **Private methods directly.** A private method is an implementation detail of
  the public method that calls it. Testing it directly (via reflection, or by
  weakening its visibility just so a test can reach it) couples the test to
  internal structure that's free to change as long as the public contract holds.
  If a private method's logic is complex enough to want direct tests, that's
  usually a sign it should be its own class with its own public API.
- **Trivial delegation.** A method that only calls another method and returns
  its result, with no branching or transformation, has nothing to assert beyond
  "it called through" — and a `verify` for that is testing that Java method
  calls work.

Every test has an ongoing maintenance cost — it re-runs on every CI build and
needs updating every time the code it touches legitimately changes. A test that
can't fail for a real reason has negative expected value: it's pure cost with no
corresponding chance of ever catching a real bug.

## Checklist

- [ ] Suite shape follows the pyramid — unit tests dominate the count, integration tests are the minority, E2E is a handful
- [ ] Constructor injection used throughout — no test forced into `@SpringBootTest` just to satisfy field injection
- [ ] AssertJ used for real diffs, `isEqualByComparingTo` for `BigDecimal`
- [ ] `MockitoExtension` strict stubbing left on — no suppressing `UnnecessaryStubbingException`
- [ ] No mocking of types you don't own; wrap and mock your own interface instead
- [ ] Assertions target observable outcomes first; `verify` reserved for genuine side effects
- [ ] Correct test slice used per concern — `@WebMvcTest`/`@DataJpaTest`/`@JsonTest` before reaching for full `@SpringBootTest`
- [ ] `@MockitoBean`/`@MockitoSpyBean` used, not the removed `@MockBean`, on Boot 4
- [ ] Mocked-bean sets and profiles kept consistent across test classes to preserve context caching
- [ ] Testcontainers with `@ServiceConnection` for real dependencies — no H2 standing in for the production database
- [ ] WireMock fault/delay/scenario tests actually exercise retry and circuit-breaker configuration
- [ ] No `Thread.sleep` for async assertions — Awaitility `untilAsserted` with a bounded `atMost`
- [ ] ArchUnit rules encode the layering/naming conventions that matter, so they can't silently drift
- [ ] Test data built via builders with sensible defaults, not shared mutable static fixtures
- [ ] No tests for getters/setters, framework behavior, private methods, or trivial delegation
