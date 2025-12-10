#!/bin/bash
set -euo pipefail

#===============================================================================
# Generate ArgoCD State from apps.yaml
#
# Reads apps.yaml and generates ArgoCD Application manifests into argocd-state/
# This is the ONLY way to create ArgoCD applications - no manual editing!
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
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPS_FILE="${PROJECT_ROOT}/apps.yaml"
OUTPUT_DIR="${PROJECT_ROOT}/argocd-state"

# Environment (local or gcp)
ENVIRONMENT="${1:-local}"

# Git repository URL - auto-detect or use default
GITHUB_REPO="${GITHUB_REPO:-$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null || echo "https://github.com/GeeekyBoy/k3s-platform.git")}"

# Load environment configuration for registry settings
if [[ -f "${PROJECT_ROOT}/configs/.env" ]]; then
    source "${PROJECT_ROOT}/configs/.env"
fi

# Set registry based on environment
case "${ENVIRONMENT}" in
    local)
        REGISTRY="${REGISTRY_NAME:-registry.localhost:5111}"
        ;;
    gcp)
        REGISTRY="${GCP_REGION:-us-central1}-docker.pkg.dev/${GCP_PROJECT_ID:-}/${REGISTRY_NAME:-k3s-platform}"
        ;;
esac

# Validate environment
if [[ "${ENVIRONMENT}" != "local" && "${ENVIRONMENT}" != "gcp" ]]; then
    echo "Usage: $0 [local|gcp]"
    echo "  local: Generate state for local k3d cluster"
    echo "  gcp:   Generate state for GCP cloud cluster"
    exit 1
fi

log_info "Generating ArgoCD state for environment: ${ENVIRONMENT}"
log_info "Source: ${APPS_FILE}"
log_info "Output: ${OUTPUT_DIR}/${ENVIRONMENT}/"
log_info "Git repo: ${GITHUB_REPO}"

# Check yq is available
if ! command -v yq &>/dev/null; then
    echo "[ERROR] yq is required. Install with: brew install yq"
    exit 1
fi

# Create output directory
mkdir -p "${OUTPUT_DIR}/${ENVIRONMENT}"

