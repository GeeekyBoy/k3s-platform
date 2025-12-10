#!/bin/bash
set -euo pipefail

#===============================================================================
# Direct Application Deployment
#
# Deploys applications directly to the cluster without ArgoCD.
# Useful for quick testing, CI/CD pipelines, or debugging.
#
# For GitOps deployments, use:
#   ./scripts/generate-argocd-state.sh [local|gcp]
#
# Usage:
#   ./scripts/deploy-apps.sh                       # Uses configs/.env
#   PLATFORM_ENV=local ./scripts/deploy-apps.sh   # Force local mode
#   PLATFORM_ENV=gcp ./scripts/deploy-apps.sh     # Force GCP mode
#===============================================================================

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_step() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

#===============================================================================
# Environment Detection and Configuration
#===============================================================================

# Default to GCP if not specified
PLATFORM_ENV="${PLATFORM_ENV:-}"

# Load configuration
if [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
elif [[ -n "${PLATFORM_ENV}" ]]; then
    log_warn "No configs/.env found, using environment variables"
else
    log_error "Configuration file not found: configs/.env"
    log_info "Copy configs/.env.example (GCP) or configs/.env.local.example (local) to configs/.env"
    exit 1
fi

# Detect environment from config or override
PLATFORM_ENV="${PLATFORM_ENV:-gcp}"

log_info "Platform environment: ${PLATFORM_ENV}"

# Set environment-specific defaults
case "${PLATFORM_ENV}" in
    dev)
        # Dev k3d environment (hot-reload with Tilt)
        export KUBECONFIG="${KUBECONFIG:-$(k3d kubeconfig write k3s-dev 2>/dev/null || echo ~/.kube/config)}"
        REGISTRY="${REGISTRY_NAME:-registry.localhost:5111}"
        BUILD_METHOD="docker"
        OVERLAY_PATH="dev"
        ;;
    local)
        # Local k3d environment (production-like, on-premises)
        export KUBECONFIG="${KUBECONFIG:-$(k3d kubeconfig write k3s-local 2>/dev/null || echo ~/.kube/config)}"
        REGISTRY="${REGISTRY_NAME:-registry.localhost:5111}"
        BUILD_METHOD="docker"
        OVERLAY_PATH="local"
        ;;
    gcp)
        # GCP cloud environment
        export KUBECONFIG="${KUBECONFIG:-~/.kube/k3s-gcp-config}"
        REGISTRY="${GCP_REGION:-us-central1}-docker.pkg.dev/${GCP_PROJECT_ID}/${REGISTRY_NAME:-k3s-platform}"
        BUILD_METHOD="cloudbuild"
        OVERLAY_PATH="gcp"
        ;;
    *)
        log_error "Unknown PLATFORM_ENV: ${PLATFORM_ENV}"
        log_info "Supported environments: dev, local, gcp"
        exit 1
        ;;
esac

# Verify kubeconfig
if ! kubectl cluster-info &>/dev/null; then
    log_error "Cannot connect to cluster. Check KUBECONFIG: ${KUBECONFIG}"
    exit 1
fi

# Check if yq is available for YAML parsing
if ! command -v yq &>/dev/null; then
    log_error "yq is not installed. Install with: brew install yq (Mac) or snap install yq (Linux)"
    exit 1
fi

APPS_FILE="${PROJECT_ROOT}/apps.yaml"

if [[ ! -f "${APPS_FILE}" ]]; then
    log_error "apps.yaml not found at: ${APPS_FILE}"
    exit 1
fi

log_step "Deploying Applications from apps.yaml"
log_info "Registry: ${REGISTRY}"
log_info "Build method: ${BUILD_METHOD}"

#===============================================================================
# Add Helm Repositories
#===============================================================================
log_info "Adding Helm repositories..."
yq eval '.repositories | to_entries | .[] | .key + " " + .value' "${APPS_FILE}" 2>/dev/null | while read -r repo_name repo_url; do
    if [[ -n "${repo_name}" && -n "${repo_url}" ]]; then
        log_info "  Adding ${repo_name}: ${repo_url}"
        helm repo add "${repo_name}" "${repo_url}" 2>/dev/null || true
    fi
