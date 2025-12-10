# K3s Platform

Production-ready Kubernetes platform using K3s with GCP integration.

**Simple like Docker Compose:** Edit `apps.yaml` to add/remove services. No scripts to modify!

## Quick Start

### 1. Configure (One Time)

```bash
# Copy and edit configuration
cp configs/.env.example configs/.env
nano configs/.env  # Set your GCP project ID
```

### 2. Deploy Infrastructure + Platform

```bash
# Deploys VMs, K3s, CCM, KEDA, etc.
./providers/gcp/deploy.sh
```

### 3. Deploy Applications

```bash
# Edit apps.yaml to enable/disable services
nano apps.yaml

# Deploy all enabled apps
./scripts/deploy-apps.sh
```

That's it! Your cluster is running.

## Adding/Removing Services

Just edit `apps.yaml`:

```yaml
helm:
  # Enable/disable by changing this flag
  - name: valkey
    chart: bitnami/valkey
    namespace: apps
    values: apps/valkey/values.yaml
    enabled: true  # Set to false to disable

  # Add PostgreSQL
  - name: postgres
    chart: bitnami/postgresql
    namespace: apps
    values: apps/postgres/values.yaml
    enabled: true

kustomize:
  - name: fastapi
    path: k8s/overlays/gcp
    enabled: true

  # Add your custom app
  - name: backend
    path: k8s/overlays/backend
    enabled: true
```

Then run:
```bash
./scripts/deploy-apps.sh
```

**No scripts to modify. No code changes. Just configuration!**

## Local Development

```bash
# Start local k3d cluster + apps with hot-reload
cd providers/local && ./setup.sh
cd ../.. && tilt up
```

## Features

- **Simple Configuration:** Like `docker-compose.yml` but for Kubernetes
- **No Hardcoded Apps:** Add/remove services without touching scripts
- **Production Ready:** All K3s best practices applied
- **Zero Downtime:** Proper health checks, rolling updates
- **VM Scale-to-Zero:** Cluster Autoscaler scales worker VMs to 0 when idle (like Cloud Run)
- **Pod Scale-to-Zero:** KEDA scales pods based on queue length or CPU
- **Self-healing:** Automatic node replacement and cluster upgrades
- **GCP Native:** Cloud Controller Manager for LoadBalancers
- **Fast Cold Start:** Embedded registry mirror for quick image pulls

## Architecture

```
GCP Infrastructure
  ├── VPC + Subnet (auto-created)
  ├── Service Account + IAM Roles (auto-created)
  ├── Artifact Registry (auto-created)
  ├── Control Plane (e2-standard-2, SSD)
  └── Workers (MIG 0-5, scale-to-zero, SSD)

K3s Platform Components
  ├── GCP Cloud Controller Manager (LoadBalancers)
  ├── Cluster Autoscaler (VM scale-to-zero)
  ├── KEDA Autoscaler (pod scale-to-zero)
  ├── System Upgrade Controller (zero-downtime upgrades)
  └── Embedded Registry Mirror (fast image pulls)

Your Applications (configured in apps.yaml)
  ├── Helm Charts (Valkey, Postgres, etc.)
  └── Kustomize Overlays (Your apps)
```

## Project Structure

```
k8s-platform/
├── apps.yaml                 # ← Enable/disable services (like docker-compose.yml)
├── configs/.env              # ← Your GCP project config
│
├── apps/                     # Helm chart values (third-party services)
│   └── valkey/values.yaml
│
├── k8s/                      # Your application manifests
│   ├── base/                 # ← ADD YOUR SERVICES HERE
│   │   ├── fastapi/          #   Each folder = one service
│   │   ├── backend/          #   Just add a folder to add a service!
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── gcp/              # GCP patches (LoadBalancer, registry, etc.)
│       └── local/            # Local patches (NodePort, local registry)
│
├── providers/
│   ├── gcp/deploy.sh         # One-command GCP deployment
│   └── local/setup.sh        # Local k3d setup
│
└── scripts/deploy-apps.sh    # Deploy all enabled apps
```

