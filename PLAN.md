# K3s Platform: Unified Configuration Plan

## Overview

This document outlines the plan to consolidate all Kubernetes deployment complexity into a single `apps.yaml` configuration file with environment-aware CLI tooling. The goal is Docker Compose-like simplicity while maintaining full power of KEDA, HAProxy/Traefik, NetworkPolicies, and scale-to-zero.

## Current State

### Problems
1. **Inconsistent technology stack**: Traefik (local/dev) vs HAProxy (GCP) requires different manifest structures
2. **Multiple overlay files**: `k8s/overlays/{local,dev,gcp}/` with duplicated/similar configuration
3. **Scattered configuration**: Apps defined in `apps.yaml`, but details spread across kustomization patches, separate YAML files
4. **Manual manifest management**: Traditional apps like FastAPI require hand-crafted Deployments, Services, Ingress, HPAs
5. **No unified security model**: NetworkPolicies only generated for serverless functions

### What Works Well
- `k3sfn` CLI for serverless: Auto-generates K8s manifests from Python decorators
- `apps.yaml` as single source of truth for deployment types
- ArgoCD for GitOps deployment

---

## Proposed Architecture

### Three CLI Tools

| Tool | Purpose | Scope |
|------|---------|-------|
| `k3sfn` | Serverless functions | Functions with `@http_trigger`, `@queue_trigger`, `@schedule_trigger` |
| `k3sapp` | Traditional apps | Dockerfile-based services with custom entrypoints |
| `k3scompose` | Docker Compose projects | Multi-container apps defined in docker-compose.yaml |

All three tools read from `apps.yaml` and generate environment-specific Kubernetes manifests.

---

## Apps.yaml Schema v2

### Root Structure

```yaml
# apps.yaml - K3s Platform Configuration v2
version: "2"

# Global settings applied across all environments
defaults:
  namespace: apps
  registry:
    local: "registry.localhost:5111"
    dev: "registry.localhost:5111"
    gcp: "us-central1-docker.pkg.dev/${PROJECT_ID}/k3s-platform"
  ingress:
    local: traefik
    dev: traefik
    gcp: haproxy

# Environment-specific overrides
environments:
  local:
    domain: "localhost"
    tls: false
  dev:
    domain: "localhost"
    tls: false
    debug: true
  gcp:
    domain: "${GCP_DOMAIN}"
    tls: true
    tls_secret: "letsencrypt-prod"

# Helm charts (third-party services)
helm:
  - name: valkey
    # ...

# Serverless functions
serverless:
  - name: serverless-example
    # ...

# Traditional container apps
apps:
  - name: fastapi
    # ...

# Docker Compose projects
compose:
  - name: monitoring-stack
    # ...

# Helm repository URLs
repositories:
  bitnami: oci://registry-1.docker.io/bitnamicharts
  kedacore: https://kedacore.github.io/charts
```

---

## Detailed Type Schemas

### 1. Helm Charts

```yaml
helm:
  - name: valkey                           # Required: Unique identifier
    chart: bitnami/valkey                  # Required: Chart reference
    version: "5.0.10"                      # Required: Chart version
    namespace: apps                        # Optional: Target namespace (default: from defaults)
    values: apps/valkey/values.yaml        # Optional: Values file path
    enabled: true                          # Optional: Enable/disable (default: true)

    # Environment-specific overrides
    local:
      values: apps/valkey/values-local.yaml
    dev:
      values: apps/valkey/values-dev.yaml
    gcp:
      values: apps/valkey/values-gcp.yaml

    # Wait for dependencies before installing
    depends_on:
      - name: cert-manager
        type: helm
```

### 2. Serverless Functions (k3sfn)

