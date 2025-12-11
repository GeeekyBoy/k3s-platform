#!/bin/bash
set -euo pipefail

#═══════════════════════════════════════════════════════════════════════════════
# K3s Platform - GCP Teardown
#
# Removes all GCP resources created by the deployment scripts
#═══════════════════════════════════════════════════════════════════════════════

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}═══ $1 ═══${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load configuration (prefer .env.gcp, fall back to .env)
if [[ -f "${PROJECT_ROOT}/configs/.env.gcp" ]]; then
    source "${PROJECT_ROOT}/configs/.env.gcp"
elif [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
else
    log_error "Configuration file not found: configs/.env.gcp or configs/.env"
    exit 1
fi

# Configuration
GCP_PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set}"
GCP_REGION="${GCP_REGION:-us-central1}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
CLUSTER_NAME="${CLUSTER_NAME:-k3s-cluster}"
VPC_NAME="${VPC_NAME:-k3s-vpc}"
SUBNET_NAME="${SUBNET_NAME:-k3s-subnet}"

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║              K3s Platform - GCP Teardown                               ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${YELLOW}WARNING: This will delete ALL resources for cluster: ${CLUSTER_NAME}${NC}"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "Teardown cancelled."
    exit 0
fi

log_step "Deleting Compute Resources"

# Delete MIG
log_info "Deleting Managed Instance Group..."
gcloud compute instance-groups managed delete "${CLUSTER_NAME}-workers" \
    --zone="${GCP_ZONE}" --quiet 2>/dev/null || log_warn "MIG not found or already deleted"

# Delete instance templates
log_info "Deleting instance templates..."
gcloud compute instance-templates delete "${CLUSTER_NAME}-worker-template" \
    --quiet 2>/dev/null || log_warn "Template not found"
gcloud compute instance-templates delete "${CLUSTER_NAME}-worker-template-self-healing" \
    --quiet 2>/dev/null || log_warn "Self-healing template not found"

# Delete control plane VM
log_info "Deleting control plane VM..."
gcloud compute instances delete "${CLUSTER_NAME}-control-plane" \
    --zone="${GCP_ZONE}" --quiet 2>/dev/null || log_warn "Control plane VM not found"

# Delete static IP
log_info "Deleting static IP..."
gcloud compute addresses delete "${CLUSTER_NAME}-ip" \
    --region="${GCP_REGION}" --quiet 2>/dev/null || log_warn "Static IP not found"

log_step "Deleting Firewall Rules"

for rule in "${CLUSTER_NAME}-internal" "${CLUSTER_NAME}-ssh" "${CLUSTER_NAME}-k8s-api" "${CLUSTER_NAME}-lb-health" "${CLUSTER_NAME}-http"; do
    log_info "Deleting firewall rule: ${rule}..."
    gcloud compute firewall-rules delete "${rule}" --quiet 2>/dev/null || log_warn "Rule not found: ${rule}"
done

log_step "Deleting Network Resources"

# Delete subnet
log_info "Deleting subnet..."
gcloud compute networks subnets delete "${SUBNET_NAME}" \
    --region="${GCP_REGION}" --quiet 2>/dev/null || log_warn "Subnet not found"

# Delete VPC
log_info "Deleting VPC..."
gcloud compute networks delete "${VPC_NAME}" --quiet 2>/dev/null || log_warn "VPC not found"

log_step "Cleaning Up Local Files"

# Clean up local token and kubeconfig
rm -f "${HOME}/.k3s/token" 2>/dev/null || true
rm -f "${HOME}/.kube/k3s-gcp-config" 2>/dev/null || true
rm -f "/tmp/${CLUSTER_NAME}-sa-key.json" 2>/dev/null || true

log_info "Listing remaining service account keys (clean up manually if needed)..."
SA_EMAIL="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts keys list --iam-account="${SA_EMAIL}" 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ Teardown complete!${NC}"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "Note: The following resources were NOT deleted (may still exist):"
echo "  - Service account: ${SA_EMAIL}"
echo "  - Artifact Registry: ${REGISTRY_NAME:-k3s-platform}"
echo ""
echo "To delete these manually:"
echo "  gcloud iam service-accounts delete ${SA_EMAIL}"
echo "  gcloud artifacts repositories delete ${REGISTRY_NAME:-k3s-platform} --location=${GCP_REGION}"
echo ""
