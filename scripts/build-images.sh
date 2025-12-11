#!/usr/bin/env bash
# Requires Bash 4+ for associative arrays
set -euo pipefail

# Check bash version for associative array support
if [[ "${BASH_VERSION%%.*}" -lt 4 ]]; then
    echo "Error: This script requires Bash 4 or later (for associative arrays)"
    echo "Current version: ${BASH_VERSION}"
    exit 1
fi

#===============================================================================
# Build and Push Container Images
#
# Reads apps.yaml and builds all enabled apps/serverless functions.
# Images are tagged with CONTENT HASH for proper deduplication and rollback.
#
# KEY FEATURES:
#   - Content-based hashing: Each app gets unique tag based on its files
#   - Only rebuilds when content actually changes
#   - Skips already-built images (checks registry by content hash)
#   - Supports both local (Docker) and GCP (Cloud Build) environments
#   - Writes per-app image tags for generate-argocd-state.sh to consume
#
# HOW IT WORKS:
#   1. For each app, compute SHA256 hash of: Dockerfile + source files + deps
#   2. Use first 12 chars of hash as image tag (e.g., fastapi:a1b2c3d4e5f6)
#   3. Check if image with that tag exists in registry
#   4. Skip build if exists, build if not
#   5. Write .image-tags.env with per-app tags
#
# Usage:
#   ./scripts/build-images.sh                     # Build all with content hash
#   ./scripts/build-images.sh --env local         # Force local Docker build
#   ./scripts/build-images.sh --env gcp           # Force GCP Cloud Build
#   ./scripts/build-images.sh --force             # Rebuild even if image exists
#   ./scripts/build-images.sh --app fastapi       # Build specific app only
#   ./scripts/build-images.sh --dry-run           # Show what would be built
#
# Output:
#   Creates .image-tags.env with per-app IMAGE_TAG_<APP> variables
#===============================================================================

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }
log_skip() { echo -e "${YELLOW}[SKIP]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPS_FILE="${PROJECT_ROOT}/apps.yaml"
IMAGE_TAGS_FILE="${PROJECT_ROOT}/.image-tags.env"

# Parse arguments
DRY_RUN=false
FORCE_BUILD=false
SPECIFIC_APP=""
SPECIFIC_SERVERLESS=""
ENVIRONMENT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE_BUILD=true
            shift
            ;;
        --app)
            SPECIFIC_APP="$2"
            shift 2
            ;;
        --serverless)
            SPECIFIC_SERVERLESS="$2"
            shift 2
            ;;
        --env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --env ENV              Environment: local or gcp (auto-detect if not specified)"
            echo "  --force                Force rebuild even if image exists in registry"
            echo "  --app NAME             Build only the specified app"
            echo "  --serverless NAME      Build only the specified serverless app"
            echo "  --dry-run              Show what would be built without building"
            echo "  -h, --help             Show this help"
            echo ""
            echo "Image tags are computed from content hash (first 12 chars of SHA256)"
            echo "This ensures images are only rebuilt when their content changes."
            echo ""
            echo "Examples:"
            echo "  $0                           # Build all apps with content hash tags"
            echo "  $0 --env gcp --force         # Force rebuild all for GCP"
            echo "  $0 --app fastapi             # Build only fastapi"
            echo "  $0 --dry-run                 # Show hashes without building"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Auto-detect environment if not specified
if [[ -z "${ENVIRONMENT}" ]]; then
    if [[ -f "${PROJECT_ROOT}/configs/.env.gcp" ]]; then
        # Check if we have GCP credentials available
        if gcloud auth print-access-token &>/dev/null 2>&1; then
            ENVIRONMENT="gcp"
        else
            ENVIRONMENT="local"
        fi
    else
        ENVIRONMENT="local"
    fi
fi

