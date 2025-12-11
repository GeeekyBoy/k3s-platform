# k3sapp

K3s Platform CLI for traditional Dockerfile-based applications.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Generate manifests for an app
k3sapp generate --name fastapi --env gcp --output ./generated/

# Generate manifests for all apps
k3sapp generate-all --env gcp --output ./argocd-state/gcp/apps/

# List apps from apps.yaml
k3sapp list

# Validate apps.yaml
k3sapp validate
```

## Features

- Reads configuration from `apps.yaml` v2 schema
- Generates Kubernetes manifests:
  - Deployment
  - Service
  - Ingress (Traefik or HAProxy)
  - HTTPScaledObject (KEDA)
  - HPA
  - NetworkPolicy
  - PodDisruptionBudget
  - PersistentVolumeClaim
- Environment-aware: local, dev, gcp
- Supports scale-to-zero with KEDA HTTP add-on
