# k3scompose

K3s Platform CLI for Docker Compose projects.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Generate K8s manifests from docker-compose.yaml
k3scompose generate --name monitoring-stack --env gcp --output ./generated/

# Generate manifests for all compose projects
k3scompose generate-all --env gcp --output ./argocd-state/gcp/compose/

# List compose projects from apps.yaml
k3scompose list

# Parse and display docker-compose.yaml structure
k3scompose parse apps/monitoring
```

## Features

- Converts Docker Compose files to Kubernetes manifests
- Reads configuration from `apps.yaml` v2 schema
- Generates:
  - Deployment
  - Service
  - ConfigMap
  - PersistentVolumeClaim
- Environment-aware: local, dev, gcp
- Supports compose-specific options like health checks, resources, volumes
