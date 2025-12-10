CLUSTER_NAME="k3s-cluster"
GCP_ZONE="us-central1-a"
CONTROL_PLANE_IP="34.59.36.164"

# Get kubeconfig
retries=30
while [[ $retries -gt 0 ]]; do
    if gcloud compute ssh "${CLUSTER_NAME}-control-plane" \
        --tunnel-through-iap \
        --zone="${GCP_ZONE}" \
        -- "sudo cat /etc/rancher/k3s/k3s.yaml" > /tmp/k3s-kubeconfig 2>/dev/null; then
        
        # Update kubeconfig with external IP
        sed -i '' "s|127.0.0.1|${CONTROL_PLANE_IP}|g" /tmp/k3s-kubeconfig
        sed -i '' "s|default|${CLUSTER_NAME}|g" /tmp/k3s-kubeconfig
        
        mkdir -p ~/.kube
        cp /tmp/k3s-kubeconfig ~/.kube/k3s-gcp-config
        export KUBECONFIG=~/.kube/k3s-gcp-config
        
        if kubectl get nodes &>/dev/null; then
            echo "Kubeconfig retrieved and working"
            break
        fi
    fi
    
    echo "Waiting for K3s... (${retries} retries left)"
    sleep 30
    ((retries--))
done