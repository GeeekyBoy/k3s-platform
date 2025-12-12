#!/bin/bash
set -euo pipefail

#═══════════════════════════════════════════════════════════════════════════════
# Platform Components Deployment
#
# Deploys all platform-level components:
#   - GCP Cloud Controller Manager (LoadBalancers)
#   - System Upgrade Controller (zero-downtime upgrades)
#   - KEDA Autoscaler (pod scale-to-zero)
#   - Cluster Autoscaler (VM scale-to-zero)
#   - ArgoCD (GitOps incremental deployments)
#
# Usage:
#   ./platform/deploy.sh
#═══════════════════════════════════════════════════════════════════════════════

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_step() { echo -e "\n${CYAN}═══ $1 ═══${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GITHUB_REPO="https://github.com/GeeekyBoy/k3s-platform.git"

# Load configuration (prefer .env.gcp, fall back to .env)
if [[ -f "${PROJECT_ROOT}/configs/.env.gcp" ]]; then
    source "${PROJECT_ROOT}/configs/.env.gcp"
elif [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
else
    echo "[ERROR] Configuration file not found: configs/.env.gcp or configs/.env"
    exit 1
fi

# Validate required variables
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set in configs/.env}"
: "${CLUSTER_NAME:?CLUSTER_NAME must be set in configs/.env}"
: "${VPC_NAME:=k3s-vpc}"
: "${SUBNET_NAME:=k3s-subnet}"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          Platform Components Deployment                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

#═══════════════════════════════════════════════════════════════════════════════
# Prepare nodes for CCM
#═══════════════════════════════════════════════════════════════════════════════
log_step "Preparing nodes for CCM"

log_info "Normalizing control-plane labels..."
for node in $(kubectl get nodes -l node-role.kubernetes.io/control-plane -o name 2>/dev/null || true); do
    kubectl label "$node" node-role.kubernetes.io/control-plane="" --overwrite 2>/dev/null || true
done

#═══════════════════════════════════════════════════════════════════════════════
# Deploy GCP Cloud Controller Manager
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying GCP Cloud Controller Manager"

# Create temporary CCM config with substituted values
log_info "Configuring CCM with: project=${GCP_PROJECT_ID}, vpc=${VPC_NAME}, subnet=${SUBNET_NAME}"
CCM_TEMP=$(mktemp -d)
cp -r "${SCRIPT_DIR}/gcp-ccm/"* "${CCM_TEMP}/"

# Substitute placeholders with actual values (cross-platform compatible)
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' \
        -e "s/GCP_PROJECT_ID_PLACEHOLDER/${GCP_PROJECT_ID}/g" \
        -e "s/VPC_NAME_PLACEHOLDER/${VPC_NAME}/g" \
        -e "s/SUBNET_NAME_PLACEHOLDER/${SUBNET_NAME}/g" \
        -e "s/NODE_TAGS_PLACEHOLDER/${CLUSTER_NAME}-node/g" \
        "${CCM_TEMP}/ccm.yaml"
else
    sed -i \
        -e "s/GCP_PROJECT_ID_PLACEHOLDER/${GCP_PROJECT_ID}/g" \
        -e "s/VPC_NAME_PLACEHOLDER/${VPC_NAME}/g" \
        -e "s/SUBNET_NAME_PLACEHOLDER/${SUBNET_NAME}/g" \
        -e "s/NODE_TAGS_PLACEHOLDER/${CLUSTER_NAME}-node/g" \
        "${CCM_TEMP}/ccm.yaml"
fi

kubectl apply -k "${CCM_TEMP}/"
rm -rf "${CCM_TEMP}"

log_info "Waiting for CCM to be ready..."
kubectl rollout status daemonset/cloud-controller-manager \
    -n kube-system \
    --timeout=180s

log_success "GCP CCM deployed"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy GCP Persistent Disk CSI Driver
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying GCP Persistent Disk CSI Driver"

log_info "Creating GCP PD CSI namespace..."
kubectl create namespace gce-pd-csi-driver --dry-run=client -o yaml | kubectl apply -f -

log_info "Applying GCP PD CSI driver manifests..."
kubectl apply -k "${SCRIPT_DIR}/gcp-pd-csi/"

log_info "Waiting for CSI node DaemonSet to be ready..."
kubectl rollout status daemonset/csi-gce-pd-node \
    -n gce-pd-csi-driver \
    --timeout=180s

log_info "Waiting for CSI controller to be ready..."
kubectl rollout status deployment/csi-gce-pd-controller \
    -n gce-pd-csi-driver \
    --timeout=180s

log_success "GCP PD CSI Driver deployed (persistent volumes survive node replacement)"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy System Upgrade Controller
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying System Upgrade Controller"

kubectl apply -k "${SCRIPT_DIR}/system-upgrade-controller/"

log_info "Waiting for System Upgrade Controller to be ready..."
kubectl rollout status deployment/system-upgrade-controller \
    -n system-upgrade \
    --timeout=180s

log_success "System Upgrade Controller deployed"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy KEDA Autoscaler
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying KEDA Autoscaler"

log_info "Installing KEDA helm chart..."
helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
helm repo update kedacore

helm upgrade --install keda kedacore/keda \
    --namespace keda \
    --create-namespace \
    --set tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set tolerations[0].operator=Exists \
    --set tolerations[0].effect=NoSchedule \
    --wait

log_success "KEDA Autoscaler deployed"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy KEDA HTTP Add-on (HTTP-based scale-to-zero for serverless functions)
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying KEDA HTTP Add-on"

log_info "Installing KEDA HTTP Add-on helm chart..."
# Configure timeouts for cold start reliability:
# - waitTimeout: Time to wait for pod to become ready (default 20s is too short)
# - responseHeaderTimeout: Time to wait for app response after pod is ready
# Note: Each component (operator, interceptor, scaler) needs its own tolerations
# Reduced resources for control-plane-only clusters (scale-to-zero scenario)
helm upgrade --install http-add-on kedacore/keda-add-ons-http \
    --namespace keda \
    --set operator.tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set operator.tolerations[0].operator=Exists \
    --set operator.tolerations[0].effect=NoSchedule \
    --set operator.resources.requests.cpu=32m \
    --set operator.resources.requests.memory=32Mi \
    --set interceptor.tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set interceptor.tolerations[0].operator=Exists \
    --set interceptor.tolerations[0].effect=NoSchedule \
    --set interceptor.replicas.min=1 \
    --set interceptor.resources.requests.cpu=32m \
    --set interceptor.resources.requests.memory=32Mi \
    --set scaler.tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set scaler.tolerations[0].operator=Exists \
    --set scaler.tolerations[0].effect=NoSchedule \
    --set scaler.replicas=1 \
    --set scaler.resources.requests.cpu=32m \
    --set scaler.resources.requests.memory=32Mi \
    --set interceptor.replicas.waitTimeout=120s \
    --set interceptor.responseHeaderTimeout=60s \
    --wait \
    --timeout=300s

log_success "KEDA HTTP Add-on deployed (HTTP scale-to-zero enabled, 120s cold start timeout)"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy HAProxy Ingress Controller (Single LB with path-based routing)
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying HAProxy Ingress Controller"

log_info "Adding HAProxy Helm repository..."
helm repo add haproxy-ingress https://haproxy-ingress.github.io/charts 2>/dev/null || true
helm repo update haproxy-ingress

log_info "Installing HAProxy Ingress..."
kubectl apply -k "${SCRIPT_DIR}/haproxy-ingress/"

helm upgrade --install haproxy-ingress haproxy-ingress/haproxy-ingress \
    --namespace haproxy-ingress \
    --values "${SCRIPT_DIR}/haproxy-ingress/values.yaml" \
    --wait \
    --timeout=300s

log_info "Waiting for HAProxy Ingress to be ready..."
kubectl rollout status deployment/haproxy-ingress-controller \
    -n haproxy-ingress \
    --timeout=180s 2>/dev/null || \
kubectl rollout status deployment/haproxy-ingress \
    -n haproxy-ingress \
    --timeout=180s 2>/dev/null || true

log_success "HAProxy Ingress Controller deployed (single GCP Load Balancer)"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy External Secrets Operator (for GCP Secret Manager integration)
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying External Secrets Operator"

log_info "Adding External Secrets Helm repository..."
helm repo add external-secrets https://charts.external-secrets.io 2>/dev/null || true
helm repo update external-secrets

log_info "Installing External Secrets Operator..."
helm upgrade --install external-secrets external-secrets/external-secrets \
    --namespace external-secrets \
    --create-namespace \
    --set installCRDs=true \
    --set tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set tolerations[0].operator=Exists \
    --set tolerations[0].effect=NoSchedule \
    --set webhook.tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set webhook.tolerations[0].operator=Exists \
    --set webhook.tolerations[0].effect=NoSchedule \
    --set certController.tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set certController.tolerations[0].operator=Exists \
    --set certController.tolerations[0].effect=NoSchedule \
    --wait

log_info "Waiting for External Secrets Operator to be ready..."
kubectl rollout status deployment/external-secrets \
    -n external-secrets \
    --timeout=180s

log_success "External Secrets Operator deployed"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy Cluster Autoscaler (VM scaling with min=1)
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying Cluster Autoscaler"

log_info "Configuring Cluster Autoscaler for MIG: ${CLUSTER_NAME}-workers"
CA_TEMP=$(mktemp -d)
cp -r "${SCRIPT_DIR}/cluster-autoscaler/"* "${CA_TEMP}/"

# Substitute placeholders
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' \
        -e "s/GCP_PROJECT_ID_PLACEHOLDER/${GCP_PROJECT_ID}/g" \
        -e "s/GCP_ZONE_PLACEHOLDER/${GCP_ZONE:-us-central1-a}/g" \
        -e "s/CLUSTER_NAME_PLACEHOLDER/${CLUSTER_NAME}/g" \
        -e "s/MIN_WORKERS_PLACEHOLDER/${MIN_WORKERS:-0}/g" \
        -e "s/MAX_WORKERS_PLACEHOLDER/${MAX_WORKERS:-5}/g" \
        "${CA_TEMP}/autoscaler.yaml"
else
    sed -i \
        -e "s/GCP_PROJECT_ID_PLACEHOLDER/${GCP_PROJECT_ID}/g" \
        -e "s/GCP_ZONE_PLACEHOLDER/${GCP_ZONE:-us-central1-a}/g" \
        -e "s/CLUSTER_NAME_PLACEHOLDER/${CLUSTER_NAME}/g" \
        -e "s/MIN_WORKERS_PLACEHOLDER/${MIN_WORKERS:-0}/g" \
        -e "s/MAX_WORKERS_PLACEHOLDER/${MAX_WORKERS:-5}/g" \
        "${CA_TEMP}/autoscaler.yaml"
fi

kubectl apply -k "${CA_TEMP}/"
rm -rf "${CA_TEMP}"

log_info "Waiting for Cluster Autoscaler to be ready..."
kubectl rollout status deployment/cluster-autoscaler \
    -n kube-system \
    --timeout=120s

log_success "Cluster Autoscaler deployed (VM scale-to-zero enabled)"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy ArgoCD (GitOps)
#═══════════════════════════════════════════════════════════════════════════════
log_step "Deploying ArgoCD for GitOps"

# Create argocd namespace
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# Install ArgoCD using kustomize
log_info "Applying ArgoCD manifests..."
kubectl apply -k "${SCRIPT_DIR}/argocd/"

# Wait for ArgoCD to be ready
log_info "Waiting for ArgoCD server to be ready..."
kubectl rollout status deployment/argocd-server -n argocd --timeout=300s
kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=300s

log_success "ArgoCD installed"

#═══════════════════════════════════════════════════════════════════════════════
# Generate and Apply ArgoCD State
#═══════════════════════════════════════════════════════════════════════════════
log_step "Generating ArgoCD State from apps.yaml"

# Generate the ArgoCD state for GCP environment
"${PROJECT_ROOT}/scripts/generate-argocd-state.sh" gcp

# Check if argocd-state/gcp exists
if [[ ! -d "${PROJECT_ROOT}/argocd-state/gcp" ]]; then
    log_error "ArgoCD state generation failed"
    exit 1
fi

# Apply the generated state
log_info "Applying ArgoCD applications from generated state..."
kubectl apply -k "${PROJECT_ROOT}/argocd-state/gcp/"

log_info "Waiting for ArgoCD to sync applications..."
sleep 5

# Check application status
kubectl get applications -n argocd 2>/dev/null || true

log_success "ArgoCD applications deployed"

#═══════════════════════════════════════════════════════════════════════════════
# Wait for nodes to be initialized by CCM
#═══════════════════════════════════════════════════════════════════════════════
log_step "Waiting for nodes to be initialized"

log_info "Waiting for CCM to label nodes..."
sleep 30

for i in {1..5}; do
    if kubectl get nodes -o wide 2>/dev/null; then
        log_success "Nodes initialized by CCM"
        break
    fi
    log_info "Waiting for API server... (attempt ${i}/5)"
    sleep 10
done

#═══════════════════════════════════════════════════════════════════════════════
# Complete
#═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ Platform components deployed successfully!${NC}"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Components installed:"
echo "  ✓ GCP Cloud Controller Manager (LoadBalancers)"
echo "  ✓ GCP PD CSI Driver (persistent volumes)"
echo "  ✓ System Upgrade Controller (zero-downtime upgrades)"
echo "  ✓ KEDA Autoscaler (pod scale-to-zero)"
echo "  ✓ KEDA HTTP Add-on (cold-start request buffering)"
echo "  ✓ HAProxy Ingress Controller (single LB, path-based routing)"
echo "  ✓ External Secrets Operator (GCP Secret Manager sync)"
echo "  ✓ Cluster Autoscaler (VM scaling, min=${MIN_WORKERS:-1})"
echo "  ✓ ArgoCD (GitOps incremental deployments)"
echo ""
echo "Load Balancer:"
INGRESS_IP=$(kubectl get svc -n haproxy-ingress haproxy-ingress -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
echo "  External IP: ${INGRESS_IP}"
echo "  All apps accessible via path-based routing on this single IP"
echo ""

echo "ArgoCD (GitOps):"
echo "  Get password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
echo "  Port forward: kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "  Access UI:    https://localhost:8080"
echo ""
echo "Deployment workflow (GitOps):"
echo "  1. Edit apps.yaml or app code"
echo "  2. ./scripts/generate-argocd-state.sh gcp"
echo "  3. git add . && git commit && git push"
echo "  4. ArgoCD auto-syncs (only changed resources updated)"
echo ""