done

helm repo update 2>/dev/null || true

#===============================================================================
# Deploy Helm Charts
#===============================================================================
log_step "Deploying Helm Charts"

helm_count=$(yq eval '.helm | length' "${APPS_FILE}" 2>/dev/null || echo "0")

if [[ "${helm_count}" -gt 0 ]]; then
    for ((i=0; i<helm_count; i++)); do
        enabled=$(yq eval ".helm[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

        if [[ "${enabled}" == "true" ]]; then
            name=$(yq eval ".helm[${i}].name" "${APPS_FILE}")
            chart=$(yq eval ".helm[${i}].chart" "${APPS_FILE}")
            namespace=$(yq eval ".helm[${i}].namespace" "${APPS_FILE}")
            values=$(yq eval ".helm[${i}].values" "${APPS_FILE}")

            log_info "Deploying ${name} (${chart})..."

            # Create namespace
            kubectl create namespace "${namespace}" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true

            # Deploy with Helm
            if [[ -f "${PROJECT_ROOT}/${values}" ]]; then
                helm upgrade --install "${name}" "${chart}" \
                    --namespace "${namespace}" \
                    --values "${PROJECT_ROOT}/${values}" \
                    --wait --timeout 600s
                log_success "  ${name} deployed"
            else
                log_warn "  Values file not found: ${values}"
            fi
        else
            name=$(yq eval ".helm[${i}].name" "${APPS_FILE}")
            log_info "Skipping ${name} (disabled)"
        fi
    done
else
    log_info "No Helm charts to deploy"
fi

#===============================================================================
# Deploy Kustomize Overlays
#===============================================================================
log_step "Deploying Kustomize Overlays"

kustomize_count=$(yq eval '.kustomize | length' "${APPS_FILE}" 2>/dev/null || echo "0")

if [[ "${kustomize_count}" -gt 0 ]]; then
    for ((i=0; i<kustomize_count; i++)); do
        enabled=$(yq eval ".kustomize[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

        if [[ "${enabled}" == "true" ]]; then
            name=$(yq eval ".kustomize[${i}].name" "${APPS_FILE}")
            path_template=$(yq eval ".kustomize[${i}].path" "${APPS_FILE}")

            # Substitute environment in path using OVERLAY_PATH
            # e.g., k8s/overlays/${PLATFORM_ENV} -> k8s/overlays/dev
            path="${path_template//\$\{PLATFORM_ENV\}/${OVERLAY_PATH}}"

            log_info "Deploying ${name} (${path})..."

            if [[ -d "${PROJECT_ROOT}/${path}" ]]; then
                cd "${PROJECT_ROOT}/${path}"

                # Build and apply with environment-specific substitutions
                case "${PLATFORM_ENV}" in
                    dev|local)
                        kubectl kustomize . | kubectl apply -f -
                        ;;
                    gcp)
                        kubectl kustomize . | \
                            sed -e "s|\${GCP_PROJECT_ID}|${GCP_PROJECT_ID}|g" \
                                -e "s|\${GCP_REGION}|${GCP_REGION}|g" \
                                -e "s|\${REGISTRY_NAME}|${REGISTRY_NAME}|g" \
                                -e "s|image: fastapi-app:latest|image: ${REGISTRY}/fastapi:latest|g" | \
                            kubectl apply -f -
                        ;;
                esac

                log_success "  ${name} deployed"
            else
                log_warn "  Path not found: ${path}"
            fi
        else
            name=$(yq eval ".kustomize[${i}].name" "${APPS_FILE}")
            log_info "Skipping ${name} (disabled)"
        fi
    done
else
    log_info "No Kustomize overlays to deploy"
fi

#===============================================================================
# Deploy Serverless Functions (k3sfn)
#===============================================================================
log_step "Deploying Serverless Functions"

serverless_count=$(yq eval '.serverless | length' "${APPS_FILE}" 2>/dev/null || echo "0")

