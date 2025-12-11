#!/bin/bash
set -euo pipefail

#═══════════════════════════════════════════════════════════════════════════════
# K3s Bootstrap Script - Minimal K3s Installation Only
#
# This script ONLY installs K3s on VMs. Nothing else.
# Platform components (CCM, KEDA, etc.) are deployed separately via kubectl.
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
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
CLUSTER_NAME="${CLUSTER_NAME:-k3s-cluster}"
K3S_VERSION="${K3S_VERSION:-v1.33.6+k3s1}"

#═══════════════════════════════════════════════════════════════════════════════
# Get control plane info
#═══════════════════════════════════════════════════════════════════════════════
get_control_plane_ip() {
    gcloud compute instances describe "${CLUSTER_NAME}-control-plane" \
        --zone="${GCP_ZONE}" \
        --format="value(networkInterfaces[0].accessConfigs[0].natIP)"
}

get_control_plane_internal_ip() {
    gcloud compute instances describe "${CLUSTER_NAME}-control-plane" \
        --zone="${GCP_ZONE}" \
        --format="value(networkInterfaces[0].networkIP)"
}

#═══════════════════════════════════════════════════════════════════════════════
# Bootstrap control plane
#═══════════════════════════════════════════════════════════════════════════════
bootstrap_control_plane() {
    log_step "Bootstrapping K3s control plane"

    local control_plane_ip=$(get_control_plane_ip)
    
    # Check for existing token
    log_info "Checking for existing K3s installation..."
    local existing_token=""
    if gcloud compute ssh "${CLUSTER_NAME}-control-plane" --zone="${GCP_ZONE}" --tunnel-through-iap --command="sudo cat /var/lib/rancher/k3s/server/token" 2>/dev/null; then
        existing_token=$(gcloud compute ssh "${CLUSTER_NAME}-control-plane" --zone="${GCP_ZONE}" --tunnel-through-iap --command="sudo cat /var/lib/rancher/k3s/server/token")
        log_info "Found existing K3s token."
    fi

    local k3s_token=""
    if [[ -n "$existing_token" ]]; then
        k3s_token="$existing_token"
    else
        k3s_token=$(openssl rand -hex 32)
    fi

    log_info "Installing/Configuring K3s ${K3S_VERSION} on control plane..."

    # Create minimal K3s server install script with best practices
    cat > /tmp/install-k3s-server.sh << 'EOF'
#!/bin/bash
set -e

# Install K3s server with production config
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="K3S_VERSION_PLACEHOLDER" sh -s - server \
    --token="K3S_TOKEN_PLACEHOLDER" \
    --tls-san="CONTROL_PLANE_IP_PLACEHOLDER" \
    --disable-cloud-controller \
    --disable=servicelb \
    --kubelet-arg="cloud-provider=external" \
    --node-label="node.kubernetes.io/instance-type=CONTROL_PLANE_TYPE_PLACEHOLDER" \
    --node-taint="node-role.kubernetes.io/control-plane:NoSchedule" \
    --write-kubeconfig-mode=600 \
    --embedded-registry

# Ensure K3s systemd service is active
echo "Waiting for K3s systemd service..."
until systemctl is-active --quiet k3s; do
    echo "K3s service not yet active, waiting..."
    sleep 3
done
echo "K3s systemd service is active"

# Wait for K3s API to be ready
echo "Waiting for K3s API server..."
until kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get nodes &>/dev/null; do
    echo "API server not ready yet, waiting..."
    sleep 5
done

# System pods will schedule after CCM removes the uninitialized taint
echo "K3s API server ready"
EOF

    # Replace placeholders (cross-platform compatible)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|K3S_VERSION_PLACEHOLDER|${K3S_VERSION}|g" /tmp/install-k3s-server.sh
        sed -i '' "s|K3S_TOKEN_PLACEHOLDER|${k3s_token}|g" /tmp/install-k3s-server.sh
        sed -i '' "s|CONTROL_PLANE_IP_PLACEHOLDER|${control_plane_ip}|g" /tmp/install-k3s-server.sh
        sed -i '' "s|CONTROL_PLANE_TYPE_PLACEHOLDER|${CONTROL_PLANE_TYPE:-e2-standard-2}|g" /tmp/install-k3s-server.sh
    else
        sed -i "s|K3S_VERSION_PLACEHOLDER|${K3S_VERSION}|g" /tmp/install-k3s-server.sh
        sed -i "s|K3S_TOKEN_PLACEHOLDER|${k3s_token}|g" /tmp/install-k3s-server.sh
        sed -i "s|CONTROL_PLANE_IP_PLACEHOLDER|${control_plane_ip}|g" /tmp/install-k3s-server.sh
        sed -i "s|CONTROL_PLANE_TYPE_PLACEHOLDER|${CONTROL_PLANE_TYPE:-e2-standard-2}|g" /tmp/install-k3s-server.sh
    fi
    rm -f /tmp/install-k3s-server.sh.bak

    # Copy and execute on control plane
    gcloud compute scp /tmp/install-k3s-server.sh \
        "${CLUSTER_NAME}-control-plane":/tmp/install-k3s.sh \
        --zone="${GCP_ZONE}" \
        --tunnel-through-iap

    gcloud compute ssh "${CLUSTER_NAME}-control-plane" \
        --zone="${GCP_ZONE}" \
        --tunnel-through-iap \
        --command="chmod +x /tmp/install-k3s.sh && sudo /tmp/install-k3s.sh"

    # Save token for workers (secure file in user's home, not world-readable /tmp)
    local token_dir="${HOME}/.k3s"
    mkdir -p "${token_dir}"
    chmod 700 "${token_dir}"
    echo "${k3s_token}" > "${token_dir}/token"
    chmod 600 "${token_dir}/token"
    export K3S_TOKEN_FILE="${token_dir}/token"

    # Wait for API server to be fully ready
    log_info "Waiting for API server to be fully ready..."
    local max_wait=180
    local elapsed=0
    while [[ $elapsed -lt $max_wait ]]; do
        if gcloud compute ssh "${CLUSTER_NAME}-control-plane" \
            --zone="${GCP_ZONE}" \
            --tunnel-through-iap \
            --command="sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get nodes" &>/dev/null; then
            log_success "API server is ready!"
            break
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        if [[ $((elapsed % 30)) -eq 0 ]]; then
            log_info "Still waiting for API server... (${elapsed}s/${max_wait}s)"
        fi
    done

    if [[ $elapsed -ge $max_wait ]]; then
        log_error "API server failed to become ready within ${max_wait}s"
        return 1
    fi

    log_success "Control plane bootstrapped and API server is ready"
}