```yaml
serverless:
  - name: serverless-example               # Required: App name (used in k3sfn CLI)
    path: apps/serverless-example          # Required: Path to functions directory
    namespace: apps                        # Optional: Target namespace
    enabled: true                          # Optional: Enable/disable

    # Build configuration
    build:
      dockerfile: Dockerfile               # Optional: Dockerfile path (default: Dockerfile)
      context: .                           # Optional: Build context (default: app path)
      args:                                # Optional: Build arguments
        PYTHON_VERSION: "3.12"

    # Default resources for all functions (can be overridden per-function via decorators)
    resources:
      memory: "256Mi"
      cpu: "100m"
      memory_limit: "512Mi"

    # Default scaling for all functions (can be overridden per-function via decorators)
    scaling:
      min_instances: 0                     # Scale to zero
      max_instances: 10
      cooldown_period: 300

    # Security defaults for all functions
    security:
      visibility: private                  # public | internal | private | restricted
      network_policy: true                 # Generate NetworkPolicy
      service_account: default
      pod_security_context:
        run_as_non_root: true
        run_as_user: 1000

    # Environment variables for all functions
    environment:
      LOG_LEVEL: INFO

    # Secrets to mount
    secrets:
      - name: api-credentials
        mount_path: /secrets/api

    # Environment-specific configuration
    local:
      port_base: 8081
      live_update: true
      scaling:
        min_instances: 1                   # Keep 1 running in local dev
    dev:
      port_base: 8081
      live_update: true
      environment:
        DEBUG: "true"
    gcp:
      ingress_annotations:
        haproxy-ingress.github.io/timeout-server: "180s"
```

### 3. Traditional Apps (k3sapp)

```yaml
apps:
  - name: fastapi                          # Required: App name
    path: apps/fastapi                     # Required: Path to app directory
    namespace: apps                        # Optional: Target namespace
    enabled: true                          # Optional: Enable/disable

    # Build configuration
    build:
      dockerfile: Dockerfile               # Required: Main Dockerfile
      dockerfile_dev: Dockerfile.dev       # Optional: Dev Dockerfile (for hot-reload)
      context: .                           # Optional: Build context
      target: production                   # Optional: Multi-stage target
      args:
        APP_VERSION: "${VERSION}"

    # Container configuration
    container:
      command: ["python", "-m", "uvicorn"] # Optional: Override CMD
      args: ["main:app", "--host", "0.0.0.0"]
      ports:
        - name: http
          container_port: 8000
          service_port: 80
          protocol: TCP
        - name: metrics
          container_port: 9090
          service_port: 9090

    # Resource limits
    resources:
      memory: "512Mi"
      cpu: "250m"
      memory_limit: "1Gi"
      cpu_limit: "1000m"

    # Scaling configuration
    scaling:
      type: keda-http                      # hpa | keda-http | keda-queue | none
      min_instances: 0
      max_instances: 10
      target_pending_requests: 100         # For keda-http
      cooldown_period: 300
      # For HPA
      # target_cpu_percent: 80
      # target_memory_percent: 80

    # Health checks
    probes:
      startup:
        path: /health
        port: 8000
        initial_delay: 1
        period: 2
        failure_threshold: 30
      readiness:
        path: /ready
        port: 8000
        period: 5
      liveness:
        path: /live
        port: 8000
        period: 10

    # Ingress configuration
    ingress:
      enabled: true
      path: /fastapi                       # URL path
      path_type: Prefix                    # Prefix | Exact | ImplementationSpecific
      strip_prefix: true                   # Remove path prefix before forwarding
      rewrite_target: /                    # Optional: Rewrite path

      # Advanced routing (optional)
      hosts:
        - "api.example.com"

      # Annotations (merged with environment defaults)
      annotations:
        nginx.ingress.kubernetes.io/proxy-body-size: "10m"

    # Security configuration
    security:
      visibility: public                   # public | internal | private | restricted

      # Network policies
      network_policy:
        enabled: true
        allow_from:
          - namespace: monitoring          # Allow from monitoring namespace
          - namespace: apps
            pod_labels:
              app: frontend
        allow_to:
          - namespace: apps
            pod_labels:
              app: valkey

      # Pod security
      service_account: fastapi-sa
      pod_security_context:
        run_as_non_root: true
        run_as_user: 1000
        fs_group: 1000
      container_security_context:
        allow_privilege_escalation: false
        read_only_root_filesystem: true
        capabilities:
          drop: ["ALL"]

    # Environment variables
    environment:
      LOG_LEVEL: INFO
      DB_HOST: valkey.apps.svc.cluster.local

    # Environment variable references (from secrets/configmaps)
    env_from:
      - secret: fastapi-secrets
        prefix: ""
      - configmap: fastapi-config

    # Volume mounts
    volumes:
      - name: cache
        type: emptyDir                     # emptyDir | pvc | secret | configmap
        mount_path: /cache
      - name: config
        type: configmap
        configmap_name: fastapi-config
        mount_path: /config

    # Dependencies
    depends_on:
      - name: valkey
        type: helm

    # Environment-specific overrides
    local:
      scaling:
        type: none                         # Disable scaling locally
        min_instances: 1
    dev:
      port: 8000                           # Tilt port-forward
      live_update: true
      sync:
        - src: src/
          dest: /app/src/
      environment:
        DEBUG: "true"
    gcp:
      replicas: 2                          # Minimum replicas for HA
      pod_disruption_budget:
        min_available: 1
      anti_affinity:
        preferred:
          - topology_key: kubernetes.io/hostname
            weight: 100
      resources:
        memory: "1Gi"
        cpu: "500m"
        memory_limit: "2Gi"
```