# Clean previous state for this environment
rm -f "${OUTPUT_DIR}/${ENVIRONMENT}"/*.yaml

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
    enabled=$(yq eval ".helm[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

    if [[ "${enabled}" == "true" ]]; then
        name=$(yq eval ".helm[${i}].name" "${APPS_FILE}")
        chart=$(yq eval ".helm[${i}].chart" "${APPS_FILE}")
        version=$(yq eval ".helm[${i}].version // \"*\"" "${APPS_FILE}")
        namespace=$(yq eval ".helm[${i}].namespace" "${APPS_FILE}")
        values_file=$(yq eval ".helm[${i}].values" "${APPS_FILE}")

        # Extract repo and chart name from chart (e.g., bitnami/valkey -> bitnami, valkey)
        repo_name=$(echo "${chart}" | cut -d'/' -f1)
        chart_name=$(echo "${chart}" | cut -d'/' -f2)

        # Get repo URL from repositories section
        repo_url=$(yq eval ".repositories.${repo_name}" "${APPS_FILE}" 2>/dev/null || echo "")

        if [[ -z "${repo_url}" ]]; then
            log_warn "Repository ${repo_name} not found in apps.yaml, skipping ${name}"
            continue
        fi

        # Generate Application manifest
        # For OCI registries, ArgoCD requires repoURL (without oci:// prefix) + chart (name)
        if [[ "${repo_url}" == oci://* ]]; then
            # Strip oci:// prefix for ArgoCD - it auto-detects OCI format
            oci_repo_url="${repo_url#oci://}"
            cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOFOCI
# Auto-generated from apps.yaml - DO NOT EDIT MANUALLY
# Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
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
EOFOCI
        else
            # Traditional Helm repo format
            cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOFHELM
# Auto-generated from apps.yaml - DO NOT EDIT MANUALLY
# Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
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
EOFHELM
        fi

        # Append helm values to the manifest
        cat >> "${OUTPUT_DIR}/${ENVIRONMENT}/${name}.yaml" <<EOF
    helm:
      releaseName: ${name}
      valueFiles: []
      values: |
$(if [[ -f "${PROJECT_ROOT}/${values_file}" ]]; then
    # Indent values file content
    sed 's/^/        /' "${PROJECT_ROOT}/${values_file}"
else
    echo "        # Values file not found: ${values_file}"
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
    fi
done

#===============================================================================
# Generate Kustomize Applications
#===============================================================================
kustomize_count=$(yq eval '.kustomize | length' "${APPS_FILE}" 2>/dev/null || echo "0")

# Build image list from apps.yaml (apps section)
# These will be substituted by ArgoCD's kustomize image transformer
generate_images_section() {
    local images=""
    local apps_count
    apps_count=$(yq eval '.apps | length' "${APPS_FILE}" 2>/dev/null || echo "0")

    for ((j=0; j<apps_count; j++)); do
        local app_enabled
        app_enabled=$(yq eval ".apps[${j}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

        if [[ "${app_enabled}" == "true" ]]; then
            local app_name
            app_name=$(yq eval ".apps[${j}].name" "${APPS_FILE}")
            # Map base image name to registry image
            # Base uses: <app_name>-app:latest, registry uses: <registry>/<app_name>:latest
            images="${images}
      - ${app_name}-app=${REGISTRY}/${app_name}:latest"
        fi
    done

    echo "${images}"
}

for ((i=0; i<kustomize_count; i++)); do
    enabled=$(yq eval ".kustomize[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

    if [[ "${enabled}" == "true" ]]; then
        name=$(yq eval ".kustomize[${i}].name" "${APPS_FILE}")
        path_template=$(yq eval ".kustomize[${i}].path" "${APPS_FILE}")

        # Substitute environment in path
        path="${path_template//\$\{PLATFORM_ENV\}/${ENVIRONMENT}}"

        # Generate image mappings
        IMAGES_SECTION=$(generate_images_section)

        cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}-kustomize.yaml" <<EOF
# Auto-generated from apps.yaml - DO NOT EDIT MANUALLY
# Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${name}
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: k3s-platform
    environment: ${ENVIRONMENT}
    type: kustomize
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: k3s-platform
  # Ignore replicas field - KEDA/HPA manages scaling
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
  source:
    repoURL: ${GITHUB_REPO}
    targetRevision: HEAD
    path: ${path}
    kustomize:
      # Image substitutions generated from apps.yaml and configs/.env
      # Base images are mapped to environment-specific registry
      images:${IMAGES_SECTION}
  destination:
    server: https://kubernetes.default.svc
    namespace: apps
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

        log_info "Generated: ${name}-kustomize.yaml (Kustomize)"
    fi
done

#===============================================================================
# Generate Serverless Applications
#===============================================================================
serverless_count=$(yq eval '.serverless | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<serverless_count; i++)); do
    enabled=$(yq eval ".serverless[${i}].enabled" "${APPS_FILE}" 2>/dev/null || echo "true")

    if [[ "${enabled}" == "true" ]]; then
        name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
        path=$(yq eval ".serverless[${i}].path" "${APPS_FILE}")
        namespace=$(yq eval ".serverless[${i}].namespace" "${APPS_FILE}")

        log_info "Generating serverless manifests for ${name}..."

        # Create output directory for this serverless app's manifests
        SERVERLESS_MANIFEST_DIR="${OUTPUT_DIR}/${ENVIRONMENT}/serverless/${name}"
        mkdir -p "${SERVERLESS_MANIFEST_DIR}"

        # Generate manifests using k3sfn CLI locally on deployer machine
        if ! uv run python -m k3sfn.cli generate "${PROJECT_ROOT}/${path}" \
            --name "${name}" \
            --output "${SERVERLESS_MANIFEST_DIR}" \
            --namespace "${namespace}" \
            --registry "${REGISTRY}" 2>/dev/null; then
            log_warn "Failed to generate manifests for ${name}, skipping"
            rm -rf "${SERVERLESS_MANIFEST_DIR}"
            continue
        fi

        # Verify manifests were generated
        if [[ ! -f "${SERVERLESS_MANIFEST_DIR}/manifests.yaml" ]]; then
            log_warn "No manifests.yaml generated for ${name}"
            rm -rf "${SERVERLESS_MANIFEST_DIR}"
            continue
        fi

        # Remove files we don't need in argocd-state (Dockerfile is for CI/CD)
        rm -f "${SERVERLESS_MANIFEST_DIR}/Dockerfile" "${SERVERLESS_MANIFEST_DIR}/k3sfn.json"

        # Create ArgoCD Application that points to the generated manifests in this repo
        cat > "${OUTPUT_DIR}/${ENVIRONMENT}/${name}-serverless.yaml" <<EOF
# Auto-generated from apps.yaml - DO NOT EDIT MANUALLY
# Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
#
# NOTE: You must build and push the image before ArgoCD can deploy this:
#   docker build -t ${REGISTRY}/${name}:latest ${path}
#   docker push ${REGISTRY}/${name}:latest
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
  # Ignore replicas field - KEDA manages scaling for serverless functions
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

        log_info "Generated: ${name}-serverless.yaml (Application)"
        log_info "Generated: serverless/${name}/manifests.yaml (raw manifests)"
    fi
done

#===============================================================================
# Generate kustomization.yaml for the environment
#===============================================================================
cat > "${OUTPUT_DIR}/${ENVIRONMENT}/kustomization.yaml" <<EOF
# Auto-generated - DO NOT EDIT MANUALLY
# Regenerate with: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}
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
# Summary
#===============================================================================
echo ""
echo "================================================================================"
log_success "ArgoCD state generated successfully!"
echo "================================================================================"
echo ""
echo "Generated files:"
ls -la "${OUTPUT_DIR}/${ENVIRONMENT}/"
echo ""
echo "Next steps:"
echo "  1. Review the generated files in argocd-state/${ENVIRONMENT}/"
echo "  2. Commit and push:"
echo "     git add argocd-state/"
echo "     git commit -m 'Update ArgoCD state for ${ENVIRONMENT}'"
echo "     git push"
echo "  3. ArgoCD will auto-sync the changes"
echo ""
