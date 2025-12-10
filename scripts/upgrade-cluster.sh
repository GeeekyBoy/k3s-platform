#!/bin/bash
set -euo pipefail

#===============================================================================
# K3s Cluster Upgrade Management
#
# Manages K3s cluster upgrades using the system-upgrade-controller.
# Supports zero-downtime upgrades of both control plane and worker nodes.
#
# Usage:
#   ./scripts/upgrade-cluster.sh status       # Show current versions
#   ./scripts/upgrade-cluster.sh apply        # Apply upgrade plans
#   ./scripts/upgrade-cluster.sh version VER  # Set specific version
#   ./scripts/upgrade-cluster.sh channel CH   # Set release channel
#   ./scripts/upgrade-cluster.sh pause        # Pause upgrades
#   ./scripts/upgrade-cluster.sh resume       # Resume upgrades
#===============================================================================

# Colors
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
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat << EOF
Usage: $(basename "$0") [command] [options]

Manage K3s cluster upgrades using system-upgrade-controller.

Commands:
  status        Show current upgrade status
  apply         Apply upgrade plans (starts upgrade)
  version VER   Set specific version to upgrade to
  channel CH    Set release channel (stable, latest, testing)
  pause         Pause all upgrades
  resume        Resume paused upgrades
  
Options:
  -h, --help    Show this help message

Examples:
  $(basename "$0") status
  $(basename "$0") apply
  $(basename "$0") version v1.35.0+k3s1
  $(basename "$0") channel stable

EOF
}

check_cluster() {
    if ! kubectl get nodes &>/dev/null; then
        log_error "Cannot connect to cluster. Check KUBECONFIG."
        exit 1
    fi
}

show_status() {
    log_info "Current K3s versions:"
    kubectl get nodes -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,ROLE:.metadata.labels.node-role\.kubernetes\.io/control-plane'
    
    echo ""
    log_info "Upgrade plans:"
    kubectl get plans -n system-upgrade 2>/dev/null || echo "No plans found"
    
    echo ""
    log_info "Upgrade jobs:"
    kubectl get jobs -n system-upgrade 2>/dev/null || echo "No jobs found"
}

apply_plans() {
    log_info "Applying upgrade plans..."
    kubectl apply -f "${PROJECT_ROOT}/configs/upgrade-plans.yaml"
    log_success "Upgrade plans applied"
    
    echo ""
    log_info "Monitor progress with:"
    echo "  kubectl get plans -n system-upgrade -w"
    echo "  kubectl get nodes -w"
}

set_version() {
    local version="$1"
    
    if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+\+k3s[0-9]+$ ]]; then
        log_error "Invalid version format. Expected: v1.34.2+k3s1"
        exit 1
    fi
    
    log_info "Setting upgrade version to: ${version}"
    
    # Update plans to use specific version
    kubectl patch plan server-plan -n system-upgrade --type=merge \
        -p "{\"spec\":{\"channel\":null,\"version\":\"${version}\"}}"
    kubectl patch plan agent-plan -n system-upgrade --type=merge \
        -p "{\"spec\":{\"channel\":null,\"version\":\"${version}\"}}"
    
    log_success "Version set. Apply changes with: $(basename "$0") apply"
}

set_channel() {
    local channel="$1"
    local channel_url=""
    
    case "$channel" in
        stable)
            channel_url="https://update.k3s.io/v1-release/channels/stable"
            ;;
        latest)
            channel_url="https://update.k3s.io/v1-release/channels/latest"
            ;;
        testing)
            channel_url="https://update.k3s.io/v1-release/channels/testing"
            ;;
        *)
            log_error "Invalid channel. Use: stable, latest, or testing"
            exit 1
            ;;
    esac
    
    log_info "Setting upgrade channel to: ${channel}"
    
    kubectl patch plan server-plan -n system-upgrade --type=merge \
        -p "{\"spec\":{\"version\":null,\"channel\":\"${channel_url}\"}}"
    kubectl patch plan agent-plan -n system-upgrade --type=merge \
        -p "{\"spec\":{\"version\":null,\"channel\":\"${channel_url}\"}}"
    
    log_success "Channel set to ${channel}"
}

pause_upgrades() {
    log_info "Pausing upgrades..."
    
    kubectl annotate plan server-plan -n system-upgrade \
        upgrade.cattle.io/disable=true --overwrite
    kubectl annotate plan agent-plan -n system-upgrade \
        upgrade.cattle.io/disable=true --overwrite
    
    log_success "Upgrades paused"
}

resume_upgrades() {
    log_info "Resuming upgrades..."
    
    kubectl annotate plan server-plan -n system-upgrade \
        upgrade.cattle.io/disable- --overwrite
    kubectl annotate plan agent-plan -n system-upgrade \
        upgrade.cattle.io/disable- --overwrite
    
    log_success "Upgrades resumed"
}

# Main
case "${1:-status}" in
    -h|--help)
        usage
        exit 0
        ;;
    status)
        check_cluster
        show_status
        ;;
    apply)
        check_cluster
        apply_plans
        ;;
    version)
        check_cluster
        if [[ -z "${2:-}" ]]; then
            log_error "Version required"
            exit 1
        fi
        set_version "$2"
        ;;
    channel)
        check_cluster
        if [[ -z "${2:-}" ]]; then
            log_error "Channel required (stable, latest, testing)"
            exit 1
        fi
        set_channel "$2"
        ;;
    pause)
        check_cluster
        pause_upgrades
        ;;
    resume)
        check_cluster
        resume_upgrades
        ;;
    *)
        log_error "Unknown command: $1"
        usage
        exit 1
        ;;
esac
