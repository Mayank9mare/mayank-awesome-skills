# Packaging and Deployment

## 1. Configuration — `@ConfigurationProperties` records, validated

```java
@ConfigurationProperties(prefix = "myservice.upstream")
@Validated
public record UpstreamProperties(
        @NotBlank String baseUrl,
        @Positive Duration connectTimeout,
        @Positive Duration readTimeout,
        @Min(1) @Max(500) int maxConnections
) {}
```

```java
@Configuration
@EnableConfigurationProperties(UpstreamProperties.class)
class UpstreamConfig { }
```

```yaml
myservice:
  upstream:
    base-url: https://api.example.com
    connect-timeout: 2s
    read-timeout: 5s
    max-connections: 100
```

A `record` for configuration is immutable by construction — nothing downstream
can accidentally mutate a shared config object at runtime, which is a real class
of bug when the object is a singleton bean read from many threads. Combined with
`jakarta.validation` annotations and `@Validated`, a missing or malformed value
fails **application startup**, not the first request that happens to touch that
field three days later in production. `@NotBlank` on `baseUrl` and `@Positive` on
the timeouts turn "someone left a required property out of the Helm values file"
into a boot failure with a clear message, not a silent `null` or `0s` timeout
that surfaces as a mystery outage.

Prefer constructor binding (implicit for records) over field-mutating setter
binding — there is no partially-constructed, partially-validated intermediate
state possible with a record.

## 2. JVM flags for containers

The single most consequential flag: **`-XX:MaxRAMPercentage`, not `-Xmx`.** A
container's cgroup memory limit is not the same as host physical memory, and the
JVM has been cgroup-aware by default for years — but a *hardcoded* `-Xmx2g` is
wrong the moment someone changes the pod's memory limit without also updating
the flag, either wasting headroom or (worse) leaving no room for non-heap memory
and getting OOMKilled by the cgroup instead of by the JVM's own OOM handling.
`-XX:MaxRAMPercentage` scales with whatever limit the container actually has.

```
# Set 1 — general-purpose service, container limit 2Gi
-XX:MaxRAMPercentage=75.0
-XX:InitialRAMPercentage=50.0
-XX:+ExitOnOutOfMemoryError
-XX:+HeapDumpOnOutOfMemoryError
-XX:HeapDumpPath=/tmp/heapdump.hprof
-XX:+UseContainerSupport
```

```
# Set 2 — latency-sensitive service, favor predictable pauses over max throughput
-XX:MaxRAMPercentage=70.0
-XX:+UseZGC
-XX:+ExitOnOutOfMemoryError
-XX:ActiveProcessorCount=2
```

```
# Set 3 — memory-constrained sidecar/low-traffic service, minimize footprint
-XX:MaxRAMPercentage=60.0
-XX:MaxMetaspaceSize=128m
-Xss512k
-XX:+ExitOnOutOfMemoryError
```

`-XX:+ExitOnOutOfMemoryError` is easy to skip and shouldn't be — without it, a
JVM that hits `OutOfMemoryError` can limp along in an undefined, partially-broken
state (some threads dead, others still serving) rather than dying cleanly and
letting the orchestrator restart it. `-XX:+HeapDumpOnOutOfMemoryError` costs
nothing until the day you actually need to know what filled the heap, at which
point it's the only artifact that tells you. `-XX:ActiveProcessorCount` matters
when the container's CPU *limit* (e.g. Kubernetes `limits.cpu`) is lower than the
node's actual core count — without it, the JVM sizes GC threads and common thread
pools off the host's core count and over-provisions for the CPU it's actually
allotted, causing contention rather than parallelism.

`-XX:+UseContainerSupport` is default-on since JDK 10 — listed above for
explicitness, not because you need to set it.

## 3. Dockerfile — multi-stage, layered jars, non-root

