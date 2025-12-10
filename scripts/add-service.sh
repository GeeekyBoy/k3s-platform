#!/bin/bash
set -euo pipefail

#===============================================================================
# Add New Traditional Service
#
# Creates scaffolding for a new traditional service (Dockerfile-based).
# Generates application code, Dockerfile, and Kubernetes manifests.
#
# For serverless functions, use: ./scripts/new-serverless-app.sh
#
# Usage:
#   ./scripts/add-service.sh <service-name> [options]
#
# Examples:
#   ./scripts/add-service.sh my-api --port 3000 --lang node
#   ./scripts/add-service.sh worker --replicas 3 --lang python
#   ./scripts/add-service.sh frontend --port 80 --image nginx:latest
#===============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default values
SERVICE_NAME=""
SERVICE_PORT="8080"
SERVICE_REPLICAS="2"
SERVICE_IMAGE=""
SERVICE_LANG=""

usage() {
    cat << EOF
Usage: $(basename "$0") <service-name> [options]

Create scaffolding for a new service in the K3s platform.

Options:
  --port PORT       Service port (default: 8080)
  --replicas NUM    Number of replicas (default: 2)
  --image IMAGE     Docker image (default: auto-built)
  --lang LANG       Language template: python, node, go (default: python)
  -h, --help        Show this help message

Examples:
  $(basename "$0") my-api --port 3000 --lang node
  $(basename "$0") worker --replicas 3 --lang python
  $(basename "$0") frontend --port 80 --image nginx:latest

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        --port)
            SERVICE_PORT="$2"
            shift 2
            ;;
        --replicas)
            SERVICE_REPLICAS="$2"
            shift 2
            ;;
        --image)
            SERVICE_IMAGE="$2"
            shift 2
            ;;
        --lang)
            SERVICE_LANG="$2"
            shift 2
            ;;
        -*)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            if [[ -z "$SERVICE_NAME" ]]; then
                SERVICE_NAME="$1"
            else
                log_error "Unexpected argument: $1"
                usage
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$SERVICE_NAME" ]]; then
    log_error "Service name is required"
    usage
    exit 1
fi

# Validate service name
if [[ ! "$SERVICE_NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
    log_error "Service name must be lowercase, start with a letter, and contain only letters, numbers, and hyphens"
    exit 1
fi

# Set defaults
SERVICE_LANG="${SERVICE_LANG:-python}"
if [[ -z "$SERVICE_IMAGE" ]]; then
    SERVICE_IMAGE="${SERVICE_NAME}:latest"
fi

log_info "Creating service: ${SERVICE_NAME}"
log_info "  Port: ${SERVICE_PORT}"
log_info "  Replicas: ${SERVICE_REPLICAS}"
log_info "  Language: ${SERVICE_LANG}"

#═══════════════════════════════════════════════════════════════════════════════
# Create app directory structure
#═══════════════════════════════════════════════════════════════════════════════
APP_DIR="${PROJECT_ROOT}/apps/${SERVICE_NAME}"
K8S_DIR="${PROJECT_ROOT}/k8s/base/${SERVICE_NAME}"

mkdir -p "${APP_DIR}/src"
mkdir -p "${K8S_DIR}"

#═══════════════════════════════════════════════════════════════════════════════
# Create Dockerfile based on language
#═══════════════════════════════════════════════════════════════════════════════
case "${SERVICE_LANG}" in
    python)
        cat > "${APP_DIR}/Dockerfile" << 'EOF'
FROM python:3.12-slim as production
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./
USER appuser
ENV PYTHONUNBUFFERED=1
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["python", "main.py"]
EOF
        cat > "${APP_DIR}/Dockerfile.dev" << 'EOF'
FROM python:3.12-slim
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt watchfiles
USER appuser
COPY --chown=appuser:appgroup src/ ./src/
ENV PYTHONUNBUFFERED=1 ENV=development
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["python", "-m", "watchfiles", "python src/main.py", "/app/src"]
EOF
        cat > "${APP_DIR}/requirements.txt" << 'EOF'
# Add your dependencies here
EOF
        cat > "${APP_DIR}/src/main.py" << 'EOF'
"""Main application entry point"""
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json

PORT = int(os.getenv("PORT", "SERVICE_PORT_PLACEHOLDER"))

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Hello from SERVICE_NAME_PLACEHOLDER!")

if __name__ == "__main__":
    print(f"Starting server on port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
EOF
        ;;
    
    node)
        cat > "${APP_DIR}/Dockerfile" << 'EOF'
FROM node:20-slim as production
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY src/ ./
USER appuser
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["node", "index.js"]
EOF
        cat > "${APP_DIR}/Dockerfile.dev" << 'EOF'
FROM node:20-slim
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser
WORKDIR /app
COPY package*.json ./
RUN npm install
USER appuser
COPY --chown=appuser:appgroup src/ ./src/
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["npm", "run", "dev"]
EOF
        cat > "${APP_DIR}/package.json" << EOF
{
  "name": "${SERVICE_NAME}",
  "version": "1.0.0",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "dev": "node --watch src/index.js"
  }
}
EOF
        cat > "${APP_DIR}/src/index.js" << 'EOF'
