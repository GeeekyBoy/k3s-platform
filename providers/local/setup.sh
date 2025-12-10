#!/bin/bash
set -euo pipefail

#===============================================================================
# K3s Local Production-Like Environment Setup
#
# Sets up a local k3d cluster for on-premises production-like deployment.
# Key features:
#   - Multiple replicas for HA
#   - HPA enabled for autoscaling
#   - Production security settings
#   - No hot-reload (use dev environment for that)
#   - Full KEDA scale-to-zero support
#
# This is different from dev environment:
#   - dev:   Hot-reload, single replica, debug logging (for development)
#   - local: Production-like, multiple replicas, INFO logging (for on-prem)
#
# Usage:
#   ./providers/local/setup.sh
#===============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLUSTER_NAME="k3s-local"

check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing_tools=()

    for tool in docker k3d kubectl helm yq; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing_tools[*]}"
        echo ""
        echo "Install with:"
        echo "  brew install kubectl helm k3d yq  # macOS"
        echo "  # OR"
        echo "  curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash"
        exit 1
    fi

    # Check Docker is running
    if ! docker info &> /dev/null; then
        log_error "Docker is not running. Please start Docker first."
        exit 1
    fi

    log_success "All prerequisites satisfied"
}

create_cluster() {
    log_info "Creating k3d cluster: ${CLUSTER_NAME}..."

    # Check if cluster already exists
    if k3d cluster list | grep -q "${CLUSTER_NAME}"; then
        log_warn "Cluster ${CLUSTER_NAME} already exists"
        read -p "Delete and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            k3d cluster delete "${CLUSTER_NAME}"
        else
            log_info "Using existing cluster"
            return 0
        fi
    fi

    # Create cluster from config
    cd "${PROJECT_ROOT}"
    k3d cluster create --config "${SCRIPT_DIR}/k3d-config.yaml"

    log_success "Cluster created successfully"
}

wait_for_cluster() {
    log_info "Waiting for cluster to be ready..."

    # Set KUBECONFIG for this session
    export KUBECONFIG="$(k3d kubeconfig write ${CLUSTER_NAME})"

    # Wait for nodes
    kubectl wait --for=condition=Ready nodes --all --timeout=120s

    # Wait for core components
    kubectl wait --for=condition=Available deployment/coredns -n kube-system --timeout=120s
    kubectl wait --for=condition=Available deployment/local-path-provisioner -n kube-system --timeout=120s

    log_success "Cluster is ready"
}

install_traefik() {
    log_info "Installing Traefik ingress controller..."

    helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
    helm repo update traefik

    helm upgrade --install traefik traefik/traefik \
        --namespace kube-system \
        --set ports.web.nodePort=30080 \
        --set ports.websecure.nodePort=30443 \
        --set service.type=NodePort \
        --set providers.kubernetesIngress.enabled=true \
        --set providers.kubernetesCRD.enabled=true \
        --set logs.general.level=INFO \
        --wait

    log_success "Traefik installed"
}

install_keda() {
    log_info "Installing KEDA autoscaler..."

    helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
    helm repo update kedacore

    helm upgrade --install keda kedacore/keda \
        --namespace keda \
        --create-namespace \
        --timeout 600s \
        --wait

    # Install KEDA HTTP Add-on with extended timeouts for cold starts
    log_info "Installing KEDA HTTP Add-on (with extended timeouts)..."
    helm upgrade --install http-add-on kedacore/keda-add-ons-http \
        --namespace keda \
        --set interceptor.replicas.waitTimeout=120s \
        --set interceptor.responseHeaderTimeout=60s \
        --timeout 600s \
        --wait

    log_success "KEDA installed with HTTP Add-on"
}

setup_local_env() {
    log_info "Setting up local environment configuration..."

    # Create local .env if it doesn't exist
    if [[ ! -f "${PROJECT_ROOT}/configs/.env" ]]; then
        cp "${PROJECT_ROOT}/configs/.env.local.example" "${PROJECT_ROOT}/configs/.env"
        log_success "Created configs/.env from local template"
    else
        # Check if it's a local config
        if ! grep -q 'PLATFORM_ENV="local"' "${PROJECT_ROOT}/configs/.env" 2>/dev/null; then
            log_warn "configs/.env exists but is not configured for local environment"
            log_info "Consider copying configs/.env.local.example to configs/.env"
        fi
    fi
}

deploy_apps() {
    log_info "Deploying applications via unified pipeline..."

    # Set environment for deploy-apps.sh
    export KUBECONFIG="$(k3d kubeconfig write ${CLUSTER_NAME})"
    export PLATFORM_ENV="local"

    # Use the unified deployment script
    "${PROJECT_ROOT}/scripts/deploy-apps.sh"
}

print_access_info() {
    echo ""
    echo "================================================================================"
    echo -e "${GREEN}Local Production-Like K3s cluster is ready!${NC}"
    echo "================================================================================"
    echo ""
    echo "Cluster info:"
    echo "  Name:        ${CLUSTER_NAME}"
    echo "  Registry:    registry.localhost:5111"
    echo "  Environment: local (production-like, on-premises)"
    echo ""
    echo "Set kubeconfig:"
    echo "  export KUBECONFIG=\$(k3d kubeconfig write ${CLUSTER_NAME})"
    echo ""
    echo "Access URLs:"
    echo "  HTTP:       http://localhost:8080"
    echo "  HTTPS:      https://localhost:8443"
    echo ""
    echo "Valkey access:"
    echo "  kubectl port-forward svc/valkey -n apps 6379:6379"
    echo "  redis-cli -h localhost -p 6379"
    echo ""
    echo "To deploy/redeploy apps:"
    echo "  PLATFORM_ENV=local ./scripts/deploy-apps.sh"
    echo ""
    echo "For development with hot-reload, use the dev environment instead:"
    echo "  ./providers/dev/setup.sh"
    echo ""
    echo "To teardown:"
    echo "  ./providers/local/teardown.sh"
    echo "================================================================================"
}

main() {
    echo ""
    echo "================================================================================"
    echo "           K3s Local Development Environment Setup"
    echo "================================================================================"
    echo ""

    check_prerequisites
    create_cluster
    wait_for_cluster
    install_traefik
    install_keda
    setup_local_env
    deploy_apps
    print_access_info
}

main "$@"