```dockerfile
# ---- build stage ----
FROM eclipse-temurin:25-jdk AS build
WORKDIR /app
COPY gradlew gradlew.bat ./
COPY gradle gradle
COPY build.gradle.kts settings.gradle.kts ./
RUN ./gradlew dependencies --no-daemon   # layer caches deps separately from source
COPY src src
RUN ./gradlew bootJar --no-daemon

# ---- layer extraction ----
FROM eclipse-temurin:25-jre AS extract
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
RUN java -Djarmode=tools -jar app.jar extract --layers --destination extracted

# ---- final runtime image ----
FROM eclipse-temurin:25-jre
RUN groupadd -r spring && useradd -r -g spring spring   # non-root — see below
WORKDIR /app
COPY --from=extract --chown=spring:spring /app/extracted/dependencies/ ./
COPY --from=extract --chown=spring:spring /app/extracted/spring-boot-loader/ ./
COPY --from=extract --chown=spring:spring /app/extracted/snapshot-dependencies/ ./
COPY --from=extract --chown=spring:spring /app/extracted/application/ ./
USER spring:spring
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "org.springframework.boot.loader.launch.JarLauncher"]
```

> **Flag note:** use `-Djarmode=tools ... extract --layers`. The older
> `-Djarmode=layertools -jar app.jar extract` spelling was **REMOVED in Spring Boot
> 4.1** — a Dockerfile carrying it fails at image-build time after the upgrade, and
> it's a very common copy-paste from older tutorials.

