# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

K3s Platform is a production-ready Kubernetes platform supporting three environments:
- **dev**: Local development with Tilt hot-reload
- **local**: On-premises production-like (k3d + ArgoCD)
- **gcp**: Cloud production (GCP + ArgoCD)

Configuration is driven by `apps.yaml` - the single source of truth for all deployments.

## Common Commands

### Environment Setup

```bash
# Development (with Tilt hot-reload)
./providers/dev/setup.sh
./providers/dev/setup.sh --no-tilt  # Setup only, don't start Tilt

# Local (production-like with ArgoCD)
./providers/local/setup.sh

# GCP cloud deployment
cp configs/.env.gcp.example configs/.env  # Configure GCP project
./providers/gcp/deploy.sh
```

### Serverless Functions (k3sfn SDK)

```bash
# Create new serverless app
./scripts/new-serverless-app.sh my-api

# List discovered functions
uv run python3 -m k3sfn.cli list ./apps/<app-name>

# Generate Kubernetes manifests
uv run python3 -m k3sfn.cli generate ./apps/<app-name> \
    --name <app-name> \
    --output ./generated \
    --namespace apps \
    --ingress traefik  # or haproxy for GCP

# Run functions locally (without containers)
uv run python3 -m k3sfn.cli run ./apps/<app-name> --port 8080
```

### GitOps Workflow

```bash
# Generate ArgoCD state from apps.yaml
./scripts/generate-argocd-state.sh local  # or gcp

# Deploy changes
git add argocd-state/
git commit -m "Update apps"
git push  # ArgoCD auto-syncs
```

### Cluster Access

```bash
# Dev cluster
export KUBECONFIG=$(k3d kubeconfig write k3s-dev)

# GCP cluster
export KUBECONFIG=~/.kube/k3s-gcp-config

# View status
kubectl get pods -n apps
kubectl get applications -n argocd

# ArgoCD UI (port-forward)
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Access: https://localhost:8080
```

### Teardown

```bash
./providers/dev/teardown.sh
./providers/local/teardown.sh
./providers/gcp/teardown.sh
```

## Architecture

### Request Flow for Serverless Functions

```
Client -> Ingress (Traefik/HAProxy) -> KEDA HTTP Interceptor -> Function Pod
                                              |
                                    (queues requests if scaled to 0,
                                     wakes pod, then forwards)
```

The KEDA HTTP Add-on handles scale-to-zero: when a function has 0 replicas, requests are buffered by the interceptor while the pod starts up.

### k3sfn SDK Structure

The SDK (`libs/k3sfn/`) provides Firebase-style decorators:

```python
from k3sfn import serverless, http_trigger, queue_trigger, schedule_trigger

@serverless(memory="256Mi", visibility="public", min_instances=0, max_instances=10)
@http_trigger(path="/api/hello", methods=["GET"])
async def hello(request):
    return {"message": "Hello!"}

@serverless(memory="512Mi")
@queue_trigger(queue_name="tasks", batch_size=5)
async def process(messages, context):
    ...

@serverless(memory="256Mi")
@schedule_trigger(cron="0 * * * *")
async def hourly_job(context):
    ...
```

Key files:
- `libs/k3sfn/k3sfn/decorators.py` - Decorator definitions and function registry
- `libs/k3sfn/k3sfn/cli.py` - CLI for manifest generation, includes all K8s resource generators
- `libs/k3sfn/k3sfn/runtime.py` - FastAPI runtime for serving functions
- `libs/k3sfn/k3sfn/types.py` - Type definitions (FunctionMetadata, TriggerType, etc.)

### Deployment Types in apps.yaml

1. **helm**: Third-party charts (e.g., Valkey/Redis)
2. **kustomize**: Apps deployed via `k8s/base` + `k8s/overlays/<env>`
3. **serverless**: k3sfn functions with auto-generated manifests
4. **apps**: Traditional container applications

### Generated Manifests

The `generate-argocd-state.sh` script reads `apps.yaml` and generates:
- `argocd-state/<env>/project.yaml` - ArgoCD project
- `argocd-state/<env>/*.yaml` - ArgoCD Application manifests
- `argocd-state/<env>/serverless/<app>/manifests.yaml` - Raw K8s resources for serverless apps

For serverless functions, `k3sfn.cli generate` creates Deployments, Services, HTTPScaledObjects (or ScaledObjects for queues), NetworkPolicies, and Ingress resources.

### Ingress Controllers

- **dev/local**: Traefik (IngressRoute CRDs)
- **gcp**: HAProxy Ingress with per-path host rewriting for KEDA routing

## Cold Start Optimization

Serverless functions with `min_instances=0` experience cold starts (~6-15s). The generated manifests include:
- **startupProbe**: Allows 60s for cold start before liveness checks begin
- **No CPU limits**: Enables burstable QoS for faster Python startup
- **Readiness probe**: 1s initial delay, 2s period for fast traffic routing

For latency-critical functions, use `min_instances=1` to avoid cold starts.

## Key Configuration Files

| File | Purpose |
|------|---------|
| `apps.yaml` | Central config for all deployments |
| `configs/.env.<env>` | Environment-specific settings |
| `k8s/base/` | Base Kubernetes manifests |
| `k8s/overlays/<env>/` | Environment-specific patches |
| `Tiltfile` | Development hot-reload config |

## Testing k3sfn SDK

```bash
cd libs/k3sfn
uv run pytest
```

## Important Notes

- ArgoCD uses `selfHeal: true` - manual kubectl changes will be reverted
- Always commit to git for changes to take effect in ArgoCD environments
- The `argocd-state/` directory is auto-generated - don't edit manually
- Serverless manifests require building/pushing Docker images before ArgoCD can deploy
