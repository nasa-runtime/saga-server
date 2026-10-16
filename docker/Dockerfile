FROM docker.io/library/rust:1.94-alpine@sha256:77237dd363a0b127bb5ef532c2d64c0deb380b738e43a9c4bdac73398d6d0a08 AS builder
RUN apk add --no-cache musl-dev
WORKDIR /build/saga-server
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --locked --release --bin saga-server -j 2

FROM docker.io/library/alpine:3.23@sha256:85fe1e81d6758c208f3e1eed4338a1997e19d4be002d4dd32d3100c9a8c010a0
ARG APP_VERSION=1.0.0
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="saga-server" \
    org.opencontainers.image.source="https://github.com/nasa-runtime/saga-server" \
    org.opencontainers.image.description="Standalone NASA Saga orchestrator: register workflows without server restarts, with multi-registry discovery and durable recovery" \
    org.opencontainers.image.licenses="MIT OR Apache-2.0" \
    org.opencontainers.image.version="${APP_VERSION}" \
    org.opencontainers.image.revision="${SOURCE_REVISION}"
RUN apk add --no-cache ca-certificates \
    && addgroup -S -g 10001 saga \
    && adduser -S -D -H -u 10001 -G saga -s /sbin/nologin saga
WORKDIR /app
COPY --from=builder /build/saga-server/target/release/saga-server /app/saga-server
COPY zcf/ ./zcf/
COPY LICENSE-MIT LICENSE-APACHE /usr/share/licenses/saga-server/
USER 10001:10001
EXPOSE 2070 9464
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:2070/readyz || exit 1
ENTRYPOINT ["/app/saga-server"]
