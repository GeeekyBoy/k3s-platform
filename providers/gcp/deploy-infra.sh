#!/bin/bash
set -euo pipefail

#═══════════════════════════════════════════════════════════════════════════════
# K3s Infrastructure Deployment - VMs Only
#
# This script ONLY creates GCP infrastructure (VMs, networking).
# K3s installation happens via bootstrap.sh
# Platform/apps deployed via kubectl after bootstrap
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

# Configuration with defaults
GCP_PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set}"
GCP_REGION="${GCP_REGION:-us-central1}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
CLUSTER_NAME="${CLUSTER_NAME:-k3s-cluster}"
VPC_NAME="${VPC_NAME:-k3s-vpc}"
SUBNET_NAME="${SUBNET_NAME:-k3s-subnet}"

# VM Configuration
CONTROL_PLANE_TYPE="${CONTROL_PLANE_TYPE:-e2-standard-2}"
WORKER_NODE_TYPE="${WORKER_NODE_TYPE:-e2-medium}"
MIN_WORKERS="${MIN_WORKERS:-1}"
MAX_WORKERS="${MAX_WORKERS:-5}"

#═══════════════════════════════════════════════════════════════════════════════
# Prerequisites check
#═══════════════════════════════════════════════════════════════════════════════
check_prerequisites() {
    log_step "Checking prerequisites"

    # Check gcloud
    if ! command -v gcloud &>/dev/null; then
        log_error "gcloud CLI not found"
        exit 1
    fi

    # Verify authentication
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated with GCP. Run: gcloud auth login"
        exit 1
    fi

    # Set project
    gcloud config set project "${GCP_PROJECT_ID}"

    log_success "Prerequisites satisfied"
}

#═══════════════════════════════════════════════════════════════════════════════
# Create VPC and Subnet
#═══════════════════════════════════════════════════════════════════════════════
create_vpc_and_subnet() {
    log_step "Setting up VPC and Subnet"

    # Create VPC if it doesn't exist
    if ! gcloud compute networks describe "${VPC_NAME}" &>/dev/null; then
        log_info "Creating VPC: ${VPC_NAME}"
        gcloud compute networks create "${VPC_NAME}" \
            --subnet-mode=custom \
            --bgp-routing-mode=regional \
            --quiet
        log_success "VPC created: ${VPC_NAME}"
    else
        log_info "VPC already exists: ${VPC_NAME}"
    fi

    # Create Subnet if it doesn't exist
    if ! gcloud compute networks subnets describe "${SUBNET_NAME}" \
        --region="${GCP_REGION}" &>/dev/null; then
        log_info "Creating subnet: ${SUBNET_NAME} (${SUBNET_CIDR:-10.128.0.0/20})"
        gcloud compute networks subnets create "${SUBNET_NAME}" \
            --network="${VPC_NAME}" \
            --region="${GCP_REGION}" \
            --range="${SUBNET_CIDR:-10.128.0.0/20}" \
            --enable-private-ip-google-access \
            --quiet
        log_success "Subnet created: ${SUBNET_NAME}"
    else
        log_info "Subnet already exists: ${SUBNET_NAME}"
    fi
}

#═══════════════════════════════════════════════════════════════════════════════
# Create Service Account and assign IAM roles
#═══════════════════════════════════════════════════════════════════════════════
create_service_account() {
    log_step "Setting up Service Account"

    local sa_name="${CLUSTER_NAME}-sa"
    local sa_email="${sa_name}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    # Create service account if it doesn't exist
    if ! gcloud iam service-accounts describe "${sa_email}" &>/dev/null; then
        log_info "Creating service account: ${sa_name}"
        gcloud iam service-accounts create "${sa_name}" \
            --display-name="K3s Cluster Service Account for ${CLUSTER_NAME}" \
            --description="Service account for K3s nodes with CCM permissions" \
            --quiet
        log_success "Service account created: ${sa_email}"
    else
        log_info "Service account already exists: ${sa_email}"
    fi

    # Assign required IAM roles for CCM
    log_info "Assigning IAM roles for GCP Cloud Controller Manager..."

    local roles=(
        "roles/compute.admin"
        "roles/iam.serviceAccountUser"
        "roles/storage.objectViewer"
    )

    for role in "${roles[@]}"; do
        log_info "  - Granting ${role}..."
        gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="serviceAccount:${sa_email}" \
            --role="${role}" \
            --condition=None \
            --quiet >/dev/null 2>&1 || log_warn "Role ${role} may already be assigned"
    done

    log_success "Service account configured with CCM permissions"
}

