#!/bin/bash
set -euo pipefail

#===============================================================================
# Generate ArgoCD State from apps.yaml (v2)
#
# Reads apps.yaml and generates K8s manifests + ArgoCD Application resources
# into argocd-state/. This is the ONLY way to deploy to local/gcp environments.
#
# Supports apps.yaml v2 sections:
#   - helm:       Third-party Helm charts (Valkey, etc.)
#   - apps:       Traditional container apps (k3sapp CLI)
#   - serverless: Scale-to-zero functions (k3sfn CLI)
#   - compose:    Docker Compose projects (k3scompose CLI)
#
# Usage:
#   ./scripts/generate-argocd-state.sh [environment]
#   ./scripts/generate-argocd-state.sh local
#   ./scripts/generate-argocd-state.sh gcp
#
# After running, commit and push argocd-state/ to trigger ArgoCD sync.
#===============================================================================

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPS_FILE="${PROJECT_ROOT}/apps.yaml"
OUTPUT_DIR="${PROJECT_ROOT}/argocd-state"

# Environment (local or gcp)
ENVIRONMENT="${1:-local}"

# Git repository URL - auto-detect or use default
GITHUB_REPO="${GITHUB_REPO:-$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null || echo "https://github.com/GeeekyBoy/k3s-platform.git")}"

# Load environment-specific configuration
ENV_FILE="${PROJECT_ROOT}/configs/.env.${ENVIRONMENT}"
if [[ -f "${ENV_FILE}" ]]; then
    source "${ENV_FILE}"
elif [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
fi

# Load per-app image tags from build-images.sh output (if available)
IMAGE_TAGS_FILE="${PROJECT_ROOT}/.image-tags.env"
if [[ -f "${IMAGE_TAGS_FILE}" ]]; then
    source "${IMAGE_TAGS_FILE}"
    log_info "Loaded per-app image tags from ${IMAGE_TAGS_FILE}"
else
    log_warn "No .image-tags.env found, will use 'latest' for all images"
    log_info "Run ./scripts/build-images.sh first to generate content-based tags"
fi

# Helper function to get image tag for a specific app
# Usage: get_image_tag "fastapi" -> returns content hash or "latest"
get_image_tag() {
    local app_name="$1"
    # Convert app name to uppercase and replace hyphens with underscores
    local var_name="IMAGE_TAG_$(echo "${app_name}" | tr '[:lower:]-' '[:upper:]_')"
    local tag="${!var_name:-latest}"
    echo "${tag}"
}

# Set registry and ingress based on environment
case "${ENVIRONMENT}" in
    local)
        REGISTRY="${REGISTRY_NAME:-registry.localhost:5111}"
        INGRESS_TYPE="traefik"
        ;;
    gcp)
        if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
            log_error "GCP_PROJECT_ID is required for gcp environment"
            echo "  Set it via: export GCP_PROJECT_ID=your-project-id"
            echo "  Or create: configs/.env.gcp with GCP_PROJECT_ID=your-project-id"
            exit 1
        fi
        REGISTRY="${GCP_REGION:-us-central1}-docker.pkg.dev/${GCP_PROJECT_ID}/${REGISTRY_NAME:-k3s-platform}"
        INGRESS_TYPE="haproxy"
        ;;
    *)
        echo "Usage: $0 [local|gcp]"
        echo "  local: Generate state for local k3d cluster"
        echo "  gcp:   Generate state for GCP cloud cluster"
        exit 1
        ;;
esac

log_info "Generating ArgoCD state for environment: ${ENVIRONMENT}"
log_info "Source: ${APPS_FILE}"
log_info "Output: ${OUTPUT_DIR}/${ENVIRONMENT}/"
log_info "Registry: ${REGISTRY}"
log_info "Ingress: ${INGRESS_TYPE}"
log_info "Git repo: ${GITHUB_REPO}"