# Load environment-specific configuration
case "${ENVIRONMENT}" in
    local|dev)
        if [[ -f "${PROJECT_ROOT}/configs/.env.local" ]]; then
            source "${PROJECT_ROOT}/configs/.env.local"
        fi
        REGISTRY="${REGISTRY_NAME:-registry.localhost:5111}"
        BUILD_METHOD="docker"
        ;;
    gcp)
        if [[ -f "${PROJECT_ROOT}/configs/.env.gcp" ]]; then
            source "${PROJECT_ROOT}/configs/.env.gcp"
        fi
        if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
            log_error "GCP_PROJECT_ID is required for GCP environment"
            echo "  Set it in configs/.env.gcp or via environment variable"
            exit 1
        fi
        GCP_REGION="${GCP_REGION:-us-central1}"
        REGISTRY_NAME="${REGISTRY_NAME:-k3s-platform}"
        REGISTRY="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REGISTRY_NAME}"
        BUILD_METHOD="cloudbuild"
        ;;
    *)
        log_error "Unknown environment: ${ENVIRONMENT}"
        echo "  Supported: local, dev, gcp"
        exit 1
        ;;
esac

log_step "Build Images (Content Hash Mode)"
log_info "Environment: ${ENVIRONMENT}"
log_info "Registry: ${REGISTRY}"
log_info "Build method: ${BUILD_METHOD}"
log_info "Force rebuild: ${FORCE_BUILD}"

# Check dependencies
if ! command -v yq &>/dev/null; then
    log_error "yq is required. Install with: brew install yq"
    exit 1
fi

if [[ ! -f "${APPS_FILE}" ]]; then
    log_error "apps.yaml not found at: ${APPS_FILE}"
    exit 1
fi

# Environment-specific checks
if [[ "${BUILD_METHOD}" == "cloudbuild" ]]; then
    if ! command -v gcloud &>/dev/null; then
        log_error "gcloud CLI is required for GCP builds"
        exit 1
    fi
    if ! gcloud auth print-access-token &>/dev/null; then
        log_error "Not authenticated with gcloud. Run: gcloud auth login"
        exit 1
    fi
elif [[ "${BUILD_METHOD}" == "docker" ]]; then
    if ! command -v docker &>/dev/null; then
        log_error "docker is required for local builds"
        exit 1
    fi
    if ! docker info &>/dev/null; then
        log_error "Docker daemon is not running"
        exit 1
    fi
fi

#===============================================================================
# Content Hash Functions
#===============================================================================

# Compute content hash for a traditional app (Dockerfile + source)
compute_app_hash() {
    local app_path="$1"
    local dockerfile="$2"
    local app_dir="${PROJECT_ROOT}/${app_path}"

    # Hash all relevant files:
    # - Dockerfile
    # - All source files (excluding .git, __pycache__, node_modules, etc.)
    # - Requirements/dependency files
    (
        # Hash Dockerfile
        if [[ -f "${app_dir}/${dockerfile}" ]]; then
            cat "${app_dir}/${dockerfile}"
        fi

        # Hash all source files (sorted for consistency)
        find "${app_dir}" -type f \
            ! -path "*/.git/*" \
            ! -path "*/__pycache__/*" \
            ! -path "*/node_modules/*" \
            ! -path "*/.venv/*" \
            ! -path "*/venv/*" \
            ! -path "*/.mypy_cache/*" \
            ! -path "*/.pytest_cache/*" \
            ! -path "*.pyc" \
            ! -path "*.generated" \
            ! -name ".DS_Store" \
            -print0 2>/dev/null | sort -z | xargs -0 cat 2>/dev/null
    ) | shasum -a 256 | cut -c1-12
}

# Compute content hash for a serverless app (functions/ + shared libs)
compute_serverless_hash() {
    local app_path="$1"
    local app_dir="${PROJECT_ROOT}/${app_path}"

    (
        # Hash functions directory
        if [[ -d "${app_dir}/functions" ]]; then
            find "${app_dir}/functions" -type f \
                ! -path "*/__pycache__/*" \
                ! -name "*.pyc" \
                -print0 2>/dev/null | sort -z | xargs -0 cat 2>/dev/null
        fi

        # Hash shared libs if present
        if [[ -d "${app_dir}/libs" ]]; then
            find "${app_dir}/libs" -type f \
                ! -path "*/__pycache__/*" \
                ! -name "*.pyc" \
                -print0 2>/dev/null | sort -z | xargs -0 cat 2>/dev/null
        fi

        # Hash requirements if present
        if [[ -f "${app_dir}/requirements.txt" ]]; then
            cat "${app_dir}/requirements.txt"
        fi

        # Hash pyproject.toml if present
        if [[ -f "${app_dir}/pyproject.toml" ]]; then
            cat "${app_dir}/pyproject.toml"
        fi

        # Hash k3sfn runtime (affects generated Dockerfile)
        if [[ -d "${PROJECT_ROOT}/libs/k3sfn" ]]; then
            find "${PROJECT_ROOT}/libs/k3sfn" -name "*.py" -type f \
                ! -path "*/__pycache__/*" \
                -print0 2>/dev/null | sort -z | xargs -0 cat 2>/dev/null
        fi
    ) | shasum -a 256 | cut -c1-12
}

