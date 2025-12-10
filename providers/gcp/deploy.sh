#!/bin/bash
set -euo pipefail

#═══════════════════════════════════════════════════════════════════════════════
# K3s Platform - Complete Deployment Orchestrator
#
# This script orchestrates the complete deployment process:
#   1. Deploy infrastructure (VMs)
#   2. Bootstrap K3s
#   3. Deploy platform components
#   4. Deploy applications
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
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load configuration
if [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
else
    echo -e "${RED}[ERROR]${NC} Configuration file not found: configs/.env"
    exit 1
fi

# Validate required variables
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set in configs/.env}"
: "${GCP_REGION:?GCP_REGION must be set in configs/.env}"
: "${CLUSTER_NAME:?CLUSTER_NAME must be set in configs/.env}"
: "${REGISTRY_NAME:?REGISTRY_NAME must be set in configs/.env}"

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║              K3s Platform - Complete GCP Deployment                    ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

#═══════════════════════════════════════════════════════════════════════════════
# Step 1: Deploy Infrastructure
#═══════════════════════════════════════════════════════════════════════════════
log_step "Step 1/4: Deploy Infrastructure"
"${SCRIPT_DIR}/deploy-infra.sh"

#═══════════════════════════════════════════════════════════════════════════════
# Step 2: Bootstrap K3s
#═══════════════════════════════════════════════════════════════════════════════
log_step "Step 2/4: Bootstrap K3s Cluster"
"${SCRIPT_DIR}/bootstrap.sh"

#═══════════════════════════════════════════════════════════════════════════════
# Step 3: Deploy Platform Components
#═══════════════════════════════════════════════════════════════════════════════
log_step "Step 3/4: Deploy Platform Components"

export KUBECONFIG=~/.kube/k3s-gcp-config

# Verify cluster is accessible
log_info "Verifying cluster is accessible..."
if ! kubectl get nodes &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} Cannot connect to cluster. Check kubeconfig at: ~/.kube/k3s-gcp-config"
    exit 1
fi

# Wait for all nodes to be Ready
log_info "Waiting for all nodes to be Ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s || {
    echo -e "${YELLOW}[WARN]${NC} Some nodes not ready yet, continuing anyway..."
}

if [[ -f "${PROJECT_ROOT}/platform/deploy.sh" ]]; then
    cd "${PROJECT_ROOT}/platform"
    ./deploy.sh
else
    log_info "No platform/deploy.sh found, skipping platform deployment"
fi

# Wait for CCM to initialize nodes (critical for StorageClass)
log_info "Waiting for CCM to initialize all nodes..."
sleep 20
kubectl get nodes -o wide

#═══════════════════════════════════════════════════════════════════════════════
# Step 4: Configure Image Pull Secrets
#═══════════════════════════════════════════════════════════════════════════════
log_step "Step 4/4: Configure Image Pull Secrets"

# Create namespaces
kubectl create namespace apps --dry-run=client -o yaml | kubectl apply -f -

# Configure image pull authentication using service account key (persistent)
log_info "Configuring image pull authentication..."
SA_EMAIL="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SA_KEY_FILE="/tmp/${CLUSTER_NAME}-sa-key.json"

# Create or reuse service account key
if [[ ! -f "${SA_KEY_FILE}" ]]; then
    log_info "Creating service account key for persistent image pull..."
    gcloud iam service-accounts keys create "${SA_KEY_FILE}" \
        --iam-account="${SA_EMAIL}" \
        --quiet
    chmod 600 "${SA_KEY_FILE}"
fi

# Create image pull secret using SA key (doesn't expire like access tokens)
log_info "Creating image pull secret using service account key..."
kubectl create secret docker-registry artifact-registry \
    --docker-server="${GCP_REGION}-docker.pkg.dev" \
    --docker-username=_json_key \
    --docker-email="${SA_EMAIL}" \
    --docker-password="$(cat ${SA_KEY_FILE})" \
    --namespace=apps \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Image pull secret configured (persistent SA key)"

#═══════════════════════════════════════════════════════════════════════════════
# Complete!
#═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ Complete K3s Platform Deployed Successfully!${NC}"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "Access your cluster:"
echo "  export KUBECONFIG=~/.kube/k3s-gcp-config"
echo "  kubectl get nodes"
echo ""
echo "Deploy your applications:"
echo "  ./scripts/deploy-apps.sh"
echo ""
echo "Or for development:"
echo "  tilt up"
echo ""
echo "Add/remove services:"
echo "  1. Edit apps.yaml"
echo "  2. Run: ./scripts/deploy-apps.sh"
echo ""
echo "To teardown everything:"
echo "  ./providers/gcp/teardown.sh"
echo "════════════════════════════════════════════════════════════════════════"
