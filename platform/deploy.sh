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

# Load configuration
if [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
else
    echo "[ERROR] Configuration file not found: configs/.env"
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
helm upgrade --install http-add-on kedacore/keda-add-ons-http \
    --namespace keda \
    --set tolerations[0].key=node-role.kubernetes.io/control-plane \
    --set tolerations[0].operator=Exists \
    --set tolerations[0].effect=NoSchedule \
    --set interceptor.replicas.waitTimeout=120s \
    --set interceptor.responseHeaderTimeout=60s \
    --wait

log_success "KEDA HTTP Add-on deployed (HTTP scale-to-zero enabled, 120s cold start timeout)"

#═══════════════════════════════════════════════════════════════════════════════
# Deploy Cluster Autoscaler (VM scale-to-zero)
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
# Apply Upgrade Plans
#═══════════════════════════════════════════════════════════════════════════════
log_step "Applying K3s Upgrade Plans"

kubectl apply -f "${PROJECT_ROOT}/configs/upgrade-plans.yaml"

log_success "Upgrade plans applied"

#═══════════════════════════════════════════════════════════════════════════════
# Wait for nodes to be initialized by CCM
#═══════════════════════════════════════════════════════════════════════════════
log_step "Waiting for nodes to be initialized"

log_info "Waiting for CCM to label nodes..."
sleep 30

kubectl get nodes -o wide

log_success "Nodes initialized by CCM"

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
echo "  ✓ System Upgrade Controller (zero-downtime upgrades)"
echo "  ✓ KEDA Autoscaler (pod scale-to-zero)"
echo "  ✓ KEDA HTTP Add-on (HTTP scale-to-zero for serverless)"
echo "  ✓ Cluster Autoscaler (VM scale-to-zero)"
echo "  ✓ K3s Upgrade Plans"
echo "  ✓ ArgoCD (GitOps incremental deployments)"
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