#===============================================================================
# Image Existence Check Functions
#===============================================================================

# Check if image exists in GCP Artifact Registry
image_exists_gcp() {
    local image_name="$1"
    local tag="$2"
    local full_image="${REGISTRY}/${image_name}:${tag}"

    # Use gcloud to check if the image exists
    if gcloud artifacts docker images describe "${full_image}" &>/dev/null 2>&1; then
        return 0  # exists
    else
        return 1  # does not exist
    fi
}

# Check if image exists in local Docker registry (k3d)
image_exists_local() {
    local image_name="$1"
    local tag="$2"
    local full_image="${REGISTRY}/${image_name}:${tag}"

    # Try to pull the manifest to check if it exists
    if docker manifest inspect "${full_image}" &>/dev/null 2>&1; then
        return 0  # exists
    else
        return 1  # does not exist
    fi
}

# Check if image exists (dispatch to appropriate method)
image_exists() {
    local image_name="$1"
    local tag="$2"

    if [[ "${BUILD_METHOD}" == "cloudbuild" ]]; then
        image_exists_gcp "${image_name}" "${tag}"
    else
        image_exists_local "${image_name}" "${tag}"
    fi
}

#===============================================================================
# Build Functions
#===============================================================================

build_with_docker() {
    local image_name="$1"
    local dockerfile_path="$2"
    local context_path="$3"
    local tag="$4"
    local full_image="${REGISTRY}/${image_name}:${tag}"

    log_info "  Building with Docker: ${full_image}"

    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "  [DRY RUN] docker build -t ${full_image} -f ${dockerfile_path} ${context_path}"
        return 0
    fi

    if docker build -t "${full_image}" -f "${dockerfile_path}" "${context_path}"; then
        log_info "  Pushing to registry..."
        if docker push "${full_image}"; then
            log_success "  Built and pushed: ${full_image}"
            return 0
        else
            log_error "  Failed to push: ${full_image}"
            return 1
        fi
    else
        log_error "  Failed to build: ${image_name}"
        return 1
    fi
}

build_with_cloudbuild() {
    local image_name="$1"
    local dockerfile_rel_path="$2"  # Relative to project root
    local tag="$3"
    local full_image="${REGISTRY}/${image_name}:${tag}"

    log_info "  Building with Cloud Build: ${full_image}"

    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "  [DRY RUN] gcloud builds submit with Dockerfile: ${dockerfile_rel_path}"
        return 0
    fi

    # Create temporary cloudbuild.yaml
    local cloudbuild_config
    cloudbuild_config=$(mktemp)
    cat > "${cloudbuild_config}" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '${full_image}'
      - '-f'
      - '${dockerfile_rel_path}'
      - '.'
images:
  - '${full_image}'
options:
  logging: CLOUD_LOGGING_ONLY
EOF

    if gcloud builds submit "${PROJECT_ROOT}" \
        --config="${cloudbuild_config}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet 2>&1; then
        log_success "  Built and pushed: ${full_image}"
        rm -f "${cloudbuild_config}"
        return 0
    else
        log_error "  Failed to build: ${image_name}"
        rm -f "${cloudbuild_config}"
        return 1
    fi
}

#===============================================================================
# Track Results
#===============================================================================
declare -a BUILT_IMAGES=()
declare -a SKIPPED_IMAGES=()
declare -a FAILED_BUILDS=()
declare -A IMAGE_TAGS=()  # Associative array: app_name -> tag

#===============================================================================
# Build Traditional Apps (Dockerfile-based)
#===============================================================================
log_step "Building Traditional Apps"

