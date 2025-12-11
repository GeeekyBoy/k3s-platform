#!/bin/bash
set -euo pipefail

#===============================================================================
# K3s Development Environment Setup (with Tilt Hot-Reload)
#
# Sets up a local k3d cluster optimized for development with Tilt.
# Key features:
#   - Hot-reload via Tilt
#   - Single replicas to save resources
#   - Debug logging
#   - No autoscaling (Tilt manages rebuilds)
#
# Usage:
#   ./providers/dev/setup.sh          # Setup and start Tilt
#   ./providers/dev/setup.sh --no-tilt  # Setup only, don't start Tilt
#===============================================================================

# Colors for output
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
log_step() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLUSTER_NAME="k3s-dev"
START_TILT=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-tilt)
            START_TILT=false
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing_tools=()

    for tool in docker k3d kubectl helm yq tilt; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing_tools[*]}"
        echo ""
        echo "Install with:"
        echo "  brew install kubectl helm k3d yq tilt  # macOS"
        echo "  # OR"
        echo "  curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash"
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

    # Create cluster using local's k3d config but with dev cluster name
    cd "${PROJECT_ROOT}"

    # Create a temporary k3d config for dev with dev cluster name
    cat > "${SCRIPT_DIR}/k3d-config.yaml" <<EOF
# k3d Configuration for Development Environment
# This creates a lightweight cluster optimized for dev with Tilt
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: ${CLUSTER_NAME}
servers: 1
agents: 1
image: rancher/k3s:v1.33.6+k3s1
kubeAPI:
  hostIP: "0.0.0.0"
  hostPort: "6444"
ports:
  - port: 8080:80
    nodeFilters:
      - loadbalancer
  - port: 8443:443
    nodeFilters:
      - loadbalancer
registries:
  create:
    name: registry.localhost
    host: "0.0.0.0"
    hostPort: "5111"
options:
  k3d:
    wait: true
    timeout: "120s"
  k3s:
    extraArgs:
      - arg: --disable=traefik
        nodeFilters:
          - server:*
  kubeconfig:
    updateDefaultKubeconfig: true
    switchCurrentContext: true
EOF

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

    # Enable ExternalName services for KEDA HTTP Add-on routing
    helm upgrade --install traefik traefik/traefik \
        --namespace kube-system \
        --set ports.web.nodePort=30080 \
        --set ports.websecure.nodePort=30443 \
        --set service.type=NodePort \
        --set providers.kubernetesIngress.enabled=true \
        --set providers.kubernetesIngress.allowExternalNameServices=true \
        --set providers.kubernetesCRD.enabled=true \
        --set providers.kubernetesCRD.allowExternalNameServices=true \
        --set logs.general.level=DEBUG \
        --wait

    log_success "Traefik installed (DEBUG logging, ExternalName services enabled)"
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

setup_dev_env() {
    log_info "Setting up development environment configuration..."

    # Create dev .env if it doesn't exist
    if [[ ! -f "${PROJECT_ROOT}/configs/.env" ]]; then
        if [[ -f "${PROJECT_ROOT}/configs/.env.dev.example" ]]; then
            cp "${PROJECT_ROOT}/configs/.env.dev.example" "${PROJECT_ROOT}/configs/.env"
            log_success "Created configs/.env from dev template"
        else
            # Create minimal dev config
            cat > "${PROJECT_ROOT}/configs/.env" <<EOF
# K3s Platform Configuration - DEV
PLATFORM_ENV="dev"
CLUSTER_NAME="${CLUSTER_NAME}"
REGISTRY_NAME="registry.localhost:5111"
VALKEY_PASSWORD=""
KEDA_COOLDOWN_PERIOD="3600"
EOF
            log_success "Created minimal configs/.env for dev"
        fi
    else
        # Check if it's a dev config
        if ! grep -q 'PLATFORM_ENV="dev"' "${PROJECT_ROOT}/configs/.env" 2>/dev/null; then
            log_warn "configs/.env exists but is not configured for dev environment"
            log_info "Consider copying configs/.env.dev.example to configs/.env"
        fi
    fi

    # Create apps namespace
    kubectl create namespace apps --dry-run=client -o yaml | kubectl apply -f -
}

deploy_infrastructure() {
    log_info "Deploying infrastructure (Valkey)..."

    # Add Helm repos
    helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
    helm repo update

    # Deploy Valkey if values file exists
    if [[ -f "${PROJECT_ROOT}/apps/valkey/values.yaml" ]]; then
        helm upgrade --install valkey bitnami/valkey \
            --namespace apps \
            --values "${PROJECT_ROOT}/apps/valkey/values.yaml" \
            --wait --timeout 300s
        log_success "Valkey deployed"
    else
        log_warn "Valkey values file not found, skipping"
    fi
}

start_tilt() {
    if [[ "${START_TILT}" == "true" ]]; then
        log_step "Starting Tilt Development Environment"

        echo ""
        echo "================================================================================"
        echo -e "${GREEN}Starting Tilt...${NC}"
        echo "================================================================================"
        echo ""
        echo "Tilt will now:"
        echo "  1. Build Docker images with live-update"
        echo "  2. Deploy to the dev cluster"
        echo "  3. Watch for file changes and hot-reload"
        echo ""
        echo "Press Ctrl+C to stop Tilt"
        echo ""

        cd "${PROJECT_ROOT}"
        export KUBECONFIG="$(k3d kubeconfig write ${CLUSTER_NAME})"
        tilt up
    fi
}

print_access_info() {
    echo ""
    echo "================================================================================"
    echo -e "${GREEN}Dev K3s cluster is ready!${NC}"
    echo "================================================================================"
    echo ""
    echo "Cluster info:"
    echo "  Name:       ${CLUSTER_NAME}"
    echo "  Registry:   registry.localhost:5111"
    echo "  Environment: dev (hot-reload enabled)"
    echo ""
    echo "Set kubeconfig:"
    echo "  export KUBECONFIG=\$(k3d kubeconfig write ${CLUSTER_NAME})"
    echo ""
    echo "Start Tilt for development:"
    echo "  cd ${PROJECT_ROOT}"
    echo "  tilt up"
    echo ""
    echo "Tilt options:"
    echo "  tilt up -- --no-valkey      # Skip Valkey"
    echo "  tilt up -- --only fastapi   # Only run FastAPI"
    echo "  tilt up -- --exclude valkey # Exclude Valkey"
    echo ""
    echo "Access URLs (when Tilt is running):"
    echo "  Tilt UI:    http://localhost:10350"
    echo "  FastAPI:    http://localhost:8000"
    echo "  Serverless: http://localhost:8081"
    echo ""
    echo "To teardown:"
    echo "  ./providers/dev/teardown.sh"
    echo "================================================================================"
}

main() {
    echo ""
    echo "================================================================================"
    echo "           K3s Development Environment Setup (Tilt)"
    echo "================================================================================"
    echo ""

    check_prerequisites
    create_cluster
    wait_for_cluster
    install_traefik
    install_keda
    setup_dev_env
    deploy_infrastructure
    print_access_info
    start_tilt
}

main "$@"