**Layered jars exist because of how Docker's layer cache works.** A Spring Boot
fat jar is one blob — change one line of application code and the entire jar is
a new layer, which means every deploy re-pushes and re-pulls the full set of
third-party dependencies even though they didn't change. `-Djarmode=tools ...
extract --layers` splits the jar into `dependencies` (changes rarely),
`spring-boot-loader` (changes almost never), `snapshot-dependencies` (your
own SNAPSHOT artifacts, if any), and `application` (your compiled classes —
changes every build). Copying them into the image in that order means only the
last, smallest layer is usually new on a rebuild, and registries/nodes that
already have the earlier layers cached skip re-pulling them — materially faster
deploys once the cache is warm.

| Base image | Size | Shell/debug tools | Use when |
|---|---|---|---|
| `eclipse-temurin:25-jre` | Moderate | Full (bash, coreutils) | Default choice — you can `kubectl exec` in and debug |
| `eclipse-temurin:25-jre-alpine` | Smaller | musl-based, limited | Size matters more than tooling; verify native-lib compatibility (musl vs glibc) |
| Distroless (`gcr.io/distroless/java25`-equivalent) | Smallest | **None — no shell at all** | Strong security posture is the priority; you lose `kubectl exec` debugging entirely |
| GraalVM native-image runtime base | Smallest, no JVM at all | None | Only if you've committed to native compilation (see §4) |

**Non-root is not optional.** Running as `root` inside a container means a
container-escape vulnerability in *any* dependency — not just your code — hands
the attacker root on the host's kernel namespace, subject only to whatever the
container runtime's other isolation provides. Creating an unprivileged user and
switching to it with `USER` costs three lines and closes off an entire class of
escalation.

**Exec form, not shell form, for `ENTRYPOINT`.** `ENTRYPOINT ["java", ...]`
(exec form) makes the JVM PID 1 and delivers `SIGTERM` directly to it.
`ENTRYPOINT java ...` (shell form) runs `/bin/sh -c "java ..."` — the shell
becomes PID 1, and depending on the shell, `SIGTERM` may not be forwarded to the
JVM child process at all. The container then only stops when Docker/Kubernetes
escalates to `SIGKILL` after the grace period expires, which means every
deployment or scale-down pays the full grace period timeout instead of shutting
down promptly, and in-flight requests get killed mid-flight rather than
completing under graceful shutdown (§5).

## 4. Startup optimization — AppCDS/AOT vs native

| Approach | Startup improvement | Peak throughput | Build complexity |
|---|---|---|---|
| Default JIT, no cache | Baseline | Best (after warmup) | None |
| AppCDS (`-XX:SharedArchiveFile`) | Meaningfully faster class loading | Same as default once warmed | Low — one extra build step |
| Project Leyden AOT cache (`-XX:AOTCache`) | Faster still — includes profiling data, not just class metadata | Same as default once warmed | Low-moderate, JDK-version-dependent |
| GraalVM native image | Near-instant startup, near-instant peak (no warmup) | Often lower peak throughput than a warmed-up JIT; reflection/dynamic-proxy-heavy code needs explicit config | High — separate build toolchain, reflection config, longer CI build times |

AppCDS and the newer AOT cache both work by capturing something the JVM would
otherwise redo on every process start — class metadata and, in Leyden's case,
early profiling data — into a file loaded at startup instead of recomputed.
They're worth adopting almost unconditionally for a JVM microservice: cheap to
add, no code changes, and every replica in a fleet with frequent restarts
(rolling deploys, autoscaling, spot-instance churn) benefits identically.

**Native image is a real tradeoff, not a strict upgrade.** It buys you
container-like startup latency (useful for scale-to-zero, CLI tools, or very
bursty autoscaling) at the cost of a heavier build pipeline, an entirely
different debugging story (limited runtime reflection means some libraries need
explicit `reflect-config.json` entries or don't work at all without framework
support), and often *lower* sustained throughput than a JIT-warmed JVM under
long-running steady load, because native image forgoes the JIT's profile-guided
runtime optimization. Reach for native image when startup latency is the
dominant cost (serverless-style scaling, short-lived jobs); for a long-running
service that stays up for hours or days, a JIT with AppCDS/AOT usually wins on
total cost.

## 5. Graceful shutdown — ordering and `preStop`

```yaml
server:
  shutdown: graceful
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s
```

Spring Boot's graceful shutdown stops accepting **new** requests on the web
server immediately but lets **in-flight** requests finish, up to the configured
timeout — this alone prevents the most common self-inflicted 5xx spike during
deploys, where the old pod is killed mid-request.

But graceful shutdown at the application level only helps if traffic actually
stops arriving before the process exits. In Kubernetes, a pod's removal from
Service endpoints (so the load balancer stops routing to it) and the container
receiving `SIGTERM` happen **concurrently**, not sequentially — there's a real
window where `SIGTERM` has already fired but some proxies/kube-proxy haven't yet
converged on the updated endpoint list, and requests still land on a pod that's
already shutting down.

```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]
terminationGracePeriodSeconds: 40   # must exceed preStop sleep + app shutdown timeout
```

The correct ordering: **`preStop` hook sleeps first** (giving endpoint removal
time to propagate before the app starts refusing work) **→ `SIGTERM`** (Spring's
graceful shutdown stops accepting new requests, drains in-flight ones) **→ JVM
exits cleanly, or `SIGKILL` after `terminationGracePeriodSeconds` if it hasn't**.
`terminationGracePeriodSeconds` must be comfortably larger than the `preStop`
sleep plus the app's own shutdown timeout — if it isn't, Kubernetes `SIGKILL`s
the process before graceful shutdown finishes, which defeats the entire point and
looks identical to not having configured graceful shutdown at all.

## 6. Kubernetes manifest essentials

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0     # never drop below desired capacity during a rollout
      maxSurge: 1
  template:
    spec:
      terminationGracePeriodSeconds: 40
      containers:
        - name: myservice
          image: registry.example.com/myservice:1.4.2   # pin a tag, never `:latest`
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              memory: "1Gi"       # memory limit == request: avoid surprise OOMKill from bursting
              # no cpu limit, or cpu limit == request — see note below
          readinessProbe:
            httpGet: { path: /actuator/health/readiness, port: 9001 }
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /actuator/health/liveness, port: 9001 }
            initialDelaySeconds: 30
            periodSeconds: 10
          lifecycle:
            preStop:
              exec: { command: ["sh", "-c", "sleep 5"] }
```

A few decisions worth calling out explicitly:

- **`maxUnavailable: 0`** during a rolling update means Kubernetes only takes an
  old pod down after a new one is ready, never dropping below full desired
  replica count — the tradeoff is a rollout briefly runs `replicas + maxSurge`
  pods, which needs headroom in the node pool.
- **Memory `limits` should equal `requests`.** Memory is not compressible the
  way CPU is — a container that bursts past its memory *limit* gets OOMKilled
  outright, so a generous limit with a small request just delays the same crash
  and makes capacity planning harder. Size the request to what the service
  actually needs and set the limit the same.