#═══════════════════════════════════════════════════════════════════════════════
# Get kubeconfig
#═══════════════════════════════════════════════════════════════════════════════
get_kubeconfig() {
    log_step "Retrieving kubeconfig"

    local control_plane_ip=$(get_control_plane_ip)
    local retries=10

    while [[ $retries -gt 0 ]]; do
        if gcloud compute ssh "${CLUSTER_NAME}-control-plane" \
            --tunnel-through-iap \
            --zone="${GCP_ZONE}" \
            --command="sudo cat /etc/rancher/k3s/k3s.yaml" > /tmp/k3s-kubeconfig 2>/dev/null; then

            # Update kubeconfig with external IP and secure permissions
            mkdir -p ~/.kube
            sed "s|127.0.0.1|${control_plane_ip}|g" /tmp/k3s-kubeconfig > ~/.kube/k3s-gcp-config
            chmod 600 ~/.kube/k3s-gcp-config
            rm -f /tmp/k3s-kubeconfig

            # Test connection
            if KUBECONFIG=~/.kube/k3s-gcp-config kubectl get nodes &>/dev/null; then
                log_success "Kubeconfig retrieved: ~/.kube/k3s-gcp-config (permissions: 600)"
                echo "export KUBECONFIG=~/.kube/k3s-gcp-config"
                return 0
            fi
        fi

        log_info "Waiting for K3s... (${retries} retries left)"
        sleep 10
        ((retries--))
    done

    log_error "Failed to retrieve kubeconfig"
    return 1
}