const http = require('http');
const PORT = process.env.PORT || SERVICE_PORT_PLACEHOLDER;

const server = http.createServer((req, res) => {
    if (req.url === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'healthy' }));
    } else {
        res.writeHead(200, { 'Content-Type': 'text/plain' });
        res.end('Hello from SERVICE_NAME_PLACEHOLDER!');
    }
});

server.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});
EOF
        ;;
    
    go)
        cat > "${APP_DIR}/Dockerfile" << 'EOF'
FROM golang:1.23-alpine as builder
WORKDIR /build
COPY go.* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o app ./src

FROM alpine:3.20
RUN adduser -D appuser
WORKDIR /app
COPY --from=builder /build/app .
USER appuser
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["./app"]
EOF
        cat > "${APP_DIR}/Dockerfile.dev" << 'EOF'
FROM golang:1.23-alpine
RUN go install github.com/cosmtrek/air@latest
WORKDIR /app
COPY go.* ./
RUN go mod download
COPY . .
EXPOSE SERVICE_PORT_PLACEHOLDER
CMD ["air", "-c", ".air.toml"]
EOF
        cat > "${APP_DIR}/go.mod" << EOF
module ${SERVICE_NAME}

go 1.23
EOF
        cat > "${APP_DIR}/src/main.go" << 'EOF'
package main

import (
    "encoding/json"
    "fmt"
    "net/http"
    "os"
)

func main() {
    port := os.Getenv("PORT")
    if port == "" {
        port = "SERVICE_PORT_PLACEHOLDER"
    }

    http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
    })

    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprintf(w, "Hello from SERVICE_NAME_PLACEHOLDER!")
    })

    fmt.Printf("Server running on port %s\n", port)
    http.ListenAndServe(":"+port, nil)
}
EOF
        ;;
    
    *)
        log_error "Unsupported language: ${SERVICE_LANG}"
        exit 1
        ;;
esac

# Replace placeholders in all files (cross-platform)
if [[ "$OSTYPE" == "darwin"* ]]; then
    find "${APP_DIR}" -type f -exec sed -i '' "s/SERVICE_PORT_PLACEHOLDER/${SERVICE_PORT}/g" {} \;
    find "${APP_DIR}" -type f -exec sed -i '' "s/SERVICE_NAME_PLACEHOLDER/${SERVICE_NAME}/g" {} \;
else
    find "${APP_DIR}" -type f -exec sed -i "s/SERVICE_PORT_PLACEHOLDER/${SERVICE_PORT}/g" {} \;
    find "${APP_DIR}" -type f -exec sed -i "s/SERVICE_NAME_PLACEHOLDER/${SERVICE_NAME}/g" {} \;
fi

#═══════════════════════════════════════════════════════════════════════════════
# Create Kubernetes manifests
#═══════════════════════════════════════════════════════════════════════════════
cat > "${K8S_DIR}/deployment.yaml" << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${SERVICE_NAME}
  namespace: apps
  labels:
    app: ${SERVICE_NAME}
