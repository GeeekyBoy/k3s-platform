#!/bin/bash
# Setup script for External Secrets Operator on GCP
#
# This script:
# 1. Creates a GCP service account for ESO
# 2. Grants Secret Manager access
# 3. Configures Workload Identity binding
#
# Prerequisites:
# - gcloud CLI authenticated
# - kubectl configured for the target cluster
# - ESO installed in the cluster
#
# Usage:
#   ./providers/gcp/setup-secrets.sh
#   GCP_PROJECT_ID=my-project ./providers/gcp/setup-secrets.sh

set -euo pipefail

# Configuration
GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
GCP_REGION="${GCP_REGION:-us-central1}"
GCP_CLUSTER_NAME="${GCP_CLUSTER_NAME:-k3s-gcp}"
K8S_NAMESPACE="${K8S_NAMESPACE:-external-secrets}"
K8S_SA_NAME="${K8S_SA_NAME:-external-secrets-sa}"
GCP_SA_NAME="${GCP_SA_NAME:-external-secrets-sa}"

if [[ -z "$GCP_PROJECT_ID" ]]; then
    echo "Error: GCP_PROJECT_ID is not set"
    echo "Usage: GCP_PROJECT_ID=my-project ./providers/gcp/setup-secrets.sh"
    exit 1
fi

echo "=== External Secrets Operator GCP Setup ==="
echo "Project: $GCP_PROJECT_ID"
echo "Region: $GCP_REGION"
echo "Cluster: $GCP_CLUSTER_NAME"
echo ""

# Step 1: Create GCP Service Account
echo "Step 1: Creating GCP service account..."
if gcloud iam service-accounts describe "$GCP_SA_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" &>/dev/null; then
    echo "  Service account already exists"
else
    gcloud iam service-accounts create "$GCP_SA_NAME" \
        --display-name="External Secrets Operator" \
        --description="Service account for ESO to access Secret Manager"
    echo "  Created service account: $GCP_SA_NAME"
fi

# Step 2: Grant Secret Manager access
echo "Step 2: Granting Secret Manager access..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:$GCP_SA_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet
echo "  Granted roles/secretmanager.secretAccessor"

# Step 3: Configure Workload Identity binding
echo "Step 3: Configuring Workload Identity binding..."
gcloud iam service-accounts add-iam-policy-binding "$GCP_SA_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/iam.workloadIdentityUser" \
    --member="serviceAccount:$GCP_PROJECT_ID.svc.id.goog[$K8S_NAMESPACE/$K8S_SA_NAME]" \
    --quiet
echo "  Bound K8s SA $K8S_NAMESPACE/$K8S_SA_NAME to GCP SA"

# Step 4: Create K8s namespace if needed
echo "Step 4: Ensuring K8s namespace exists..."
kubectl create namespace "$K8S_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Step 5: Create/update K8s ServiceAccount with annotation
echo "Step 5: Creating annotated K8s ServiceAccount..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: $K8S_SA_NAME
  namespace: $K8S_NAMESPACE
  annotations:
    iam.gke.io/gcp-service-account: $GCP_SA_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com
  labels:
    k3sapp.io/component: secrets
EOF
echo "  Created K8s ServiceAccount with Workload Identity annotation"

# Step 6: Apply ClusterSecretStore
echo "Step 6: Applying ClusterSecretStore..."
export GCP_PROJECT_ID GCP_REGION GCP_CLUSTER_NAME
envsubst < "$(dirname "$0")/../../platform/external-secrets/cluster-secret-store-gcp.yaml" | kubectl apply -f -
echo "  Applied ClusterSecretStore: gcp-secret-manager"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Verify the ClusterSecretStore is ready:"
echo "   kubectl get clustersecretstore gcp-secret-manager"
echo ""
echo "2. Test with an ExternalSecret:"
echo "   kubectl apply -f - <<EOF"
echo "   apiVersion: external-secrets.io/v1beta1"
echo "   kind: ExternalSecret"
echo "   metadata:"
echo "     name: test-secret"
echo "     namespace: apps"
echo "   spec:"
echo "     refreshInterval: 1h"
echo "     secretStoreRef:"
echo "       kind: ClusterSecretStore"
echo "       name: gcp-secret-manager"
echo "     target:"
echo "       name: test-secret"
echo "     data:"
echo "       - secretKey: TEST_VALUE"
echo "         remoteRef:"
echo "           key: K8S_VALKEY_PASSWORD"
echo "   EOF"
echo ""
echo "3. Check the synced secret:"
echo "   kubectl get secret test-secret -n apps -o yaml"
echo ""
