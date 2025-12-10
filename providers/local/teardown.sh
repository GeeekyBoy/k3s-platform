#!/bin/bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "[INFO] $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

CLUSTER_NAME="k3s-local"

main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║             K3s Local Environment Teardown                    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Stop Tilt if running
    if pgrep -f "tilt up" > /dev/null 2>&1; then
        log_info "Stopping Tilt..."
        pkill -f "tilt up" || true
    fi
    
    # Delete k3d cluster
    if k3d cluster list 2>/dev/null | grep -q "${CLUSTER_NAME}"; then
        log_info "Deleting k3d cluster: ${CLUSTER_NAME}..."
        k3d cluster delete "${CLUSTER_NAME}"
        log_success "Cluster deleted"
    else
        log_warn "Cluster ${CLUSTER_NAME} not found"
    fi
    
    # Clean up k3d registry
    if docker ps -a | grep -q "k3d-${CLUSTER_NAME}-registry"; then
        log_info "Removing local registry..."
        docker rm -f "k3d-${CLUSTER_NAME}-registry" 2>/dev/null || true
    fi
    
    # Clean up Docker network
    if docker network ls | grep -q "k3s-network"; then
        log_info "Removing Docker network..."
        docker network rm k3s-network 2>/dev/null || true
    fi
    
    # Clean up dangling images (optional)
    read -p "Clean up dangling Docker images? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleaning up dangling images..."
        docker image prune -f
    fi
    
    echo ""
    log_success "Local environment cleaned up successfully!"
    echo ""
}

main "$@"