apps_count=$(yq eval '.apps | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<apps_count; i++)); do
    enabled=$(yq eval ".apps[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".apps[${i}].name" "${APPS_FILE}")
    path=$(yq eval ".apps[${i}].path // \"apps/${name}\"" "${APPS_FILE}")
    dockerfile=$(yq eval ".apps[${i}].build.dockerfile // \"Dockerfile\"" "${APPS_FILE}")

    # Skip if specific app requested and this isn't it
    if [[ -n "${SPECIFIC_APP}" && "${name}" != "${SPECIFIC_APP}" ]]; then
        continue
    fi

    APP_DIR="${PROJECT_ROOT}/${path}"
    DOCKERFILE_PATH="${APP_DIR}/${dockerfile}"

    if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
        log_warn "Dockerfile not found for ${name}: ${DOCKERFILE_PATH}"
        continue
    fi

    # Compute content hash
    CONTENT_HASH=$(compute_app_hash "${path}" "${dockerfile}")
    log_info "Processing app: ${name} (hash: ${CONTENT_HASH})"

    # Store the tag for this app
    IMAGE_TAGS["${name}"]="${CONTENT_HASH}"

    # Check if image already exists (unless force rebuild)
    if [[ "${FORCE_BUILD}" != "true" ]] && image_exists "${name}" "${CONTENT_HASH}"; then
        log_skip "${name}:${CONTENT_HASH} already exists in registry (content unchanged)"
        SKIPPED_IMAGES+=("${name}:${CONTENT_HASH}")
        continue
    fi

    # Build the image
    if [[ "${BUILD_METHOD}" == "cloudbuild" ]]; then
        if build_with_cloudbuild "${name}" "${path}/${dockerfile}" "${CONTENT_HASH}"; then
            BUILT_IMAGES+=("${name}:${CONTENT_HASH}")
        else
            FAILED_BUILDS+=("${name}")
        fi
    else
        if build_with_docker "${name}" "${DOCKERFILE_PATH}" "${PROJECT_ROOT}" "${CONTENT_HASH}"; then
            BUILT_IMAGES+=("${name}:${CONTENT_HASH}")
        else
            FAILED_BUILDS+=("${name}")
        fi
    fi
done

#===============================================================================
# Build Serverless Functions (k3sfn-based)
#===============================================================================
log_step "Building Serverless Functions"

serverless_count=$(yq eval '.serverless | length' "${APPS_FILE}" 2>/dev/null || echo "0")

for ((i=0; i<serverless_count; i++)); do
    enabled=$(yq eval ".serverless[${i}].enabled // true" "${APPS_FILE}")
    [[ "${enabled}" != "true" ]] && continue

    name=$(yq eval ".serverless[${i}].name" "${APPS_FILE}")
    path=$(yq eval ".serverless[${i}].path // \"apps/${name}\"" "${APPS_FILE}")

    # Skip if specific serverless requested and this isn't it
    if [[ -n "${SPECIFIC_SERVERLESS}" && "${name}" != "${SPECIFIC_SERVERLESS}" ]]; then
        continue
    fi

    APP_DIR="${PROJECT_ROOT}/${path}"

    # Check if it's a valid serverless app
    if [[ ! -d "${APP_DIR}/functions" ]]; then
        log_warn "Not a serverless app (no functions/ directory): ${path}"
        continue
    fi

    # Compute content hash
    CONTENT_HASH=$(compute_serverless_hash "${path}")
    log_info "Processing serverless: ${name} (hash: ${CONTENT_HASH})"

    # Store the tag for this app
    IMAGE_TAGS["${name}"]="${CONTENT_HASH}"

    # Check if image already exists (unless force rebuild)
    if [[ "${FORCE_BUILD}" != "true" ]] && image_exists "${name}" "${CONTENT_HASH}"; then
        log_skip "${name}:${CONTENT_HASH} already exists in registry (content unchanged)"
        SKIPPED_IMAGES+=("${name}:${CONTENT_HASH}")
        continue
    fi

    # Generate Dockerfile using k3sfn CLI
    TEMP_OUTPUT=$(mktemp -d)
    log_info "  Generating Dockerfile with k3sfn..."

    if ! uv run --project "${PROJECT_ROOT}/libs/k3sfn" k3sfn generate \
        --name "${name}" \
        --from-apps-yaml \
        --env "${ENVIRONMENT}" \
        --ingress "$(yq eval ".defaults.ingress.${ENVIRONMENT} // \"traefik\"" "${APPS_FILE}")" \
        --output "${TEMP_OUTPUT}" 2>&1; then
        log_error "  Failed to generate Dockerfile for ${name}"
        FAILED_BUILDS+=("${name}")
        rm -rf "${TEMP_OUTPUT}"
        continue
    fi

    if [[ ! -f "${TEMP_OUTPUT}/Dockerfile" ]]; then
        log_error "  Dockerfile not generated for ${name}"
        FAILED_BUILDS+=("${name}")
        rm -rf "${TEMP_OUTPUT}"
        continue
    fi

    # Copy Dockerfile to app directory for build context
    GENERATED_DOCKERFILE="${APP_DIR}/Dockerfile.generated"
    cp "${TEMP_OUTPUT}/Dockerfile" "${GENERATED_DOCKERFILE}"
    rm -rf "${TEMP_OUTPUT}"

    # Build the image
    if [[ "${BUILD_METHOD}" == "cloudbuild" ]]; then
        if build_with_cloudbuild "${name}" "${path}/Dockerfile.generated" "${CONTENT_HASH}"; then
            BUILT_IMAGES+=("${name}:${CONTENT_HASH}")
        else
            FAILED_BUILDS+=("${name}")
        fi
    else
        if build_with_docker "${name}" "${GENERATED_DOCKERFILE}" "${PROJECT_ROOT}" "${CONTENT_HASH}"; then
            BUILT_IMAGES+=("${name}:${CONTENT_HASH}")
        else
            FAILED_BUILDS+=("${name}")
        fi
    fi
done

#===============================================================================
# Write Image Tags File (per-app tags)
#===============================================================================
log_step "Writing Image Tags"

cat > "${IMAGE_TAGS_FILE}" <<EOF
# Auto-generated by build-images.sh - DO NOT EDIT
# Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Environment: ${ENVIRONMENT}
# Registry: ${REGISTRY}
#
# Tags are computed from content hash (SHA256, first 12 chars)
# Same content = same hash = no rebuild needed

REGISTRY=${REGISTRY}

# Per-app image tags (content-based)
EOF

for app_name in "${!IMAGE_TAGS[@]}"; do
    # Convert app name to uppercase and replace hyphens with underscores for variable name
    var_name=$(echo "${app_name}" | tr '[:lower:]-' '[:upper:]_')
    echo "IMAGE_TAG_${var_name}=${IMAGE_TAGS[${app_name}]}" >> "${IMAGE_TAGS_FILE}"
done

log_info "Written: ${IMAGE_TAGS_FILE}"
cat "${IMAGE_TAGS_FILE}"

#===============================================================================
# Summary
#===============================================================================
log_step "Build Summary"

echo ""

if [[ ${#BUILT_IMAGES[@]} -gt 0 ]]; then
    log_success "Built ${#BUILT_IMAGES[@]} image(s):"
    for img in "${BUILT_IMAGES[@]}"; do
        echo "  - ${REGISTRY}/${img}"
    done
    echo ""
fi

if [[ ${#SKIPPED_IMAGES[@]} -gt 0 ]]; then
    log_info "Skipped ${#SKIPPED_IMAGES[@]} image(s) (content unchanged):"
    for img in "${SKIPPED_IMAGES[@]}"; do
        echo "  - ${REGISTRY}/${img}"
    done
    echo ""
fi

if [[ ${#FAILED_BUILDS[@]} -gt 0 ]]; then
    log_error "Failed to build ${#FAILED_BUILDS[@]} image(s):"
    for img in "${FAILED_BUILDS[@]}"; do
        echo "  - ${img}"
    done
    exit 1
fi

if [[ ${#BUILT_IMAGES[@]} -eq 0 && ${#SKIPPED_IMAGES[@]} -eq 0 ]]; then
    log_warn "No images were processed"
    if [[ -n "${SPECIFIC_APP}${SPECIFIC_SERVERLESS}" ]]; then
        log_info "Check that the specified app exists and is enabled in apps.yaml"
    fi
fi

echo ""
log_info "Next steps:"
echo "  1. Run: ./scripts/generate-argocd-state.sh ${ENVIRONMENT}"
echo "     (This will use per-app tags from ${IMAGE_TAGS_FILE})"
echo "  2. Commit and push argocd-state/"
echo "  3. ArgoCD will sync the changes"
echo ""