- **Think hard before setting a CPU `limit` lower than what bursts need.**
  Kubernetes enforces CPU limits via CFS throttling, which can throttle a
  container even when the node has spare CPU sitting idle — a workload doing
  bursty work (JIT compilation just after startup, GC pauses, a request spike)
  can get throttled into visibly worse latency purely from the limit, not from
  actual resource contention. Many teams set CPU `requests` for scheduling and
  either omit the `limits.cpu` entirely or set it well above the request.
- **Readiness on the readiness health group, liveness on the liveness group,**
  each on the separate management port — see `observability.md` §6 for why
  checking dependencies in the liveness probe causes fleet-wide restart storms.
- **Never deploy `:latest`.** An immutable, specific tag means the manifest
  describes exactly what's running; `:latest` makes rollbacks non-deterministic
  and can silently redeploy a different image than what was tested.

## 7. Supply chain and dependency scanning

A microservice's real attack surface is overwhelmingly its dependency tree, not
the code it authors — a typical Spring Boot service pulls in hundreds of
transitive jars, any one of which can carry a CVE its authors haven't patched
yet, or ever. Treat the dependency tree as something to inspect, not something
that's implicitly trusted because it compiled.

```
./gradlew dependencies --configuration runtimeClasspath   # Gradle: full resolved tree
mvn dependency:tree                                          # Maven equivalent
```

Run these when a "why is this transitive version X" question comes up, and
especially before pinning an override — a forced version bump on a shared
transitive dependency can silently break an unrelated library that assumed the
old version's behavior.

Baseline supply-chain hygiene for a JVM service:

- **Automated dependency + container image scanning in CI**, gating the build on
  known-critical CVEs rather than discovering them from a security team's
  quarterly report.
- **A BOM/platform** (Spring Boot's own dependency-management BOM, or an
  internal equivalent) so every module in a multi-module build resolves the same
  version of a shared library — without one, different modules silently drift to
  different transitive versions and you get version-conflict bugs that only show
  up at runtime, not compile time.
- **Reproducible, pinned base images** — a floating `eclipse-temurin:25-jre` tag
  changes contents over time; pin to a digest or a dated tag in anything you
  actually promote to production, and let a controlled process (Dependabot/Renovate
  or equivalent) propose the bump rather than picking it up silently on every
  rebuild.
- **Minimize what ships.** Every dependency you don't use but sits in the jar is
  still attack surface if it's ever loaded reflectively. Layered jars (§3) don't
  reduce this — pruning unused dependencies from the build does.

## Checklist

- [ ] Configuration bound via `@ConfigurationProperties` records with `jakarta.validation` constraints, `@Validated` — fails fast at startup, not at first use
- [ ] `-XX:MaxRAMPercentage` used instead of a hardcoded `-Xmx`
- [ ] `-XX:+ExitOnOutOfMemoryError` and `-XX:+HeapDumpOnOutOfMemoryError` set
- [ ] `-XX:ActiveProcessorCount` set if the container's CPU limit is below the node's core count
- [ ] Dockerfile is multi-stage; build tools never ship in the final image
- [ ] Spring Boot layered jars extracted and copied in dependency-stability order for cache efficiency
- [ ] Base image choice deliberate — JRE default, distroless/alpine only after weighing the debuggability tradeoff
- [ ] Container runs as a non-root user
- [ ] `ENTRYPOINT` in exec form — JVM is PID 1 and receives `SIGTERM` directly
- [ ] AppCDS or AOT cache adopted for startup time; native image only if startup latency is the dominant cost, with its throughput/build-complexity tradeoff accepted knowingly
- [ ] `preStop` sleep precedes `SIGTERM`; `terminationGracePeriodSeconds` exceeds `preStop` sleep + app shutdown timeout
- [ ] Rolling update strategy keeps `maxUnavailable: 0`; memory `limits` equal `requests`; CPU `limits` set deliberately, not by default
- [ ] Readiness and liveness probes point at the correct, separate health groups on the management port
- [ ] Image tags are immutable and specific — never `:latest` — in any manifest that reaches production
- [ ] Dependency tree and container images scanned in CI; a BOM/platform keeps transitive versions aligned across modules