#═══════════════════════════════════════════════════════════════════════════════
# Create Artifact Registry
#═══════════════════════════════════════════════════════════════════════════════
create_artifact_registry() {
    log_step "Setting up Artifact Registry"

    local registry_name="${REGISTRY_NAME:-k3s-platform}"

    # Enable Artifact Registry API
    log_info "Enabling Artifact Registry API..."
    gcloud services enable artifactregistry.googleapis.com --quiet

    # Create repository if it doesn't exist
    if ! gcloud artifacts repositories describe "${registry_name}" \
        --location="${GCP_REGION}" &>/dev/null; then
        log_info "Creating Artifact Registry: ${registry_name}"
        gcloud artifacts repositories create "${registry_name}" \
            --repository-format=docker \
            --location="${GCP_REGION}" \
            --description="K3s Platform container images" \
            --quiet
        log_success "Artifact Registry created: ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${registry_name}"
    else
        log_info "Artifact Registry already exists: ${registry_name}"
    fi

    # Grant service account access to pull images
    local sa_email="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
    log_info "Granting Artifact Registry Reader role to service account..."
    gcloud artifacts repositories add-iam-policy-binding "${registry_name}" \
        --location="${GCP_REGION}" \
        --member="serviceAccount:${sa_email}" \
        --role="roles/artifactregistry.reader" \
        --quiet >/dev/null 2>&1 || log_warn "Permission may already be granted"

    log_success "Artifact Registry configured"
}

#═══════════════════════════════════════════════════════════════════════════════
# Create networking (reuse existing or create new)
#═══════════════════════════════════════════════════════════════════════════════
create_networking() {
    log_step "Setting up firewall rules"

    # Firewall rules - simplified
    log_info "Creating firewall rules..."

    # Internal communication
    if ! gcloud compute firewall-rules describe "${CLUSTER_NAME}-internal" &>/dev/null; then
        log_info "Creating internal firewall rule..."
        gcloud compute firewall-rules create "${CLUSTER_NAME}-internal" \
            --network="${VPC_NAME}" \
            --allow=tcp,udp,icmp \
            --source-ranges="${SUBNET_CIDR:-10.128.0.0/20}" \
            --quiet
    else
        log_info "Internal firewall rule already exists"
    fi

    # SSH via IAP only
    if ! gcloud compute firewall-rules describe "${CLUSTER_NAME}-ssh" &>/dev/null; then
        log_info "Creating SSH (via IAP) firewall rule..."
        gcloud compute firewall-rules create "${CLUSTER_NAME}-ssh" \
            --network="${VPC_NAME}" \
            --allow=tcp:22 \
            --source-ranges="35.235.240.0/20" \
            --target-tags="${CLUSTER_NAME}-node" \
            --quiet
    else
        log_info "SSH firewall rule already exists"
    fi

    # K8s API
    if ! gcloud compute firewall-rules describe "${CLUSTER_NAME}-k8s-api" &>/dev/null; then
        log_info "Creating K8s API firewall rule..."
        gcloud compute firewall-rules create "${CLUSTER_NAME}-k8s-api" \
            --network="${VPC_NAME}" \
            --allow=tcp:6443 \
            --source-ranges="0.0.0.0/0" \
            --target-tags="${CLUSTER_NAME}-control-plane" \
            --quiet
    else
        log_info "K8s API firewall rule already exists"
    fi

    # HTTP/HTTPS for GCP Load Balancer health checks
    if ! gcloud compute firewall-rules describe "${CLUSTER_NAME}-lb-health" &>/dev/null; then
        log_info "Creating LB health check firewall rule..."
        gcloud compute firewall-rules create "${CLUSTER_NAME}-lb-health" \
            --network="${VPC_NAME}" \
            --allow=tcp:80,tcp:443,tcp:8000,tcp:10256 \
            --source-ranges="130.211.0.0/22,35.191.0.0/16" \
            --target-tags="${CLUSTER_NAME}-node" \
            --quiet
    else
        log_info "LB health check firewall rule already exists"
    fi

    # HTTP/HTTPS for external traffic
    if ! gcloud compute firewall-rules describe "${CLUSTER_NAME}-http" &>/dev/null; then
        log_info "Creating HTTP/HTTPS firewall rule for external access..."
        gcloud compute firewall-rules create "${CLUSTER_NAME}-http" \
            --network="${VPC_NAME}" \
            --allow=tcp:80,tcp:443,tcp:8000 \
            --source-ranges="0.0.0.0/0" \
            --target-tags="${CLUSTER_NAME}-node" \
            --quiet
    else
        log_info "HTTP firewall rule already exists"
    fi

    log_success "Networking configured"
}

