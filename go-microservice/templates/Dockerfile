# Multi-stage build for a Go service.
#
# Produces a ~2MB image from a static binary on distroless. The comments explain
# the choices that matter; see the go-microservice skill's
# references/packaging-deploy.md for the reasoning in full.

# ---- build stage -------------------------------------------------------------
FROM golang:1.26 AS build

WORKDIR /src

# Copy manifests FIRST. This layer is cached until dependencies actually change,
# so editing source code doesn't re-download the module graph.
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .

ARG VERSION=dev
ARG COMMIT=unknown
ARG TARGETOS=linux
ARG TARGETARCH=amd64

# CGO_ENABLED=0  -> a fully static binary that runs on distroless/scratch, and
#                   uses Go's pure-Go DNS resolver rather than the system one.
#                   (With CGO on, musl-based images hit real DNS edge cases.)
# -trimpath      -> strips local filesystem paths; reproducible builds.
# -s -w          -> drop the symbol table and DWARF; smaller binary.
# -X main.…      -> stamp version/commit so /version and startup logs are useful.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build \
      -trimpath \
      -ldflags="-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" \
      -o /out/app \
      ./cmd/myservice

# ---- runtime stage -----------------------------------------------------------
# distroless/static gives us CA certificates, tzdata, /etc/passwd and a nonroot
# user — with no shell and no package manager, so the attack surface is tiny.
#
# Alternatives:
#   scratch                  0 bytes, but YOU must COPY ca-certificates.crt or
#                            every HTTPS call fails with x509: unknown authority
#   alpine                   has a shell for debugging; musl, so only safe with
#                            CGO_ENABLED=0
#   debian:*-slim            when you genuinely need glibc + CGO
FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=build /out/app /app

# Never run as root. distroless:nonroot ships uid/gid 65532.
USER nonroot:nonroot

EXPOSE 8080 9090

# Exec form (a JSON array), NOT shell form. With shell form the process tree is
# `sh -c app`, so SIGTERM goes to sh and the app never shuts down gracefully —
# every deploy then drops in-flight requests and waits for SIGKILL.
ENTRYPOINT ["/app"]

# NOTE ON HEALTHCHECKS
# `HEALTHCHECK CMD curl ...` cannot work here: there is no curl and no shell.
# Prefer the orchestrator's HTTP probe (Kubernetes httpGet against /healthz and
# /readyz). If you need a container-level check, compile a subcommand into the
# binary and use:
#   HEALTHCHECK --interval=10s --timeout=2s CMD ["/app", "healthcheck"]

# RUNTIME ENVIRONMENT (set these in your deployment, not here)
#   GOMEMLIMIT=900MiB   ~90% of the container memory limit. The GC is otherwise
#                       ratio-based (GOGC) and knows nothing about your cgroup,
#                       so a live-heap spike gets you OOMKilled before the next
#                       collection. This is the cheapest OOMKill prevention there is.
#
#   GOMAXPROCS          DO NOT SET on Go >= 1.25. The runtime now reads the
#                       cgroup CPU *limit* (not requests) and re-reads it if the
#                       limit changes. Setting it manually disables that.
#                       This also makes uber-go/automaxprocs redundant — delete it.