### 4. Docker Compose Projects (k3scompose)

```yaml
compose:
  - name: monitoring-stack                 # Required: Stack name
    path: apps/monitoring                  # Required: Path to compose directory
    compose_file: docker-compose.yaml      # Optional: Compose file name
    namespace: monitoring                  # Optional: Target namespace
    enabled: true                          # Optional: Enable/disable

    # Global configuration for all services in the compose project
    defaults:
      resources:
        memory: "256Mi"
        cpu: "100m"
      security:
        visibility: internal

    # Per-service overrides (keyed by service name in docker-compose.yaml)
    services:
      prometheus:
        ingress:
          enabled: true
          path: /prometheus
        resources:
          memory: "1Gi"
          cpu: "500m"
        volumes:
          - name: prometheus-data
            type: pvc
            size: 10Gi
            storage_class: standard
            mount_path: /prometheus

      grafana:
        ingress:
          enabled: true
          path: /grafana
        security:
          visibility: public
        environment:
          GF_SERVER_ROOT_URL: "%(protocol)s://%(domain)s/grafana"

    # Network configuration
    network:
      policy: strict                       # none | permissive | strict
      allow_external:
        - namespace: apps

    # Environment-specific
    local:
      enabled: true
    dev:
      enabled: true
    gcp:
      enabled: true
      services:
        prometheus:
          volumes:
            - name: prometheus-data
              type: pvc
              size: 50Gi
              storage_class: pd-ssd
```

---

## Common Property Reference

### Resources Schema
```yaml
resources:
  memory: "256Mi"              # Memory request
  cpu: "100m"                  # CPU request
  memory_limit: "512Mi"        # Memory limit (OOM kill threshold)
  cpu_limit: "500m"            # CPU limit (optional - often omitted for burstable)
  ephemeral_storage: "1Gi"     # Ephemeral storage request
  gpu:
    type: nvidia.com/gpu       # GPU resource type
    count: 1                   # Number of GPUs
```

### Scaling Schema
```yaml
scaling:
  type: keda-http              # hpa | keda-http | keda-queue | keda-cron | none
  min_instances: 0             # Minimum replicas
  max_instances: 10            # Maximum replicas

  # For keda-http
  target_pending_requests: 100

  # For keda-queue
  queue_name: my-queue
  queue_length: 5

  # For HPA
  target_cpu_percent: 80
  target_memory_percent: 80

  # Stabilization
  cooldown_period: 300         # Seconds before scale down
  scale_up_stabilization: 0    # Seconds to wait before scaling up
  scale_down_stabilization: 300
```

### Security Schema
```yaml
security:
  # Network visibility
  visibility: private          # public | internal | private | restricted

  # For restricted visibility
  allowed_sources:
    - namespace: monitoring
    - namespace: apps
      pod_labels:
        role: frontend
    - cidr: 10.0.0.0/8

  # Network policy
  network_policy:
    enabled: true
    ingress:
      - from:
          - namespace: kube-system
            pod_labels:
              app.kubernetes.io/name: traefik
        ports:
          - protocol: TCP
            port: 8080
    egress:
      - to:
          - namespace: apps
            pod_labels:
              app: valkey
        ports:
          - protocol: TCP
            port: 6379

  # Service account
  service_account: my-app-sa
  create_service_account: true
  service_account_annotations:
    iam.gke.io/gcp-service-account: "my-app@project.iam.gserviceaccount.com"

  # Pod security context
  pod_security_context:
    run_as_non_root: true
    run_as_user: 1000
    run_as_group: 1000
    fs_group: 1000
    seccomp_profile:
      type: RuntimeDefault

  # Container security context
  container_security_context:
    allow_privilege_escalation: false
    read_only_root_filesystem: true
    capabilities:
      drop: ["ALL"]
      add: ["NET_BIND_SERVICE"]
```