#═══════════════════════════════════════════════════════════════════════════════
# Deploy control plane
#═══════════════════════════════════════════════════════════════════════════════
deploy_control_plane() {
    log_step "Deploying control plane VM"

    local sa_email="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    # Reserve static IP
    if ! gcloud compute addresses describe "${CLUSTER_NAME}-ip" \
        --region="${GCP_REGION}" &>/dev/null; then
        gcloud compute addresses create "${CLUSTER_NAME}-ip" \
            --region="${GCP_REGION}"
    fi

    CONTROL_PLANE_IP=$(gcloud compute addresses describe "${CLUSTER_NAME}-ip" \
        --region="${GCP_REGION}" --format="value(address)")

    log_info "Control plane IP: ${CONTROL_PLANE_IP}"

    # Create control plane VM
    gcloud compute instances create "${CLUSTER_NAME}-control-plane" \
        --zone="${GCP_ZONE}" \
        --machine-type="${CONTROL_PLANE_TYPE}" \
        --network="${VPC_NAME}" \
        --subnet="${SUBNET_NAME}" \
        --address="${CONTROL_PLANE_IP}" \
        --tags="${CLUSTER_NAME}-control-plane,${CLUSTER_NAME}-node" \
        --service-account="${sa_email}" \
        --scopes="cloud-platform" \
        --image-family="ubuntu-2404-lts-amd64" \
        --image-project="ubuntu-os-cloud" \
        --boot-disk-size="50GB" \
        --boot-disk-type="pd-ssd" \
        --metadata="startup-script=#!/bin/bash
echo 'VM ready. K3s will be installed via bootstrap.sh'"

    if [[ $? -ne 0 ]]; then
        if gcloud compute instances describe "${CLUSTER_NAME}-control-plane" --zone="${GCP_ZONE}" &>/dev/null; then
            log_info "Control plane VM already exists"
        else
            log_error "Failed to create control plane VM"
            return 1
        fi
    fi

    log_success "Control plane VM deployed: ${CONTROL_PLANE_IP}"
}

#═══════════════════════════════════════════════════════════════════════════════
# Deploy worker nodes
#═══════════════════════════════════════════════════════════════════════════════
deploy_workers() {
    log_step "Deploying worker nodes"

    local sa_email="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
    local preemptible_flag=""

    # Check if workers should be preemptible (spot VMs)
    if [[ "${WORKER_PREEMPTIBLE:-false}" == "true" ]]; then
        preemptible_flag="--preemptible"
        log_info "Workers will use preemptible/spot VMs (cost savings, less reliable)"
    else
        log_info "Workers will use standard VMs (production reliability)"
    fi

    # Create instance template
    gcloud compute instance-templates create "${CLUSTER_NAME}-worker-template" \
        --machine-type="${WORKER_NODE_TYPE}" \
        --network="${VPC_NAME}" \
        --subnet="${SUBNET_NAME}" \
        --region="${GCP_REGION}" \
        --no-address \
        --tags="${CLUSTER_NAME}-node" \
        --service-account="${sa_email}" \
        --scopes="cloud-platform" \
        --image-family="ubuntu-2404-lts-amd64" \
        --image-project="ubuntu-os-cloud" \
        --boot-disk-size="30GB" \
        --boot-disk-type="pd-ssd" \
        ${preemptible_flag} \
        --metadata="startup-script=#!/bin/bash
echo 'Worker VM ready. K3s agent will be installed via bootstrap.sh'" 2>/dev/null || log_info "Worker template already exists"

    # Create Managed Instance Group
    # Note: We do NOT configure GCP autoscaling here. The Kubernetes Cluster Autoscaler
    # (deployed in platform/cluster-autoscaler) manages the MIG size based on pending pods.
    # This enables true scale-to-zero when no workloads need worker nodes.
    gcloud compute instance-groups managed create "${CLUSTER_NAME}-workers" \
        --zone="${GCP_ZONE}" \
        --template="${CLUSTER_NAME}-worker-template" \
        --size="${MIN_WORKERS}" 2>/dev/null || log_info "Worker MIG already exists"

    log_success "Worker MIG created (size: ${MIN_WORKERS}, will be managed by Cluster Autoscaler)"
}

#═══════════════════════════════════════════════════════════════════════════════
# Wait for VMs to be ready
#═══════════════════════════════════════════════════════════════════════════════
wait_for_vms() {
    log_step "Waiting for VMs to be ready"

    log_info "Waiting for control plane..."
    until gcloud compute ssh "${CLUSTER_NAME}-control-plane" \
        --zone="${GCP_ZONE}" \
        --tunnel-through-iap \
        --command="echo ready" &>/dev/null; do
        sleep 5
    done

    log_success "VMs are ready for K3s installation"
}

#═══════════════════════════════════════════════════════════════════════════════
# Print next steps
#═══════════════════════════════════════════════════════════════════════════════
print_next_steps() {
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo -e "${GREEN}✅ Infrastructure deployed successfully!${NC}"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Next steps:"
    echo ""
    echo "  1. Bootstrap K3s cluster:"
    echo "     ./providers/gcp/bootstrap.sh"
    echo ""
    echo "  2. Deploy platform components:"
    echo "     cd platform && ./deploy.sh"
    echo ""
    echo "  3. Deploy applications:"
    echo "     kubectl apply -k k8s/overlays/gcp"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
}

#═══════════════════════════════════════════════════════════════════════════════
# Main
#═══════════════════════════════════════════════════════════════════════════════
main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║        K3s Platform - GCP Infrastructure Deployment            ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    create_vpc_and_subnet
    create_service_account
    create_artifact_registry
    create_networking
    deploy_control_plane
    deploy_workers
    wait_for_vms
    print_next_steps
}

main "$@"
