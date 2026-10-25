# saga-server

[中文](README.md)

[Complete Docker scenario commands](docker/README.md): MySQL/PostgreSQL, direct HTTP, single/dual Nacos, Consul, mixed registries, two replicas, custom ports, metrics, file logs, maintenance and image replacement. Database choice is independent of registry choice; adding a workflow does not require maintenance commands.

MySQL audit triggers require additional creation privileges when binary logging is enabled and `log_bin_trust_function_creators=0`. Database-scoped grants alone may not initialize an empty database. A DBA can initialize the empty coordinator schema with a stable schema-management account, then run the service with the database-scoped account; retain the triggers’ `DEFINER` and its required table privileges. See the [complete initialization commands](docker/README.md#mysql-首次初始化与触发器权限). The application does not change global MySQL settings.

`saga-server` is a standalone NASA Saga orchestrator. Operators run the image and mount deployment configuration; business services publish workflow definitions, implement participant steps and start Sagas. Each business project can use the same coordinator image without assembling a server from NASA source.

The entry point uses `#[nasa::application]`. napp manages the database, Saga runtime, Outbox, HTTP listener, logging, named discovery connections and the nafana metrics exporter. The application uses `nasa 2.0.5` from crates.io; it does not duplicate the coordination engine or storage implementation.

The coordinator stays running when an already trusted business service introduces a workflow. Managed clients publish signed definitions and step capabilities, then submit transaction instance IDs. This does not require editing server YAML, reloading configuration or restarting saga-server.

Java, Go and Rust services can keep separate registries while sharing one coordinator cluster across multiple Nacos and Consul environments. NASA clients select a connection with `qualifier`; clients in any language can also use a fixed HTTP URL. Business admission and capability/result recovery use separate registrations, so losing business readiness does not cut off recovery. Cross-language operation requires the same Saga protocol contracts. See the [multi-registry configuration guide](docs/discovery.md).

## Architecture and guarantees

- One binary supports MySQL and PostgreSQL, selected by configuration.
- The database holds instances, journals, Inbox, Outbox, durable timers, the dynamic Definition Catalog and audit facts.
- Workflow owners publish immutable Ed25519 signed definitions. Participants register capabilities and renew leases. Adding a workflow within existing trust grants requires no coordinator configuration change, image rebuild or restart.
- Local transactions, at least once delivery, Inbox deduplication, explicit compensation and result resolution provide recoverable coordination. Existing instances retain their original definition version and digest.
- HTTP HMAC authentication, shared database replay protection, tenant/workflow permissions and participant address allowlists constrain access.
- Replicas share one database and logical service identity, with distinct restart stable replica identities. Leases and fencing prevent stale authority from continuing state transitions.

This binary provides HTTP control and command/result APIs. It does not assemble the framework's gRPC, Kafka or Redis Streams transports. It does not execute business steps, generate compensation logic, provide distributed ACID or physical exactly once execution, or resolve resource contention between independent Sagas.

## Introduce workflows while the coordinator stays running

The workflow owner declares a complete definition with `#[nasa::saga_workflow]`; the managed client signs and publishes its `workflow`, `definition_version`, ordered steps, compensation and timeout contracts. Participants register reachable step capabilities and renew their leases. The coordinator activates a valid definition when the required capabilities satisfy the `validated` policy. A subsequent client request supplies `saga_id` for a particular transaction instance. Instance IDs and business steps are not preloaded in server YAML.

Business services can deploy new workflows independently. Existing instances retain their frozen definition version and digest, and a definition cannot be changed in place under the same version. Adding an untrusted identity, signing key or network range still requires a corresponding trust configuration change. A precise workflow allowlist requires authorization updates for new names; use the explicit trusted owner scope for continuous workflow onboarding. See the [dynamic registration contract](docs/integration.md#流程动态上报与服务端持续运行).

The template uses `workflows: ["*"]` for a trusted owner within explicitly authorized tenants; ownership, signature and participant network checks still apply. A successful `/readyz` response does not establish that a particular new workflow is active. Confirm its definition lifecycle and capability renewals before starting instances, as described in [dynamic catalog monitoring](docs/monitoring.md#动态目录与新流程接入). The catalog synchronizes while the coordinator runs.

## Prepare configuration

Keep `compose.yml`, `application.yml` and `.env` together in one deployment directory. With a source checkout, use its root directory and copy the three templates below; existing deployments must keep their own files. Container-only operators can download the required files using the [Docker Hub guide](docker/README.md) without installing Rust.

```sh
git clone --branch release https://github.com/nasa-runtime/saga-server.git
cd saga-server
```

The image loads `/app/zcf/application.yml` and imports `${SAGA_YML:/etc/saga-server/*.yml}`. Files in each glob are merged in natural filename order; later files override earlier files and lists are replaced. Missing required imports or credentials prevent startup. Local configuration is loaded at startup and changes require a restart; the dynamic workflow catalog and participant leases are synchronized separately.

```sh
cp docker/compose.yml compose.yml
cp docker/env.example .env
cp examples/config/10-security.yml application.yml
chmod 600 .env
chmod 644 application.yml
```

Update the sample tenant `system`, callers `order-api`/`order-worker`, signing key mapping and participant address allowlist to match your deployment. Each result producer needs its own `producer_credentials` entry. The template grants the trusted definition owner `workflows: ["*"]` within its explicit tenants, allowing new workflow names without server configuration changes. This scope does not restrict workflow names; definition ownership checks still apply. Grant it only to trusted workflow owners.

Fill the copied `.env` with real values:

```dotenv
SAGA_DATABASE_DRIVER=mysql
SAGA_DATABASE_URL=mysql://saga_user:URL_ENCODED_PASSWORD@mysql.internal:3306/saga_control
SAGA_REPLICA_ID=saga-server-0
SAGA_SERVICE_ID=saga-server
SAGA_ENVIRONMENT=production
SAGA_CLUSTER=orders
SAGA_LOG_PATH=
SAGA_COMMAND_KEY=REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS
SAGA_RESULT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_PAGE_TOKEN_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_CLIENT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_WORKER_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_DEFINITION_PUBLIC_KEY=REPLACE_WITH_BASE64_SPKI_ED25519_PUBLIC_KEY
```

Generate independent HMAC keys with `openssl rand -hex 32`. The page token key must contain at least 32 bytes and be identical across coordinator replicas. The signing public key is Base64 encoded SPKI DER, not PEM text or a raw 32 byte key. Workflow owners hold the matching Base64 encoded PKCS8 DER private key; never mount this private key into the coordinator. `ncrypto::generate_ed25519_key_pair()` produces both encodings. An OpenSSL alternative:

```sh
umask 077
openssl genpkey -algorithm ED25519 -out definition-private.pem
openssl pkey -in definition-private.pem -pubout -outform DER -out definition-public.der
openssl base64 -A -in definition-public.der
chmod 600 .env
```

Use the public key output as `SAGA_DEFINITION_PUBLIC_KEY`. Keep credentials outside version control. The database must already exist. The application account needs the DML and schema creation/validation privileges required by the managed components. Use a dedicated account and database. To use PostgreSQL:

```dotenv
SAGA_DATABASE_DRIVER=postgresql
SAGA_DATABASE_URL=postgres://saga_user:URL_ENCODED_PASSWORD@postgres.internal:5432/saga_control
```

## Start with Docker Compose

For a new MySQL database, complete the [audit trigger initialization](docker/README.md#mysql-首次初始化与触发器权限) before starting with the regular runtime account.

The copied [Compose template](docker/compose.yml) uses the adjacent `application.yml` and `.env`, and connects to your existing database. Choose this or the alternative `docker run` deployment; do not start both on host port 2070 or with the same replica identity.

Use Docker Compose 2.30.0 or newer. Write `.env` as `KEY=value`, without wrapping quotes or inline comments. The template uses `raw` format so credential values reach the container unchanged, matching `docker run --env-file`. A deployment platform can inject the environment directly without an environment file.

```sh
docker compose up -d
docker compose ps
docker compose logs --tail 100 saga-server
curl --fail http://127.0.0.1:2070/readyz
```

Use `docker compose stop` only for planned maintenance or upgrades. Restart with the original database, replica identity and trust configuration. New business workflows do not require stopping the coordinator. The monitoring Compose below already includes the coordinator, so choose that stack directly when monitoring is needed.

## Run with Docker

Use the `.env` and `application.yml` prepared above with the actual database, stable replica identity and keys. The image runs as UID/GID `10001:10001`. On Linux, create a dedicated writable log directory:

```sh
sudo install -d -o 10001 -g 10001 -m 0750 logs
```

```sh
docker run -d --name saga-server --restart unless-stopped --stop-timeout 70 \
  -p 127.0.0.1:2070:2070 \
  --env-file ./.env -e SAGA_LOG_PATH=/usr/local/logs/saga-server \
  -v "$PWD/application.yml:/etc/saga-server/application.yml:ro" \
  -v "$PWD/logs:/usr/local/logs/saga-server" \
  nasaruntime/saga-server:1.0.0
```

Check `http://127.0.0.1:2070/readyz` for business readiness and use `docker logs -f saga-server` for logs. The command enables file logging, overriding the empty log path in `.env`; Docker Desktop must allow sharing the log directory. Persistent coordination data lives in the external MySQL/PostgreSQL database. Keep that database, configuration, keys and replica identity when recreating the container.

Direct HTTP addressing is the default and requires no registry. The loopback mapping is host-local. See the [Docker Hub guide](docker/README.md) for complete registry, networking, read-only root, log rotation and maintenance commands.

## Start and query a Saga

First deploy a workflow owner and step participants using the [participant configuration](docs/integration.md#参与方与流程拥有方). They provide persistent business processing, signed definitions and renewable capabilities. The coordinator image has no built-in `order_checkout` workflow or business steps. The following example assumes version `1` is published and accepts `order_id` and `quantity` as the first step's input.

Construct requests using the [HTTP signing protocol](docs/integration.md#http-地址与认证). The default base path is `/_nasa/saga`:

1. Use `order-worker` with its `SAGA_WORKER_KEY` to call `GET /registry/definitions/system/order_checkout/1` and confirm activation.
2. Use `order-api` with its `SAGA_CLIENT_KEY` and `start` permission to call `POST /instances`. Supply stable instance, business and trigger identities and input matching the workflow contract; see the [request fields](docs/integration.md#发起与查询).
3. Use a caller with `read` permission to call `GET /instances/system/order-1001` and inspect the final status.

Each caller must use its own key. Sign the actual request path and raw body with a fresh timestamp and nonce for each attempt. Do not follow redirects that change the signed target.

HTTP 200 with `Committed` or `Duplicate` acknowledges durable creation; query the instance to determine the eventual business outcome. On an ambiguous response, keep the same instance, business key, trigger ID and input, and generate a new signature before retrying. See the [API contract](docs/integration.md#接口与失败语义).

## Named registry connections

The binary enables Nacos, Consul and Kubernetes discovery providers. `discovery.connections` holds named
connections; `discovery.registrations` independently selects publication targets using `qualifier`.
`primary` is the case sensitive default. An unknown qualifier or unavailable target never falls back to
another environment. Connections and publication policy are frozen at startup.

For Nacos, set:

```dotenv
APP_PROFILE=nacos
NACOS_SERVER_ADDR=http://nacos.internal:8848/nacos/
NACOS_NAMESPACE=public
NACOS_GROUP=SAGA_GROUP
NACOS_USERNAME=YOUR_NACOS_USERNAME
NACOS_PASSWORD=YOUR_NACOS_PASSWORD
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

Use Nacos 3 HTTP API access, not the console or SDK gRPC endpoint. Publish Docker port `12070:2070` on
the advertised host address. `LOCAL_NETWORK_IP` is not used implicitly. The profile registers
`saga-server` and `saga-server-recovery`; both names follow `SAGA_SERVICE_ID`. The former uses business
eligibility, while the latter remains reachable for authenticated capability renewal and result recovery.

`APP_PROFILE=multi-nacos` adds a `secondary` connection. Configure `SECONDARY_NACOS_SERVER_ADDR`,
`SECONDARY_NACOS_NAMESPACE`, `SECONDARY_NACOS_GROUP`, `SECONDARY_NACOS_USERNAME`,
`SECONDARY_NACOS_PASSWORD`, `SECONDARY_REGISTER_IP` and `SECONDARY_REGISTER_PORT`. Each connection
publishes both business and recovery registrations, with its own reachable endpoint and credentials.

Append the second connection to the first Nacos configuration and replace its `APP_PROFILE`:

```dotenv
APP_PROFILE=multi-nacos
SECONDARY_NACOS_SERVER_ADDR=http://nacos-secondary.internal:8848/nacos/
SECONDARY_NACOS_NAMESPACE=public
SECONDARY_NACOS_GROUP=SAGA_GROUP
SECONDARY_NACOS_USERNAME=YOUR_SECONDARY_NACOS_USERNAME
SECONDARY_NACOS_PASSWORD=YOUR_SECONDARY_NACOS_PASSWORD
SECONDARY_REGISTER_IP=192.168.20.20
SECONDARY_REGISTER_PORT=22070
```

Map both reachable endpoints to the same container listener, for example `192.168.10.20:12070:2070` and `192.168.20.20:22070:2070`. Those IPs must belong to the host or be provided by trusted gateways. Each environment discovers its own reachable endpoint while sharing the same Saga database.

`APP_PROFILE=consul` uses `CONSUL_API_ADDR`, a fixed `CONSUL_AGENT_ADDR`, `CONSUL_DATACENTER`, optional
`CONSUL_TOKEN`, and `SAGA_REGISTER_IP` / `SAGA_REGISTER_PORT`. TTL checks follow local eligibility.
For mixed providers, omit the profile and supply a complete discovery block in mounted configuration.
See [configuration examples and boundaries](docs/discovery.md) and the [profiles](zcf/application-multi-nacos.yml).

For a single Consul backend, replace the profile and advertised endpoint with:

```dotenv
APP_PROFILE=consul
CONSUL_API_ADDR=http://consul.internal:8500
CONSUL_AGENT_ADDR=http://consul-agent.internal:8500
CONSUL_DATACENTER=dc1
CONSUL_TOKEN=YOUR_CONSUL_TOKEN
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

The four built-in registration names preserve numeric port types when using their environment variables.
For additional registration names, write ports as YAML integers and policies such as `startup_required`
and `readiness_critical` as YAML booleans. Quoted strings and arbitrary environment placeholders do not
automatically receive those conversions. Registry credentials and service names remain strings.

## Multiple registries sharing one coordinator cluster

Replicas share the coordinator database and trust configuration; registries do not replicate Saga state
or elect task owners. Business services can retain their own `primary` registry and add a `saga-infra`
connection. In `saga.discovery`, select it with `qualifier: saga-infra` and bind separate coordinator and
recovery service aliases. New Saga clients use the business alias; participant Registry clients and
result delivery use the recovery alias. Identity metadata and address allowlists remain mandatory.

```mermaid
flowchart LR
    Java[Java services] -.Find business or recovery entry.-> Nacos[Nacos environment]
    Go[Go services] -.Find business or recovery entry.-> Consul[Consul environment]
    Server[saga-server replicas] -.primary registration.-> Nacos
    Server -.consul-go registration.-> Consul
    Java -->|Signed HTTP| Server
    Go -->|Signed HTTP| Server
    Server --> DB[(Shared coordinator database)]
    Server -->|Capability routed commands| Workers[Reachable participant endpoints]
    Workers -->|Renewals and results| Server
```

Registries locate coordinator entry points. Requests use the same durable facts, definitions and permissions
after reaching the coordinator; publishing to multiple registries does not duplicate Sagas or databases.
Commands use registered participant capabilities, without searching another registry for a matching service
name. Each business environment must reach the coordinator, and the coordinator must reach its participants.

Import the [mixed Nacos/Consul configuration](examples/config/discovery-mixed.yml) and follow the
[deployment steps](docs/discovery.md#consul-与混合后端). `primary` and `consul-go` are connection names;
`coordinator` and `recovery` are service aliases within each connection; `SAGA_SERVICE_ID` is the logical
identity checked by the protocol. Client connection names may differ, but must select the correct backend
scope and trust the same coordinator identity.

Kubernetes publication uses native Pods, selector Services and controller EndpointSlices. The adapter
is read only and does not generate Saga identity metadata. Use a trusted full Service DNS URL for Saga
clients where native endpoints lack that metadata. Recovery must not share a readiness gate that removes
all endpoints after capability expiry; two Services selecting the same Pods do not provide independent
readiness by themselves.

### Independent Nacos clusters for Java, Go and Rust

For fixed URL access, expose one trusted coordinator entry point such as `https://saga.internal/_nasa/saga`. Java, Go and Rust keep their existing Nacos registration, configuration centers and internal service discovery. Saga traffic uses reachable HTTP endpoints.

```mermaid
flowchart LR
    Java[Java services] -.discovery.-> NJ[Java Nacos]
    Go[Go services] -.discovery.-> NG[Go Nacos]
    Rust[Rust services] -.discovery.-> NR[Rust Nacos]
    Java -->|Signed HTTP| Entry[saga.internal]
    Go -->|Signed HTTP| Entry
    Rust -->|Signed HTTP| Entry
    Entry --> A[saga-server-0]
    Entry --> B[saga-server-1]
    A --> DB[(Shared coordinator database)]
    B --> DB
    A -->|Capability routed commands| Workers[Participant endpoints]
    B -->|Capability routed commands| Workers
```

1. Run coordinator replicas against the same database and expose an internal load balancer. Nacos can remain disabled on the coordinators, or they can register in a separate infrastructure Nacos environment. Business services using the URL do not need access to that registry.
2. Set each initiating client's Saga base URL to `https://saga.internal/_nasa/saga` and use the start and query APIs. A managed Rust client sets `saga.client.orchestrator_discovery_ref` to this full URL.
3. Point participant capability registration, workflow publication and result delivery to the same entry point. Merge the following overrides into a complete Rust participant configuration; this fragment is not a standalone application configuration:

```yaml
saga:
  definition_catalog:
    registry_client:
      discovery_ref: https://saga.internal/_nasa/saga
  transport:
    command_result:
      http:
        orchestrator_discovery_ref: https://saga.internal/_nasa/saga
        advertised_endpoint: https://rust-order-0.internal
```

`advertised_endpoint` is a participant origin reachable from the coordinator, without `/_nasa/saga`. The capability registration includes the effective Saga path separately. Each replica uses its own `replica_identity` and correct endpoint. Commands must reach the selected participant capability or backends explicitly sharing its persistent deduplication and capability contracts; arbitrary routing to an incompatible replica is unsafe. A trusted proxy can terminate TLS while preserving the actual Saga path.

The coordinator sends commands to registered, leased capability endpoints and does not need to subscribe to the Java, Go or Rust Nacos clusters. Connectivity must work in both directions: participants reach the coordinator entry point, and coordinators reach participant endpoints. Access to Nacos alone does not establish these network paths.

Set the coordinator's imported `saga-participants` address policy to the real endpoints, for example:

```yaml
saga:
  transport:
    address_policies:
      saga-participants:
        http_schemes: [https]
        http_hosts: [java-order-0.internal, go-stock-0.internal, rust-order-0.internal]
        http_ports: [443]
```

This replaces each list in that policy, so include every host and port that must remain allowed. The policy only authorizes network destinations. Each participant also needs an independent secret, a result identity in `producer_credentials`, and a Registry caller with the correct tenant/workflow scope in the [authorization configuration](examples/config/10-security.yml). Workflow owners additionally need a definition signing public key mapping; only the public key belongs on the coordinator.

### Java and Go protocol integration

| Business responsibility | Required contract |
| --- | --- |
| Start and query Sagas | Follow the [HTTP API contract](docs/integration.md): JSON, HMAC, caller identity, stable business idempotency identifiers and native HTTP status handling |
| Publish workflow definitions | Produce canonical DefinitionArtifacts, digests and Ed25519 signatures matching the NASA contract, then publish through the authorized Registry |
| Execute business steps | Register and renew capabilities, authenticate commands, persist the Inbox and business effects, implement the step's declared cancellation/resolution/compensation semantics, and deliver results through an Outbox or equivalent durable mechanism |

This project provides Rust NASA integration examples and does not bundle Java or Go participant SDKs. Java/Go HTTP clients can implement start and query operations. A full participant requires a protocol adapter; registering an existing business REST endpoint alone does not make it a Saga step. Nacos registration does not provide Saga deduplication, compensation or capability semantics.

Once their protocol adapters are in place, steps in one workflow can use different languages. Each step declares its owner. Identical service names in separate Nacos environments do not establish the same Saga identity. Configure caller identities, tenants, workflow permissions and keys explicitly on the coordinator; a Nacos namespace does not automatically become a Saga tenant.

### Coordinator replicas and load balancing

Use the same `SAGA_DATABASE_URL`, `SAGA_SERVICE_ID`, authorization settings, trust material and page token key across coordinator replicas. Set distinct, restart stable identities such as `SAGA_REPLICA_ID=saga-server-0` and `saga-server-1`. Mount configuration into every replica; local configuration changes require restarting each replica. Deploy the database for high availability and avoid a single load balancer failure point.

Keep these traffic paths distinct instead of applying one `/readyz` rule to every request:

| Traffic | Routing requirement |
| --- | --- |
| New Sagas and ordinary business operations | Route to coordinators passing `/readyz`; stop admitting new work when they are unready |
| `POST /_nasa/saga/registry/capabilities` | Preserve a path to replicas eligible for recovery after startup or capability expiry; the component still authenticates callers and validates capabilities |
| `POST /_nasa/saga/results` | Preserve delivery to replicas eligible for recovery; the component determines whether Catalog, definition and producer trust still permit convergence |

With a built-in discovery profile, check the recovery pool with `/discovery/eligible/primary-recovery`
and the business pool with `/readyz`. The eligibility probe reports local authority without querying the
registry; use `napp_discovery_registration_ready` to observe remote publication as well. `/healthz` only
checks liveness and cannot replace recovery eligibility. Fixed URL deployments with discovery disabled do
not expose the eligibility probe: retain a separate recovery path, use liveness and platform shutdown
withdrawal, and preserve Saga's per-request lifecycle, authentication and transaction checks.

If every coordinator becomes unready due to missing capability routes, blocking all Registry traffic
would prevent lease renewal and readiness recovery. Business and recovery addresses may share one HTTP
listener; the recovery address grants no extra permissions and cannot bypass admission checks for new
Sagas. Shutdown revokes eligibility and registrations before draining work and closing connections.

HTTP signatures cover the actual path and raw body. Forward `x-saga-*` headers unchanged, preserve Saga paths and JSON bytes, and disable blind POST retries. On an ambiguous outcome, the caller preserves the original business identity and content but generates a new timestamp, nonce and signature. Replaying the original HTTP request through a proxy triggers replay rejection. Synchronize node clocks within the 30 second signature window, and use HTTPS certificates trusted by the caller.

After a replica fails, already claimed work may wait for lease expiry before takeover. The default timer lease is 60 seconds; `timer_poll_interval_ms: 500` does not guarantee a 500 ms recovery time. Scrape each replica separately and deduplicate shared database metrics as described in the [monitoring guide](docs/monitoring.md).

MySQL Outbox protects dispatch order with a database session lock. A paused process or half-open network can leave that session alive; another replica cannot steal its lock. Delivery resumes when the original process recovers or its database session closes after the process exits. A timer lease does not release this lock. PostgreSQL Outbox instead uses a durable owner lease with fencing. Recovery therefore depends on the storage backend and failure mode. Docker health checks alone do not terminate an unresponsive process; deployment operators must provide a corresponding failure-handling policy.

### Registry isolation and failure boundaries

`startup_required` controls initial confirmation; `readiness_critical` controls whether a lost registration
makes the whole application unready. Built-in profiles require initial success but isolate runtime failures.
Observe `napp_discovery_*` metrics and per-registration eligibility probes. Shutdown withdraws registrations
before draining business work and closing discovery connections; unknown outcomes require checking residuals.

Temporary connection loss can recover while the original record and ownership remain valid. A missing record
does not trigger automatic registration, because it may represent an intentional administrative withdrawal.
Check remote records and administrative intent, then restart the coordinator replica in a controlled manner
to establish a new owner if needed. Nacos client API authentication and admin API authentication are separate;
the configured account must be able to inspect ownership as well as register and renew instances.

Registry access does not establish bidirectional application connectivity or tenant authorization. Use separate
coordinator databases for environments requiring complete data and trust isolation. Remove the old
`rest_discovery` root when using `discovery`; even a disabled legacy root cannot coexist with the new one.

## Prometheus and Grafana

The `grafana` feature uses **nafana** and napp's managed exporter. `9464/metrics` serves application, HTTP and Outbox metrics. `2070/_nasa/saga/metrics` serves persistent Saga state, terminal latency quantiles and timer backlog. Both are internal monitoring endpoints; restrict access with network policy or a proxy. The native Saga metrics route does not require business HMAC authentication.

When discovery is enabled, the nafana endpoint also exports `napp_discovery_*` metrics per connection and
registration. Local eligibility and confirmed remote registration are separate observations. The bundled
dashboard and alerts cover Saga, Outbox and scrape status; add per-registration views in your monitoring
platform as described in the [discovery metrics guide](docs/monitoring.md#发现连接与注册目标).

With root-level `application.yml` and `.env` ready:

This stack already includes the coordinator. Choose it instead of the standalone container or base Compose deployment to avoid port and replica identity conflicts.

```sh
export GRAFANA_ADMIN_PASSWORD='REPLACE_WITH_A_STRONG_PASSWORD'
docker compose -p saga-monitoring -f docker/monitoring/compose.yml up -d
```

Grafana: `http://127.0.0.1:3000`, user `admin`, your configured password, dashboard `Saga / Saga Server`. Prometheus: `http://127.0.0.1:9090`. The Compose stack uses independent persistent volumes and does not create the business database. Set the static `saga-state` scrape labels to match `SAGA_ENVIRONMENT`, `SAGA_CLUSTER` and `SAGA_SERVICE_ID` (sample labels are `local/local/saga-server`).

Scrape every replica directly. Database backed gauges and counters are shared facts: aggregate with `max` over replicas of the same database, not `sum`. Different databases need different cluster or service labels. Lifetime quantiles are not sliding window quantiles and cannot be added or averaged. `up=1` means scrape success, not business readiness; monitor `/readyz` independently.

`nasaga_stage_duration_seconds` exports process histograms for five fixed stages, totaling 85 series, with counters reset on process restart. The dashboard uses persistent lifecycle quantiles from database facts, which have a different scope. Nonzero `nametrics_samples_rejected_total` requires checking metric capacity. Prometheus rules cover scrape failures, manual intervention and timer backlog; notification delivery requires your Alertmanager or Grafana contact points.

Detailed [monitoring configuration](docs/monitoring.md) and [business integration](docs/integration.md) include endpoint, authentication, permissions and failure semantics. The upstream [Saga production guide](https://github.com/nasa-runtime/nasa-runtime-rust/blob/master/docs/saga-production.md) defines participant and workflow contracts. Successful start returns HTTP 200 with `Committed` or `Duplicate`; completion is queried separately. Errors keep native HTTP status codes and may have an empty body. On an ambiguous timeout, retry the same business intent with a fresh HMAC nonce instead of creating another Saga identity.

## Build the image

Source and image builds use `nasa 2.0.5` from crates.io, with the full dependency graph pinned by `Cargo.lock`. Use Rust 1.94 or later:

```sh
cargo build --locked --release
bash docker/build-image.sh
```

Docker files, build/publish scripts and Compose deployment files live in `docker/`; GitHub Actions workflows remain in `.github/workflows/`. See the [image overview](docker/README.md).

The image script uses the service directory as its build context. `SAGA_IMAGE` overrides the output tag.
The build environment must be able to download the locked registry dependencies or have a matching Cargo cache.

This project distributes a standalone service image and sets `publish = false`. Keep `Cargo.lock` with source deployments so local and image builds use the same component versions.

The Dockerfile uses digest pinned Docker Hub official `rust:1.94-alpine` and `alpine:3.23` images. The runtime contains the executable, default configuration, CA certificates and licenses. Build for `linux/amd64` (x86-64/x64) or `linux/arm64` using an appropriate builder; business credentials and database data do not belong in the image.

License: [MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE).