### Ingress Schema
```yaml
ingress:
  enabled: true
  class: ""                    # Auto-detected from environment (traefik/haproxy)

  # Simple path-based routing
  path: /api
  path_type: Prefix            # Prefix | Exact | ImplementationSpecific
  strip_prefix: true           # Remove path prefix
  rewrite_target: /            # Rewrite to this path

  # Host-based routing
  hosts:
    - api.example.com
    - api.staging.example.com

  # TLS configuration
  tls:
    enabled: true
    secret: my-tls-secret      # Or use letsencrypt-prod
    hosts:
      - api.example.com

  # Timeouts
  timeouts:
    connect: "10s"
    server: "180s"
    client: "180s"
    queue: "180s"

  # Rate limiting
  rate_limit:
    requests_per_second: 100
    burst: 200

  # CORS
  cors:
    enabled: true
    allow_origins:
      - "https://example.com"
    allow_methods:
      - GET
      - POST
    allow_headers:
      - Authorization
      - Content-Type

  # Custom annotations (merged with environment defaults)
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
```

### Probes Schema
```yaml
probes:
  startup:
    type: http                 # http | tcp | exec
    path: /health              # For http
    port: 8080
    initial_delay: 1
    period: 2
    timeout: 1
    success_threshold: 1
    failure_threshold: 30      # Allow 60s startup (30 * 2s)

  readiness:
    type: http
    path: /ready
    port: 8080
    period: 5
    timeout: 1
    success_threshold: 1
    failure_threshold: 3

  liveness:
    type: http
    path: /live
    port: 8080
    initial_delay: 10
    period: 10
    timeout: 1
    failure_threshold: 3

  # Exec probe example
  liveness:
    type: exec
    command: ["pg_isready", "-U", "postgres"]
    period: 10
```

### Environment Schema
```yaml
# Direct values
environment:
  LOG_LEVEL: INFO
  APP_NAME: myapp

# References
env_from:
  - type: secret
    name: my-secret
    prefix: ""                 # Optional prefix for all keys
    optional: false
  - type: configmap
    name: my-config

# Individual references
env_refs:
  - name: DATABASE_PASSWORD
    from: secret
    secret_name: db-credentials
    key: password
  - name: API_KEY
    from: configmap
    configmap_name: api-config
    key: api_key
```

### Volumes Schema
```yaml
volumes:
  # EmptyDir (ephemeral)
  - name: cache
    type: emptyDir
    mount_path: /cache
    medium: ""                 # "" or "Memory"
    size_limit: "1Gi"

  # PersistentVolumeClaim
  - name: data
    type: pvc
    mount_path: /data
    size: 10Gi
    storage_class: standard    # standard | pd-ssd | etc.
    access_modes:
      - ReadWriteOnce

  # Secret
  - name: certs
    type: secret
    secret_name: tls-certs
    mount_path: /certs
    read_only: true
    items:                     # Optional: mount specific keys
      - key: tls.crt
        path: server.crt
      - key: tls.key
        path: server.key

  # ConfigMap
  - name: config
    type: configmap
    configmap_name: app-config
    mount_path: /config
    items:
      - key: config.yaml
        path: config.yaml
```

---

## CLI Tool Design

### k3sapp CLI

```bash
# Generate manifests for a traditional app
k3sapp generate apps/fastapi --name fastapi --env gcp --output ./generated/

# Options:
#   --name, -n       App name (required)
#   --env, -e        Environment: local, dev, gcp (default: local)
#   --output, -o     Output directory (default: ./generated)
#   --namespace      Override namespace
#   --dry-run        Print manifests without writing

# List apps from apps.yaml
k3sapp list

# Validate apps.yaml schema
k3sapp validate

# Generate manifests for all apps
k3sapp generate-all --env gcp --output ./argocd-state/gcp/apps/
```

