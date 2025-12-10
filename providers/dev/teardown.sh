#!/bin/bash
set -euo pipefail

#===============================================================================
# K3s Development Environment Teardown
#
# Removes the dev k3d cluster and cleans up resources.
#
# Usage:
#   ./providers/dev/teardown.sh
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

CLUSTER_NAME="k3s-dev"

main() {
    echo ""
    echo "================================================================================"
    echo "           K3s Development Environment Teardown"
    echo "================================================================================"
    echo ""

    # Check if cluster exists
    if k3d cluster list | grep -q "${CLUSTER_NAME}"; then
        log_info "Deleting k3d cluster: ${CLUSTER_NAME}..."
        k3d cluster delete "${CLUSTER_NAME}"
        log_success "Cluster deleted"
    else
        log_warn "Cluster ${CLUSTER_NAME} does not exist"
    fi

    # Clean up generated files
    log_info "Cleaning up generated files..."
    find "$(dirname "$0")/../.." -type d -name "generated" -exec rm -rf {} + 2>/dev/null || true

    log_success "Teardown complete"
}

main "$@"
