# K3s Platform

Production-ready Kubernetes platform with K3s, supporting development, on-premises, and cloud deployments.

**Configuration-Driven:** Edit `apps.yaml` to add/remove services. No scripts to modify!

## Environments

| Environment | Purpose | Setup | Deployment |
|-------------|---------|-------|------------|
| **dev** | Development with hot-reload | `./providers/dev/setup.sh` | Tilt |
| **local** | On-premises production-like | `./providers/local/setup.sh` | ArgoCD |
| **gcp** | Cloud production | `./providers/gcp/deploy.sh` | ArgoCD |

## Quick Start

### Development (with Tilt hot-reload)

```bash
# 1. Setup cluster and start Tilt
./providers/dev/setup.sh

# 2. Open Tilt UI at http://localhost:10350
# 3. Edit code, see changes instantly!
```

### Local Production-Like (with ArgoCD)

```bash
# 1. Setup cluster
./providers/local/setup.sh

# 2. Generate ArgoCD state and push to git
./scripts/generate-argocd-state.sh local
git add . && git commit -m "Update apps" && git push

# 3. ArgoCD auto-syncs your changes
```

### GCP Cloud Deployment

```bash
# 1. Configure GCP settings
cp configs/.env.gcp.example configs/.env
nano configs/.env  # Set your GCP project ID

# 2. Deploy everything
./providers/gcp/deploy.sh

# 3. Update apps via GitOps
./scripts/generate-argocd-state.sh gcp
git add . && git commit && git push
```

## Deployment Types

### Helm Charts (third-party services)
```yaml
helm:
  - name: valkey
    chart: bitnami/valkey
    values: apps/valkey/values.yaml
    enabled: true
```

### Kustomize (your applications)
```yaml
kustomize:
  - name: apps
    path: k8s/overlays/${PLATFORM_ENV}
    enabled: true
```

### Serverless Functions (scale-to-zero)
```yaml
serverless:
  - name: serverless-example
    path: apps/serverless-example
    enabled: true
```

### Traditional Apps (Dockerfile-based)
```yaml
apps:
  - name: fastapi
    path: apps/fastapi
    enabled: true
```

## Project Structure

```
k3s-platform/
├── apps.yaml                 # Single source of truth for all deployments
├── configs/
│   ├── .env.dev.example      # Dev environment config
│   ├── .env.local.example    # Local environment config
│   └── .env.gcp.example      # GCP environment config
│
├── apps/                     # Application source code
│   ├── fastapi/              # Traditional container app
│   ├── serverless-example/   # Serverless functions (k3sfn)
│   └── valkey/               # Helm chart values
│
├── k8s/                      # Kubernetes manifests
│   ├── base/                 # Base manifests (add services here)
│   └── overlays/             # Environment-specific patches
│       ├── dev/
│       ├── local/
│       └── gcp/
│
├── argocd-state/             # Generated ArgoCD applications (git-synced)
│   ├── local/
│   └── gcp/
│
├── libs/
│   └── k3sfn/                # Serverless function SDK
│
├── platform/                 # Platform components
│   ├── argocd/               # ArgoCD configuration
│   ├── cluster-autoscaler/   # VM scale-to-zero
│   ├── gcp-ccm/              # GCP Cloud Controller Manager
│   ├── system-upgrade-controller/
│   └── traefik/              # Traefik configuration
│
├── providers/                # Environment setup scripts
│   ├── dev/                  # Development (Tilt)
│   ├── local/                # On-premises (ArgoCD)
│   └── gcp/                  # Cloud (ArgoCD)
│
└── scripts/                  # Utility scripts
    ├── generate-argocd-state.sh  # Generate ArgoCD manifests
    ├── deploy-apps.sh            # Deploy apps (legacy)
    └── new-serverless-app.sh     # Create new serverless app
```

## Serverless Functions (k3sfn)

Create serverless functions with scale-to-zero:

```python
# apps/my-app/functions/api.py
from k3sfn import http, queue, schedule

@http("/api/hello", visibility="public")
async def hello_world(request):
    return {"message": "Hello, World!"}

@queue("tasks", visibility="private")
async def process_task(message):
    # Process queue message
    pass

@schedule("0 * * * *")  # Every hour
async def hourly_job(context):
    # Scheduled job
    pass
```

Generate manifests and deploy:
```bash
./scripts/generate-argocd-state.sh gcp
git add . && git commit && git push
```

## GitOps Workflow

1. **Edit** - Modify `apps.yaml` or app code
2. **Generate** - Run `./scripts/generate-argocd-state.sh <env>`
3. **Push** - `git add . && git commit && git push`
4. **Sync** - ArgoCD auto-syncs (only changed resources)

## Features

- **Configuration-Driven**: Add/remove services via `apps.yaml`
- **Three Environments**: dev (Tilt), local (ArgoCD), gcp (ArgoCD)
- **Serverless Functions**: HTTP, queue, and scheduled triggers with scale-to-zero
- **GitOps Ready**: ArgoCD for incremental deployments
- **VM Scale-to-Zero**: Cluster Autoscaler scales workers to 0 when idle
- **Pod Scale-to-Zero**: KEDA scales pods based on load
- **Zero-Downtime Upgrades**: System Upgrade Controller
- **GCP Native**: Cloud Controller Manager for LoadBalancers

## Platform Components

| Component | Purpose |
|-----------|---------|
| Traefik | Ingress controller |
| KEDA | Pod autoscaling (scale-to-zero) |
| KEDA HTTP Add-on | HTTP-triggered scale-to-zero |
| ArgoCD | GitOps deployments |
| Cluster Autoscaler | VM scale-to-zero (GCP) |
| GCP CCM | LoadBalancer support (GCP) |
| System Upgrade Controller | Rolling upgrades |

## Common Tasks

### Add a New Serverless Function
```bash
# 1. Create new app from template
./scripts/new-serverless-app.sh my-new-app

# 2. Edit apps.yaml to add the app
# 3. Generate and deploy
./scripts/generate-argocd-state.sh gcp
git add . && git commit && git push
```

### View Cluster Status
```bash
export KUBECONFIG=~/.kube/k3s-gcp-config
kubectl get nodes
kubectl get pods -n apps
kubectl get applications -n argocd
```

### Access ArgoCD UI
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Open https://localhost:8080
# Username: admin
# Password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

### Teardown
```bash
./providers/gcp/teardown.sh   # GCP
./providers/local/teardown.sh # Local
./providers/dev/teardown.sh   # Dev
```

## Configuration

### Environment Files

| File | Purpose |
|------|---------|
| `configs/.env.dev.example` | Development with Tilt |
| `configs/.env.local.example` | On-premises production-like |
| `configs/.env.gcp.example` | GCP cloud deployment |

Copy the appropriate example to `configs/.env` before running setup.

## License

MIT