### k3scompose CLI

```bash
# Generate K8s manifests from docker-compose.yaml
k3scompose generate apps/monitoring --name monitoring-stack --env gcp --output ./generated/

# Options:
#   --name, -n       Stack name (required)
#   --env, -e        Environment: local, dev, gcp (default: local)
#   --output, -o     Output directory (default: ./generated)
#   --namespace      Override namespace
#   --compose-file   Override compose file name

# Convert existing docker-compose to apps.yaml entry
k3scompose init apps/monitoring --name monitoring-stack

# Validate compose file and apps.yaml configuration
k3scompose validate apps/monitoring
```

### Updated k3sfn CLI

```bash
# Existing commands (unchanged)
k3sfn generate apps/serverless-example --name serverless-example --ingress haproxy
k3sfn list apps/serverless-example
k3sfn run apps/serverless-example --function hello_world

# New: Read defaults from apps.yaml
k3sfn generate apps/serverless-example --from-apps-yaml --env gcp
```

---

## Generated Manifest Structure

```
argocd-state/
├── gcp/
│   ├── apps/
│   │   ├── fastapi/
│   │   │   ├── manifests.yaml          # All K8s resources
│   │   │   └── k3sapp.json             # Metadata
│   │   └── another-app/
│   ├── serverless/
│   │   ├── serverless-example/
│   │   │   ├── manifests.yaml
│   │   │   ├── Dockerfile
│   │   │   └── k3sfn.json
│   │   └── another-function/
│   ├── compose/
│   │   └── monitoring-stack/
│   │       ├── manifests.yaml
│   │       └── k3scompose.json
│   └── helm/
│       └── valkey.yaml                  # ArgoCD Application
├── local/
│   └── ...
└── dev/
    └── ...
```

---

## Migration Plan

### Phase 1: Schema Design (Completed)
- [x] Design apps.yaml v2 schema
- [x] Document all property types
- [x] Create PLAN.md
- [x] Create JSON Schema for validation (`schemas/apps-schema.json`)

### Phase 2: k3sapp Implementation (Completed)
- [x] Create `libs/k3sapp/` Python package
- [x] Implement manifest generators:
  - [x] Deployment generator
  - [x] Service generator
  - [x] Ingress generator (Traefik + HAProxy)
  - [x] HTTPScaledObject generator
  - [x] HPA generator
  - [x] NetworkPolicy generator
  - [x] PDB generator
  - [x] PVC generator
- [x] Implement apps.yaml parser (`schema.py`)
- [x] Add CLI commands: generate, generate-all, list, validate
- [x] Write tests (test_types.py, test_generators.py, test_schema.py)

### Phase 3: k3scompose Implementation (Completed)
- [x] Create `libs/k3scompose/` Python package
- [x] Implement docker-compose.yaml parser
- [x] Implement K8s manifest generators (Deployment, Service, ConfigMap, PVC)
- [x] Add CLI commands: generate, generate-all, list, parse
- [x] Write tests (test_types.py, test_parser.py, test_generators.py)

### Phase 4: k3sfn Updates (Completed)
- [x] Add `--from-apps-yaml` flag
- [x] Read defaults from apps.yaml serverless entries
- [x] Maintain backward compatibility

### Phase 5: Migration (Completed)
- [x] Migrate FastAPI from kustomize to apps.yaml `apps:` entry
- [x] Generate manifests to `k8s/generated/{env}/` directories
- [x] Update Tiltfile to use new CLI tools (k3sapp, k3sfn)
- [x] Tiltfile now uses `uv run --project libs/k3sapp k3sapp generate` for apps
- [x] Tiltfile now uses `uv run --project libs/k3sfn k3sfn generate --from-apps-yaml` for serverless

### Phase 6: Validation & Testing (Completed)
- [x] Run unit tests (k3sapp: 55 passed, k3scompose: 56 passed)
- [x] Validate YAML syntax for generated manifests
- [x] Validate manifests against GCP cluster (kubectl apply --dry-run=server)
- [x] All resources validated: Deployment, Service, HTTPScaledObject, Ingress, NetworkPolicy, PDB