#═══════════════════════════════════════════════════════════════════════════════
# Bootstrap workers
#═══════════════════════════════════════════════════════════════════════════════
bootstrap_workers() {
    log_step "Bootstrapping K3s workers"

    # Get token from secure location
    local token_file="${HOME}/.k3s/token"
    if [[ ! -f "${token_file}" ]]; then
        log_error "K3s token file not found. Run bootstrap_control_plane first."
        return 1
    fi
    local k3s_token=$(cat "${token_file}")
    local control_plane_ip=$(get_control_plane_internal_ip)

    log_info "Getting worker instances..."
    local workers=$(gcloud compute instances list \
        --filter="name~${CLUSTER_NAME}-workers" \
        --format="value(name,zone)")

    if [[ -z "$workers" ]]; then
        log_warn "No worker nodes found. They may not be created yet."
        return 0
    fi

    # Install K3s agent on each worker (sequentially with retry)
    local failed_workers=()
    while IFS=$'\t' read -r name zone; do
        log_info "Waiting for ${name} to be SSH-ready..."
        for i in {1..30}; do
            if gcloud compute ssh "${name}" --zone="${zone}" --tunnel-through-iap --command="echo ready" &>/dev/null; then
                break
            fi
            sleep 5
        done

        log_info "Installing K3s agent on ${name}..."

        cat > /tmp/install-k3s-agent.sh << 'EOF'
#!/bin/bash
set -e

# Wait for API server to be reachable (TCP check)
MAX_RETRIES=30
RETRY_COUNT=0
until timeout 5 bash -c "echo >/dev/tcp/CONTROL_PLANE_IP_PLACEHOLDER/6443" 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [[ $RETRY_COUNT -ge $MAX_RETRIES ]]; then
        echo "ERROR: API server not reachable after ${MAX_RETRIES} attempts"
        exit 1
    fi
    echo "Waiting for API server to be reachable... (attempt ${RETRY_COUNT}/${MAX_RETRIES})"
    sleep 10
done

echo "API server is reachable, installing K3s agent..."

# Install K3s without starting it (avoids blocking on systemd)
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="K3S_VERSION_PLACEHOLDER" \
    INSTALL_K3S_SKIP_START=true \
    K3S_URL="https://CONTROL_PLANE_IP_PLACEHOLDER:6443" \
    K3S_TOKEN="K3S_TOKEN_PLACEHOLDER" \
    sh -s - agent \
    --kubelet-arg="cloud-provider=external" \
    --node-label="node.kubernetes.io/instance-type=WORKER_NODE_TYPE_PLACEHOLDER" \
    --node-label="cloud.google.com/gke-spot=true"

# Start k3s-agent in background (don't wait for systemd 'active' - that requires CCM)
echo "Starting K3s agent service..."
systemctl start k3s-agent --no-block

# Wait for process to be running (not systemd active state)
AGENT_RETRIES=0
MAX_AGENT_RETRIES=30
until pgrep -f "k3s agent" > /dev/null; do
    AGENT_RETRIES=$((AGENT_RETRIES + 1))
    if [[ $AGENT_RETRIES -ge $MAX_AGENT_RETRIES ]]; then
        echo "ERROR: K3s agent process failed to start"
        systemctl status k3s-agent --no-pager || true
        exit 1
    fi
    echo "Waiting for K3s agent process... (${AGENT_RETRIES}/${MAX_AGENT_RETRIES})"
    sleep 2
done

echo "K3s agent started - will become fully ready after CCM deployment"
EOF

        # Substitute placeholders (cross-platform compatible)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' \
                -e "s|K3S_VERSION_PLACEHOLDER|${K3S_VERSION}|g" \
                -e "s|CONTROL_PLANE_IP_PLACEHOLDER|${control_plane_ip}|g" \
                -e "s|K3S_TOKEN_PLACEHOLDER|${k3s_token}|g" \
                -e "s|WORKER_NODE_TYPE_PLACEHOLDER|${WORKER_NODE_TYPE:-e2-medium}|g" \
                /tmp/install-k3s-agent.sh
        else
            sed -i \
                -e "s|K3S_VERSION_PLACEHOLDER|${K3S_VERSION}|g" \
                -e "s|CONTROL_PLANE_IP_PLACEHOLDER|${control_plane_ip}|g" \
                -e "s|K3S_TOKEN_PLACEHOLDER|${k3s_token}|g" \
                -e "s|WORKER_NODE_TYPE_PLACEHOLDER|${WORKER_NODE_TYPE:-e2-medium}|g" \
                /tmp/install-k3s-agent.sh
        fi

        # Copy and execute with timeout
        if gcloud compute scp /tmp/install-k3s-agent.sh \
            "${name}":/tmp/install-k3s.sh \
            --zone="${zone}" \
            --tunnel-through-iap --quiet 2>/dev/null; then

            # Use gtimeout on macOS, timeout on Linux
            TIMEOUT_CMD="timeout"
            command -v timeout &>/dev/null || TIMEOUT_CMD="gtimeout"

            if $TIMEOUT_CMD 600 gcloud compute ssh "${name}" \
                --zone="${zone}" \
                --tunnel-through-iap \
                --command="chmod +x /tmp/install-k3s.sh && sudo /tmp/install-k3s.sh" 2>&1 | tee /tmp/worker-${name}.log; then
                log_success "  ✓ ${name} joined successfully"
            else
                log_error "  ✗ ${name} failed to join (timeout or error)"
                failed_workers+=("${name}")
            fi
        else
            log_error "  ✗ ${name} failed to copy install script"
            failed_workers+=("${name}")
        fi
    done <<< "$workers"

    # Report results
    if [[ ${#failed_workers[@]} -gt 0 ]]; then
        log_warn "Some workers failed to join: ${failed_workers[*]}"
        log_warn "Workers will auto-join via self-healing startup script"
    else
        log_success "All workers bootstrapped successfully"
    fi
}

#═══════════════════════════════════════════════════════════════════════════════
# Configure Self-Healing (Auto-Join)
#═══════════════════════════════════════════════════════════════════════════════
configure_self_healing() {
    log_step "Configuring Self-Healing (Auto-Join)"

    # Get token from secure location
    local token_file="${HOME}/.k3s/token"
    if [[ ! -f "${token_file}" ]]; then
        log_error "K3s token file not found. Cannot configure self-healing."
        return 1
    fi
    local k3s_token=$(cat "${token_file}")
    local control_plane_ip=$(get_control_plane_internal_ip)
    local sa_email="${CLUSTER_NAME}-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    log_info "Creating self-healing instance template..."

    # Define startup script that runs on every boot
    local startup_script="#!/bin/bash
set -e
echo 'Self-healing: Checking K3s status...'

if ! systemctl is-active --quiet k3s-agent; then
    echo 'K3s agent not running. Installing...'
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=\"${K3S_VERSION}\" \
        K3S_URL=\"https://${control_plane_ip}:6443\" \
        K3S_TOKEN=\"${k3s_token}\" \
        sh -s - agent \
        --kubelet-arg=\"cloud-provider=external\" \
        --node-label=\"node.kubernetes.io/instance-type=${WORKER_NODE_TYPE:-e2-medium}\" \
        --node-label=\"cloud.google.com/gke-spot=true\"
    echo 'K3s agent installed successfully!'
else
    echo 'K3s agent already running.'
fi
"

    # Create new template with startup script
    # We use --force to overwrite if exists (simplified update)
    gcloud compute instance-templates delete "${CLUSTER_NAME}-worker-template-self-healing" --quiet 2>/dev/null || true

    local preemptible_flag=""
    if [[ "${WORKER_PREEMPTIBLE:-false}" == "true" ]]; then
        preemptible_flag="--preemptible"
    fi

    gcloud compute instance-templates create "${CLUSTER_NAME}-worker-template-self-healing" \
        --machine-type="${WORKER_NODE_TYPE:-e2-medium}" \
        --network="${VPC_NAME:-k3s-vpc}" \
        --subnet="${SUBNET_NAME:-k3s-subnet}" \
        --region="${GCP_REGION:-us-central1}" \
        --no-address \
        --tags="${CLUSTER_NAME}-node" \
        --service-account="${sa_email}" \
        --scopes="cloud-platform" \
        --image-family="ubuntu-2404-lts-amd64" \
        --image-project="ubuntu-os-cloud" \
        --boot-disk-size="30GB" \
        --boot-disk-type="pd-ssd" \
        ${preemptible_flag} \
        --metadata="startup-script=${startup_script}" \
        --quiet

    log_info "Updating Managed Instance Group to use self-healing template..."
    
    gcloud compute instance-groups managed set-instance-template "${CLUSTER_NAME}-workers" \
        --template="${CLUSTER_NAME}-worker-template-self-healing" \
        --zone="${GCP_ZONE}" \
        --quiet

    # Trigger replacement of instances with proper rolling update (no downtime)
    log_info "Rolling update to apply self-healing config (gradual, no downtime)..."
    gcloud compute instance-groups managed rolling-action replace "${CLUSTER_NAME}-workers" \
        --zone="${GCP_ZONE}" \
        --max-surge=1 \
        --max-unavailable=0 \
        --replacement-method=substitute \
        --quiet || log_warn "Rolling update failed, but self-healing template is set for new instances"

    log_success "Cluster is now self-healing! New nodes will auto-join."
}

#═══════════════════════════════════════════════════════════════════════════════
# Verify cluster
#═══════════════════════════════════════════════════════════════════════════════
verify_cluster() {
    log_step "Verifying cluster"

    export KUBECONFIG=~/.kube/k3s-gcp-config

    log_info "Waiting for all nodes to be ready..."

    # First, wait for kubectl to work
    local kubectl_ready=false
    for i in {1..30}; do
        if kubectl get nodes &>/dev/null; then
            kubectl_ready=true
            break
        fi
        log_info "Waiting for API server... (${i}/30)"
        sleep 5
    done

    if [[ "${kubectl_ready}" != "true" ]]; then
        log_error "Could not connect to cluster"
        return 1
    fi

    # Wait for nodes to be ready (with timeout)
    log_info "Waiting for nodes to be Ready..."
    if kubectl wait --for=condition=Ready nodes --all --timeout=300s 2>/dev/null; then
        log_success "All nodes are Ready!"
    else
        log_warn "Some nodes may not be ready yet"
    fi

    # Show final status
    echo ""
    kubectl get nodes -o wide
    echo ""

    # Note: System pods won't be ready until CCM is deployed (removes uninitialized taint)
    log_info "System pods status (will become Ready after CCM deployment):"
    kubectl get pods -n kube-system || true
}

#═══════════════════════════════════════════════════════════════════════════════
# Main
#═══════════════════════════════════════════════════════════════════════════════
main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║           K3s Bootstrap - Minimal Installation                 ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    bootstrap_control_plane
    get_kubeconfig
    bootstrap_workers
    configure_self_healing
    verify_cluster

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo -e "${GREEN}✅ K3s cluster bootstrapped successfully!${NC}"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Next steps:"
    echo "  1. export KUBECONFIG=~/.kube/k3s-gcp-config"
    echo "  2. Deploy platform components:"
    echo "     cd ${PROJECT_ROOT}/platform && ./deploy.sh"
    echo "  3. Deploy applications:"
    echo "     kubectl apply -k ${PROJECT_ROOT}/k8s/overlays/gcp"
    echo ""
}

main "$@"