spec:
  replicas: ${SERVICE_REPLICAS}
  selector:
    matchLabels:
      app: ${SERVICE_NAME}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: ${SERVICE_NAME}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: ${SERVICE_NAME}
          image: ${SERVICE_IMAGE}
          ports:
            - name: http
              containerPort: ${SERVICE_PORT}
          env:
            - name: PORT
              value: "${SERVICE_PORT}"
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
EOF

cat > "${K8S_DIR}/service.yaml" << EOF
apiVersion: v1
kind: Service
metadata:
  name: ${SERVICE_NAME}
  namespace: apps
  labels:
    app: ${SERVICE_NAME}
spec:
  type: ClusterIP
  selector:
    app: ${SERVICE_NAME}
  ports:
    - name: http
      port: ${SERVICE_PORT}
      targetPort: http
EOF

cat > "${K8S_DIR}/pdb.yaml" << EOF
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: ${SERVICE_NAME}
  namespace: apps
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: ${SERVICE_NAME}
EOF

#═══════════════════════════════════════════════════════════════════════════════
# Update base kustomization.yaml
#═══════════════════════════════════════════════════════════════════════════════
KUSTOMIZE_FILE="${PROJECT_ROOT}/k8s/base/kustomization.yaml"

# Add new resources if not already present
if ! grep -q "${SERVICE_NAME}/deployment.yaml" "${KUSTOMIZE_FILE}"; then
    # Add the new resources to kustomization.yaml (cross-platform)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "/^resources:/a\\
  - ${SERVICE_NAME}/deployment.yaml\\
  - ${SERVICE_NAME}/service.yaml\\
  - ${SERVICE_NAME}/pdb.yaml" "${KUSTOMIZE_FILE}"
    else
        sed -i "/^resources:/a\\  - ${SERVICE_NAME}/deployment.yaml\n  - ${SERVICE_NAME}/service.yaml\n  - ${SERVICE_NAME}/pdb.yaml" "${KUSTOMIZE_FILE}"
    fi
    log_info "Updated kustomization.yaml"
fi

#═══════════════════════════════════════════════════════════════════════════════
# Update Tiltfile
#═══════════════════════════════════════════════════════════════════════════════
TILTFILE="${PROJECT_ROOT}/Tiltfile"

# Add Tilt configuration for new service
cat >> "${TILTFILE}" << EOF

# ============================================================================
# ${SERVICE_NAME} (auto-generated)
# ============================================================================

docker_build(
    '${SERVICE_NAME}',
    context='./apps/${SERVICE_NAME}',
    dockerfile='./apps/${SERVICE_NAME}/Dockerfile.dev',
    live_update=[
        sync('./apps/${SERVICE_NAME}/src/', '/app/src/'),
    ],
)

k8s_resource(
    '${SERVICE_NAME}',
    port_forwards=[port_forward(${SERVICE_PORT}, ${SERVICE_PORT}, name='${SERVICE_NAME}')],
    labels=['app'],
)
EOF

log_info "Updated Tiltfile"

#═══════════════════════════════════════════════════════════════════════════════
# Summary
#═══════════════════════════════════════════════════════════════════════════════
echo ""
log_success "Service '${SERVICE_NAME}' created successfully!"
echo ""
echo "Files created:"
echo "  ${APP_DIR}/"
echo "    ├── Dockerfile"
echo "    ├── Dockerfile.dev"
echo "    └── src/"
echo "  ${K8S_DIR}/"
echo "    ├── deployment.yaml"
echo "    ├── service.yaml"
echo "    └── pdb.yaml"
echo ""
echo "Next steps:"
echo "  1. Implement your service in apps/${SERVICE_NAME}/src/"
echo "  2. Add dependencies to requirements.txt/package.json/go.mod"
echo "  3. For local dev: tilt up"
echo "  4. For GCP: ./providers/gcp/deploy.sh"
echo ""