### Phase 7: Deployment via ArgoCD
- [ ] Copy generated manifests to argocd-state/ repository
- [ ] Commit and push to trigger ArgoCD sync
- [ ] Verify deployment through ArgoCD UI

---

## Directory Structure After Migration

```
k3s-platform/
├── apps.yaml                    # Single source of truth
├── apps/
│   ├── fastapi/
│   │   ├── Dockerfile
│   │   ├── Dockerfile.dev
│   │   └── src/
│   ├── serverless-example/
│   │   ├── functions/
│   │   └── requirements.txt
│   ├── monitoring/              # Docker Compose project
│   │   ├── docker-compose.yaml
│   │   └── configs/
│   └── valkey/
│       └── values.yaml
├── libs/
│   ├── k3sfn/                   # Serverless CLI
│   ├── k3sapp/                  # Traditional apps CLI
│   └── k3scompose/              # Compose CLI
├── argocd-state/                # Generated manifests (gitops)
│   ├── gcp/
│   ├── local/
│   └── dev/
├── providers/
│   ├── local/setup.sh
│   ├── dev/setup.sh
│   └── gcp/deploy.sh
├── platform/                    # Cluster infrastructure
├── scripts/
│   ├── generate-all.sh          # Regenerate all manifests
│   └── deploy-apps.sh
├── configs/
│   └── .env.example
├── Tiltfile
└── PLAN.md
```

---

## Example: Complete apps.yaml v2

```yaml
version: "2"

defaults:
  namespace: apps
  registry:
    local: "registry.localhost:5111"
    dev: "registry.localhost:5111"
    gcp: "us-central1-docker.pkg.dev/my-project/k3s-platform"
  ingress:
    local: traefik
    dev: traefik
    gcp: haproxy

environments:
  local:
    domain: "localhost"
    tls: false
  dev:
    domain: "localhost"
    tls: false
  gcp:
    domain: "api.example.com"
    tls: true
    tls_secret: "letsencrypt-prod"

helm:
  - name: valkey
    chart: bitnami/valkey
    version: "5.0.10"
    namespace: apps
    values: apps/valkey/values.yaml
    enabled: true

serverless:
  - name: serverless-example
    path: apps/serverless-example
    namespace: apps
    enabled: true
    security:
      visibility: public
    local:
      port_base: 8081
      live_update: true
    dev:
      port_base: 8081
      live_update: true
    gcp:
      scaling:
        min_instances: 0
        max_instances: 20

apps:
  - name: fastapi
    path: apps/fastapi
    namespace: apps
    enabled: true
    build:
      dockerfile: Dockerfile
      dockerfile_dev: Dockerfile.dev
    container:
      ports:
        - name: http
          container_port: 8000
          service_port: 80
    resources:
      memory: "512Mi"
      cpu: "250m"
      memory_limit: "1Gi"
    scaling:
      type: keda-http
      min_instances: 0
      max_instances: 10
      target_pending_requests: 100
    probes:
      startup:
        path: /health
        port: 8000
        failure_threshold: 30
      readiness:
        path: /health
        port: 8000
      liveness:
        path: /health
        port: 8000
    ingress:
      enabled: true
      path: /fastapi
      strip_prefix: true
    security:
      visibility: public
      network_policy:
        enabled: true
    local:
      scaling:
        type: none
        min_instances: 1
    dev:
      port: 8000
      live_update: true
      sync:
        - src: src/
          dest: /app/src/
    gcp:
      pod_disruption_budget:
        min_available: 1

repositories:
  bitnami: oci://registry-1.docker.io/bitnamicharts
  kedacore: https://kedacore.github.io/charts
```

---

## Benefits

1. **Single Source of Truth**: All configuration in `apps.yaml`
2. **Environment Awareness**: `local`, `dev`, `gcp` handled automatically
3. **Consistent Security**: NetworkPolicies, Pod Security, RBAC everywhere
4. **Consistent Ingress**: Traefik/HAProxy abstracted away
5. **Scale-to-Zero**: KEDA HTTPScaledObject for all HTTP services
6. **Type Safety**: Clear schema with validation
7. **Extensible**: Easy to add new environments or app types
8. **GitOps Ready**: Generated manifests committed to argocd-state/