**Key insight:** Overlays are for ENVIRONMENTS (gcp, local), not services. Add services to `k8s/base/`.

## Common Tasks

### View Cluster Status
```bash
export KUBECONFIG=~/.kube/k3s-gcp-config
kubectl get nodes
kubectl get all -n apps
```

### Add a New Service (Your Code)

1. Create manifests folder:
   ```bash
   mkdir -p k8s/base/backend
   ```

2. Add your Kubernetes manifests:
   ```bash
   # deployment.yaml, service.yaml, etc.
   cat > k8s/base/backend/deployment.yaml <<EOF
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: backend
     namespace: apps
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: backend
     template:
       metadata:
         labels:
           app: backend
       spec:
         containers:
           - name: backend
             image: your-registry/backend:latest
             ports:
               - containerPort: 8080
   EOF
   ```

3. Add to base kustomization:
   ```bash
   # Edit k8s/base/kustomization.yaml and add:
   # resources:
   #   - backend/
   ```

4. Deploy:
   ```bash
   ./scripts/deploy-apps.sh
   ```

**That's it!** The GCP overlay automatically includes all services from base.

### Add a Third-Party Service (Helm)

```bash
# 1. Create values file
cat > apps/mongodb/values.yaml <<EOF
auth:
  rootPassword: "changeme"
EOF

# 2. Add to apps.yaml
# helm:
#   - name: mongodb
#     chart: bitnami/mongodb
#     values: apps/mongodb/values.yaml
#     enabled: true

# 3. Deploy
./scripts/deploy-apps.sh
```

### Remove a Service

1. Set `enabled: false` in `apps.yaml`, or:
   ```bash
   helm uninstall <service-name> -n apps
   ```

### Upgrade Cluster

K3s upgrades happen automatically based on `configs/upgrade-plans.yaml`. To trigger manually:
```bash
kubectl apply -f configs/upgrade-plans.yaml
kubectl get plans -n system-upgrade
```

### Teardown Everything

```bash
./providers/gcp/teardown.sh
```

## Configuration Files

### configs/.env
Project-wide settings (GCP project, region, cluster name)

### apps.yaml
All application deployments (like docker-compose.yml)

### apps/*/values.yaml
Helm chart values for each service

### k8s/overlays/*/
Kustomize overlays for environment-specific configs

## Why K3s?

- **Lightweight:** ~70MB binary vs full Kubernetes
- **Fast:** Optimized for edge and CI/CD
- **Production Ready:** Used by millions of devices
- **Full Kubernetes:** 100% upstream Kubernetes compliance
- **Batteries Included:** Traefik ingress, Helm controller, etc.

## Best Practices Applied

- ✅ Embedded registry mirror for fast cold starts
- ✅ Systemd reliability checks
- ✅ Proper kubeconfig permissions (600)
- ✅ Short-lived access tokens (no SA key files)
- ✅ Health checks between deployment steps
- ✅ Sequential bootstrap with retry logic
- ✅ Zero-downtime rolling updates
- ✅ Configuration-driven (no hardcoded apps)
- ✅ SSD for all nodes (reliability)
- ✅ Auto-scaling workers (1-5)
- ✅ Pod Disruption Budgets
- ✅ Comprehensive tolerations
- ✅ Network policies
- ✅ Security contexts

## Troubleshooting

### Cluster not accessible?
```bash
export KUBECONFIG=~/.kube/k3s-gcp-config
kubectl cluster-info
```

### App deployment failed?
```bash
kubectl get pods -n apps
kubectl logs -f <pod-name> -n apps
kubectl describe pod <pod-name> -n apps
```

### Image pull failed?
```bash
kubectl get secrets -n apps
./providers/gcp/deploy.sh  # Recreates secrets
```

### Storage issues?
```bash
kubectl get storageclass
kubectl get pvc -n apps
```

## Support

For issues or questions, check:
- K3s docs: https://docs.k3s.io
- Helm charts: https://artifacthub.io

## License

MIT