if [[ "${serverless_count}" -gt 0 ]]; then
    # Ensure k3sfn SDK is installed
    if ! uv run python3 -c "import k3sfn" 2>/dev/null; then
        log_info "Installing k3sfn SDK..."
        uv pip install -e "${PROJECT_ROOT}/libs/k3sfn" --quiet
    fi

    for ((i=0; i<serverless_count; i++)); do
        enabled=$(yq eval ".serverless[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

        if [[ "${enabled}" == "true" ]]; then
            name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
            path=$(yq eval ".serverless[${i}].path" "${APPS_FILE}")
            namespace=$(yq eval ".serverless[${i}].namespace" "${APPS_FILE}")

            log_info "Deploying serverless app: ${name}"

            APP_DIR="${PROJECT_ROOT}/${path}"
            if [[ ! -d "${APP_DIR}" ]]; then
                log_warn "  App directory not found: ${path}"
                continue
            fi

            # Check if it's a serverless app (has functions/ directory)
            if [[ ! -d "${APP_DIR}/functions" ]]; then
                log_warn "  Not a serverless app (no functions/ directory): ${path}"
                continue
            fi

            # Discover functions
            log_info "  Discovering functions..."
            cd "${APP_DIR}"
            uv run python3 -m k3sfn.cli list . 2>/dev/null || true

            # Generate manifests
            OUTPUT_DIR="${APP_DIR}/generated"
            rm -rf "${OUTPUT_DIR}"

            log_info "  Generating Kubernetes manifests..."
            uv run python3 -m k3sfn.cli generate . \
                --name "${name}" \
                --output "${OUTPUT_DIR}" \
                --namespace "${namespace}" \
                --registry "${REGISTRY}"

            # Build Docker image based on environment
            IMAGE_TAG="${REGISTRY}/${name}:latest"
            log_info "  Building Docker image: ${IMAGE_TAG}"

            if [[ "${BUILD_METHOD}" == "cloudbuild" ]]; then
                # GCP: Use Cloud Build with dynamic cloudbuild.yaml
                # Dockerfile path relative to project root
                DOCKERFILE_REL="${path}/generated/Dockerfile"
                CLOUDBUILD_CONFIG="${OUTPUT_DIR}/cloudbuild.yaml"

                cat > "${CLOUDBUILD_CONFIG}" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE_TAG}', '-f', '${DOCKERFILE_REL}', '.']
images:
  - '${IMAGE_TAG}'
EOF

                gcloud builds submit "${PROJECT_ROOT}" \
                    --config="${CLOUDBUILD_CONFIG}" \
                    --project "${GCP_PROJECT_ID}" \
                    --quiet
            else
                # Local: Use local Docker with k3d registry
                docker build \
                    -f "${OUTPUT_DIR}/Dockerfile" \
                    -t "${IMAGE_TAG}" \
                    "${PROJECT_ROOT}"

                # Push to k3d local registry
                docker push "${IMAGE_TAG}"
            fi

            log_success "  Image built: ${IMAGE_TAG}"

            # Deploy to Kubernetes
            log_info "  Applying manifests..."
            kubectl create namespace "${namespace}" 2>/dev/null || true
            kubectl apply -f "${OUTPUT_DIR}/manifests.yaml"

            # Wait for deployments
            log_info "  Waiting for deployments..."
            for deploy in $(kubectl get deployments -n "${namespace}" -l "k3sfn.io/app=${name}" -o name 2>/dev/null); do
                kubectl rollout status "${deploy}" -n "${namespace}" --timeout=120s 2>/dev/null || true
            done

            log_success "  ${name} deployed"
        else
            name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
            log_info "Skipping ${name} (disabled)"
        fi
    done
else
    log_info "No serverless apps to deploy"
fi

#===============================================================================
# Complete
#===============================================================================
log_step "Deployment Complete"
log_success "All enabled applications deployed successfully!"

echo ""
echo "To check status:"
echo "  kubectl get all -n apps"
echo ""
if [[ "${PLATFORM_ENV}" == "local" ]]; then
    echo "Local access:"
    echo "  HTTP:  http://localhost:8080"
    echo "  HTTPS: https://localhost:8443"
else
    echo "GCP access:"
    echo "  kubectl get svc -n apps"
fi
echo ""