# Check dependencies
if ! command -v yq &>/dev/null; then
    log_error "yq is required. Install with: brew install yq"
    exit 1
fi

if ! command -v uv &>/dev/null; then
    log_error "uv is required. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create output directory and clean previous state
mkdir -p "${OUTPUT_DIR}/${ENVIRONMENT}"
rm -rf "${OUTPUT_DIR}/${ENVIRONMENT:?}"/*

#===============================================================================
# Generate ArgoCD Project
#===============================================================================
cat > "${OUTPUT_DIR}/${ENVIRONMENT}/project.yaml" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: k3s-platform
  namespace: argocd
spec:
  description: K3s Platform Applications
  sourceRepos:
    - '*'
  destinations:
    - namespace: '*'
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: '*'
      kind: '*'
  namespaceResourceWhitelist:
    - group: '*'
      kind: '*'
EOF

log_info "Generated: project.yaml"

#===============================================================================
# Generate Helm Applications
#===============================================================================
helm_count=$(yq eval '.helm | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<helm_count; i++)); do
    enabled=$(yq eval ".helm[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".helm[${i}].name" "${APPS_FILE}")
    chart=$(yq eval ".helm[${i}].chart" "${APPS_FILE}")
    version=$(yq eval ".helm[${i}].version // \"*\"" "${APPS_FILE}")
    namespace=$(yq eval ".helm[${i}].namespace // \"apps\"" "${APPS_FILE}")
    values_file=$(yq eval ".helm[${i}].values // \"\"" "${APPS_FILE}")

    repo_name=$(echo "${chart}" | cut -d'/' -f1)
    chart_name=$(echo "${chart}" | cut -d'/' -f2)
    repo_url=$(yq eval ".repositories.${repo_name} // \"\"" "${APPS_FILE}")

    if [[ -z "${repo_url}" ]]; then
        log_warn "Repository ${repo_name} not found in apps.yaml, skipping ${name}"
        continue
    fi

    # Handle OCI vs traditional Helm repos
    if [[ "${repo_url}" == oci://* ]]; then
        oci_repo_url="${repo_url#oci://}"
        cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: helm
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  source:
    repoURL: ${oci_repo_url}
    chart: ${chart_name}
    targetRevision: "${version}"
EOF
    else
        cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: helm
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  source:
    repoURL: ${repo_url}
    chart: ${chart_name}
    targetRevision: "${version}"
EOF
    fi

    # Append helm values
    cat >> "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOF
    helm:
      releaseName: ${name}
      valueFiles: []
      values: |
$(if [[ -n "${values_file}" && -f "${PROJECT_ROOT}/${values_file}" ]]; then
    sed 's/^/        /' "${PROJECT_ROOT}/${values_file}"
else
    echo "        # No values file"
fi)
  destination:
    server: https://kubernetes.default.svc
    namespace: ${namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
      - ServerSideApply=true
EOF

    log_info "Generated: ${name}.yaml (Helm)"
done

#===============================================================================
# Generate Traditional Apps (k3sapp CLI)
#===============================================================================
apps_count=$(yq eval '.apps | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<apps_count; i++)); do
    enabled=$(yq eval ".apps[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".apps[${i}].name" "${APPS_FILE}")
    namespace=$(yq eval ".apps[${i}].namespace // \"apps\"" "${APPS_FILE}")
    app_path=$(yq eval ".apps[${i}].path // \"apps/${name}\"" "${APPS_FILE}")

    log_info "Generating app manifests for ${name}..."

    APP_MANIFEST_DIR="${OUTPUT_DIR}/${ENVIRONMENT}/apps/${name}"
    mkdir -p "${APP_MANIFEST_DIR}"

    # Generate manifests using k3sapp CLI
    if ! uv run --project "${PROJECT_ROOT}/libs/k3sapp" k3sapp generate "${name}" \
        --env "${ENVIRONMENT}" \
        --output "${APP_MANIFEST_DIR}" 2>&1; then
        log_warn "Failed to generate manifests for ${name}, skipping"
        rm -rf "${APP_MANIFEST_DIR}"
        continue
    fi

    # Check for generated file and rename to manifests.yaml
    if [[ -f "${APP_MANIFEST_DIR}/${name}.yaml" ]]; then
        mv "${APP_MANIFEST_DIR}/${name}.yaml" "${APP_MANIFEST_DIR}/manifests.yaml"
    elif [[ ! -f "${APP_MANIFEST_DIR}/manifests.yaml" ]]; then
        log_warn "No manifests generated for ${name}"
        rm -rf "${APP_MANIFEST_DIR}"
        continue
    fi

    # Create ArgoCD Application
    cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}-app.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: app
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
  source:
    repoURL: ${GITHUB_REPO}
    targetRevision: HEAD
    path: argocd-state/${ENVIRONMENT}/apps/${name}
    directory:
      recurse: false
      include: 'manifests.yaml'
  destination:
    server: https://kubernetes.default.svc
    namespace: ${namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
EOF

    log_info "Generated: ${name}-app.yaml + apps/${name}/manifests.yaml"
done

#===============================================================================
# Generate Serverless Applications (k3sfn CLI)
#===============================================================================
serverless_count=$(yq eval '.serverless | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<serverless_count; i++)); do
    enabled=$(yq eval ".serverless[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
    namespace=$(yq eval ".serverless[${i}].namespace // \"apps\"" "${APPS_FILE}")
    app_path=$(yq eval ".serverless[${i}].path // \"apps/${name}\"" "${APPS_FILE}")

    log_info "Generating serverless manifests for ${name}..."

    SERVERLESS_MANIFEST_DIR="${OUTPUT_DIR}/${ENVIRONMENT}/serverless/${name}"
    mkdir -p "${SERVERLESS_MANIFEST_DIR}"

    # Generate manifests using k3sfn CLI with apps.yaml integration
    if ! uv run --project "${PROJECT_ROOT}/libs/k3sfn" k3sfn generate \
        --name "${name}" \
        --from-apps-yaml \
        --env "${ENVIRONMENT}" \
        --ingress "${INGRESS_TYPE}" \
        --output "${SERVERLESS_MANIFEST_DIR}" 2>&1; then
        log_warn "Failed to generate manifests for ${name}, skipping"
        rm -rf "${SERVERLESS_MANIFEST_DIR}"
        continue
    fi

    if [[ ! -f "${SERVERLESS_MANIFEST_DIR}/manifests.yaml" ]]; then
        log_warn "No manifests.yaml generated for ${name}"
        rm -rf "${SERVERLESS_MANIFEST_DIR}"
        continue
    fi

    # Remove files not needed in argocd-state (Dockerfile is for CI/CD)
    rm -f "${SERVERLESS_MANIFEST_DIR}/Dockerfile" "${SERVERLESS_MANIFEST_DIR}/k3sfn.json"

    # Create ArgoCD Application
    cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}-serverless.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: serverless
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
  source:
    repoURL: ${GITHUB_REPO}
    targetRevision: HEAD
    path: argocd-state/${ENVIRONMENT}/serverless/${name}
    directory:
      recurse: false
      include: 'manifests.yaml'
  destination:
    server: https://kubernetes.default.svc
    namespace: ${namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
EOF

    log_info "Generated: ${name}-serverless.yaml + serverless/${name}/manifests.yaml"
done

#===============================================================================
# Generate Docker Compose Projects (k3scompose CLI)
#===============================================================================
compose_count=$(yq eval '.compose | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<compose_count; i++)); do
    enabled=$(yq eval ".compose[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".compose[${i}].name" "${APPS_FILE}")
    namespace=$(yq eval ".compose[${i}].namespace // \"apps\"" "${APPS_FILE}")
    compose_path=$(yq eval ".compose[${i}].path // \"apps/${name}\"" "${APPS_FILE}")

    log_info "Generating compose manifests for ${name}..."

    COMPOSE_MANIFEST_DIR="${OUTPUT_DIR}/${ENVIRONMENT}/compose/${name}"
    mkdir -p "${COMPOSE_MANIFEST_DIR}"

    # Generate manifests using k3scompose CLI
    if ! uv run --project "${PROJECT_ROOT}/libs/k3scompose" k3scompose generate "${name}" \
        --env "${ENVIRONMENT}" \
        --output "${COMPOSE_MANIFEST_DIR}" 2>&1; then
        log_warn "Failed to generate manifests for ${name}, skipping"
        rm -rf "${COMPOSE_MANIFEST_DIR}"
        continue
    fi

    # Check for generated manifests
    if [[ -f "${COMPOSE_MANIFEST_DIR}/${name}.yaml" ]]; then
        mv "${COMPOSE_MANIFEST_DIR}/${name}.yaml" "${COMPOSE_MANIFEST_DIR}/manifests.yaml"
    elif [[ ! -f "${COMPOSE_MANIFEST_DIR}/manifests.yaml" ]]; then
        log_warn "No manifests generated for ${name}"
        rm -rf "${COMPOSE_MANIFEST_DIR}"
        continue
    fi

    # Create ArgoCD Application
    cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}-compose.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: compose
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
  source:
    repoURL: ${GITHUB_REPO}
    targetRevision: HEAD
    path: argocd-state/${ENVIRONMENT}/compose/${name}
    directory:
      recurse: false
      include: 'manifests.yaml'
  destination:
    server: https://kubernetes.default.svc
    namespace: ${namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
EOF

    log_info "Generated: ${name}-compose.yaml + compose/${name}/manifests.yaml"
done

#===============================================================================
# Generate kustomization.yaml for the environment
#===============================================================================
cat > "${OUTPUT_DIR}/${ENVIRONMENT}/kustomization.yaml" <<EOF
# Auto-generated - DO NOT EDIT. Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - project.yaml
$(for f in "${OUTPUT_DIR}/${ENVIRONMENT}"/*.yaml; do
    fname=$(basename "$f")
    if [[ "$fname" != "kustomization.yaml" && "$fname" != "project.yaml" ]]; then
        echo "  - ${fname}"
    fi
done)

labels:
  - pairs:
      app.kubernetes.io/managed-by: argocd-state-generator
      environment: ${ENVIRONMENT}
    includeSelectors: false
EOF

log_info "Generated: kustomization.yaml"

#===============================================================================
# Post-process: Substitute environment variables in manifests
#===============================================================================
log_info "Post-processing manifests to substitute environment variables..."

# For GCP environment, substitute ${PROJECT_ID} with actual project ID
if [[ "${ENVIRONMENT}" == "gcp" ]]; then
    # Substitute in all YAML files under the environment directory
    find "${OUTPUT_DIR}/${ENVIRONMENT}" -type f -name "*.yaml" | while read -r manifest_file; do
        if grep -q '\${PROJECT_ID}' "${manifest_file}" 2>/dev/null; then
            log_info "  Substituting \${PROJECT_ID} in: $(basename "${manifest_file}")"
            # Use sed to replace ${PROJECT_ID} with actual GCP_PROJECT_ID
            if [[ "$(uname)" == "Darwin" ]]; then
                # macOS sed requires empty string for -i
                sed -i '' "s|\${PROJECT_ID}|${GCP_PROJECT_ID}|g" "${manifest_file}"
            else
                # Linux sed
                sed -i "s|\${PROJECT_ID}|${GCP_PROJECT_ID}|g" "${manifest_file}"
            fi
        fi
        # Also substitute ${GCP_PROJECT_ID} if present
        if grep -q '\${GCP_PROJECT_ID}' "${manifest_file}" 2>/dev/null; then
            log_info "  Substituting \${GCP_PROJECT_ID} in: $(basename "${manifest_file}")"
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "s|\${GCP_PROJECT_ID}|${GCP_PROJECT_ID}|g" "${manifest_file}"
            else
                sed -i "s|\${GCP_PROJECT_ID}|${GCP_PROJECT_ID}|g" "${manifest_file}"
            fi
        fi
        # Substitute ${GCP_REGION} if present
        if grep -q '\${GCP_REGION}' "${manifest_file}" 2>/dev/null; then
            log_info "  Substituting \${GCP_REGION} in: $(basename "${manifest_file}")"
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "s|\${GCP_REGION}|${GCP_REGION}|g" "${manifest_file}"
            else
                sed -i "s|\${GCP_REGION}|${GCP_REGION}|g" "${manifest_file}"
            fi
        fi
    done
    log_success "Variable substitution complete"
fi

# Substitute image tags per-app (content hash based)
# For each app, replace <registry>/<app-name>:latest with <registry>/<app-name>:<content-hash>
log_info "Substituting per-app image tags..."

# Process traditional apps
apps_count=$(yq eval '.apps | length' "${APPS_FILE}" 2>/dev/null || echo "0")
for ((i=0; i<apps_count; i++)); do
    enabled=$(yq eval ".apps[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".apps[${i}].name" "${APPS_FILE}")
    tag=$(get_image_tag "${name}")

    if [[ "${tag}" != "latest" ]]; then
        log_info "  ${name}: :latest -> :${tag}"
        # Find and substitute in app manifests
        manifest_path="${OUTPUT_DIR}/${ENVIRONMENT}/apps/${name}/manifests.yaml"
        if [[ -f "${manifest_path}" ]]; then
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "s|/${name}:latest|/${name}:${tag}|g" "${manifest_path}"
            else
                sed -i "s|/${name}:latest|/${name}:${tag}|g" "${manifest_path}"
            fi
        fi
    fi
done

# Process serverless apps
serverless_count=$(yq eval '.serverless | length' "${APPS_FILE}" 2>/dev/null || echo "0")
for ((i=0; i<serverless_count; i++)); do
    enabled=$(yq eval ".serverless[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
    tag=$(get_image_tag "${name}")

    if [[ "${tag}" != "latest" ]]; then
        log_info "  ${name}: :latest -> :${tag}"
        # Find and substitute in serverless manifests
        manifest_path="${OUTPUT_DIR}/${ENVIRONMENT}/serverless/${name}/manifests.yaml"
        if [[ -f "${manifest_path}" ]]; then
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "s|/${name}:latest|/${name}:${tag}|g" "${manifest_path}"
            else
                sed -i "s|/${name}:latest|/${name}:${tag}|g" "${manifest_path}"
            fi
        fi
    fi
done

log_success "Per-app image tag substitution complete"

#===============================================================================
# Summary
#===============================================================================
echo ""
echo "================================================================================"
log_success "ArgoCD state generated successfully!"
echo "================================================================================"
echo ""
echo "Generated structure:"
find "${OUTPUT_DIR}/${ENVIRONMENT}" -type f -name "*.yaml" | sort | while read -r f; do
    echo "  ${f#${PROJECT_ROOT}/}"
done
echo ""
echo "Next steps:"
if [[ "${ENVIRONMENT}" == "gcp" ]]; then
    echo "  1. Build and push images: ./scripts/build-images.sh"
    echo "  2. Review the generated files in argocd-state/${ENVIRONMENT}/"
    echo "  3. Commit and push:"
else
    echo "  1. Review the generated files in argocd-state/${ENVIRONMENT}/"
    echo "  2. Commit and push:"
fi
echo "     git add argocd-state/"
echo "     git commit -m 'Update ArgoCD state for ${ENVIRONMENT}'"
echo "     git push"
echo "  3. ArgoCD will auto-sync the changes"
echo ""
