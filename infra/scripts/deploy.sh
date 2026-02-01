#!/bin/bash
# Agent System Kubernetes Deployment Script
set -e

# Configuration
NAMESPACE="${NAMESPACE:-agent-system}"
RELEASE_NAME="${RELEASE_NAME:-agent-system}"
ACR_NAME="${ACR_NAME:-macdoncml}"
ACR_REGISTRY="${ACR_REGISTRY:-${ACR_NAME}.azurecr.io}"
CHART_PATH="./helm/agent-system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check required tools
check_requirements() {
    log_info "Checking requirements..."
    
    for cmd in kubectl helm az docker; do
        if ! command -v $cmd &> /dev/null; then
            log_error "$cmd is required but not installed"
            exit 1
        fi
    done
    
    log_info "All requirements satisfied"
}

# Login to Azure Container Registry
acr_login() {
    log_info "Logging into Azure Container Registry..."
    az acr login --name $ACR_NAME
}

# Build and push Docker images
build_images() {
    local TAG="${1:-latest}"
    
    log_info "Building backend image for linux/amd64..."
    docker build --platform linux/amd64 -f infra/docker/Dockerfile.backend -t ${ACR_REGISTRY}/agent-system-backend:${TAG} .
    
    log_info "Building frontend image for linux/amd64..."
    docker build --platform linux/amd64 -f infra/docker/Dockerfile.frontend -t ${ACR_REGISTRY}/agent-system-frontend:${TAG} .
    
    log_info "Pushing images to ACR..."
    docker push ${ACR_REGISTRY}/agent-system-backend:${TAG}
    docker push ${ACR_REGISTRY}/agent-system-frontend:${TAG}
    
    log_info "Images pushed successfully"
}

# Create namespace if it doesn't exist
create_namespace() {
    if ! kubectl get namespace $NAMESPACE &> /dev/null; then
        log_info "Creating namespace: $NAMESPACE"
        kubectl create namespace $NAMESPACE
    else
        log_info "Namespace $NAMESPACE already exists"
    fi
}

# Create secrets (interactive)
create_secrets() {
    log_info "Creating Kubernetes secrets..."
    
    if kubectl get secret agent-system-secrets -n $NAMESPACE &> /dev/null; then
        log_warn "Secret agent-system-secrets already exists. Skipping..."
        return
    fi
    
    echo "Please provide the following secret values:"
    echo "(Note: OPENAI_API_KEY is NOT required - users manage their own keys)"
    echo
    
    read -sp "SECRET_KEY (JWT secret, min 32 chars): " SECRET_KEY
    echo
    read -sp "ENCRYPTION_KEY (Fernet key for encrypting user API keys): " ENCRYPTION_KEY
    echo
    read -sp "DATABASE_PASSWORD: " DATABASE_PASSWORD
    echo
    read -sp "NEO4J_PASSWORD: " NEO4J_PASSWORD
    echo
    
    # Neo4j auth format is username/password (for Neo4j chart)
    # Backend also needs NEO4J_PASSWORD separately
    NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}"
    
    kubectl create secret generic agent-system-secrets \
        --namespace $NAMESPACE \
        --from-literal=SECRET_KEY="$SECRET_KEY" \
        --from-literal=ENCRYPTION_KEY="$ENCRYPTION_KEY" \
        --from-literal=DATABASE_PASSWORD="$DATABASE_PASSWORD" \
        --from-literal=NEO4J_PASSWORD="$NEO4J_PASSWORD" \
        --from-literal=NEO4J_AUTH="$NEO4J_AUTH"
    
    log_info "Secrets created successfully"
}

# Create ACR pull secret
create_acr_secret() {
    if kubectl get secret acr-pull-secret -n $NAMESPACE &> /dev/null; then
        log_warn "ACR pull secret already exists. Skipping..."
        return
    fi
    
    log_info "Creating ACR pull secret..."
    
    # Get ACR credentials
    ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username -o tsv)
    ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)
    
    kubectl create secret docker-registry acr-pull-secret \
        --namespace $NAMESPACE \
        --docker-server=${ACR_REGISTRY} \
        --docker-username=$ACR_USERNAME \
        --docker-password=$ACR_PASSWORD
    
    log_info "ACR pull secret created"
}

# Update Helm dependencies
update_deps() {
    log_info "Updating Helm dependencies..."
    helm dependency update $CHART_PATH
}

# Deploy with Helm
helm_deploy() {
    local VALUES_FILE="${1:-}"
    
    log_info "Deploying with Helm..."
    
    local HELM_ARGS="upgrade --install $RELEASE_NAME $CHART_PATH \
        --namespace $NAMESPACE \
        --create-namespace \
        --wait \
        --timeout 10m"
    
    if [ -n "$VALUES_FILE" ] && [ -f "$VALUES_FILE" ]; then
        HELM_ARGS="$HELM_ARGS -f $VALUES_FILE"
    fi
    
    eval "helm $HELM_ARGS"
    
    log_info "Deployment complete!"
}

# Get deployment status
status() {
    log_info "Deployment Status:"
    echo
    kubectl get pods -n $NAMESPACE
    echo
    kubectl get svc -n $NAMESPACE
    echo
    kubectl get ingress -n $NAMESPACE
}

# Rollback deployment
rollback() {
    local REVISION="${1:-}"
    
    if [ -z "$REVISION" ]; then
        log_info "Rolling back to previous revision..."
        helm rollback $RELEASE_NAME -n $NAMESPACE
    else
        log_info "Rolling back to revision $REVISION..."
        helm rollback $RELEASE_NAME $REVISION -n $NAMESPACE
    fi
}

# Uninstall deployment
uninstall() {
    log_warn "This will delete all resources in namespace $NAMESPACE"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        helm uninstall $RELEASE_NAME -n $NAMESPACE
        log_info "Deployment uninstalled"
    else
        log_info "Cancelled"
    fi
}

# Full deployment
full_deploy() {
    local TAG="${1:-latest}"
    local VALUES_FILE="${2:-}"
    
    check_requirements
    acr_login
    build_images $TAG
    create_namespace
    create_secrets
    create_acr_secret
    update_deps
    helm_deploy "$VALUES_FILE"
    status
}

# Print usage
usage() {
    echo "Agent System Deployment Script"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  full-deploy [tag] [values-file]  Full deployment (build, push, deploy)"
    echo "  build [tag]                       Build and push Docker images"
    echo "  deploy [values-file]              Deploy with Helm"
    echo "  secrets                           Create Kubernetes secrets"
    echo "  status                            Show deployment status"
    echo "  rollback [revision]               Rollback to previous or specific revision"
    echo "  uninstall                         Uninstall the deployment"
    echo "  deps                              Update Helm dependencies"
    echo
    echo "Environment variables:"
    echo "  NAMESPACE       Kubernetes namespace (default: agent-system)"
    echo "  RELEASE_NAME    Helm release name (default: agent-system)"
    echo "  ACR_NAME        Azure Container Registry name (default: macdoncml)"
}

# Main
case "${1:-}" in
    full-deploy)
        full_deploy "${2:-latest}" "${3:-}"
        ;;
    build)
        check_requirements
        acr_login
        build_images "${2:-latest}"
        ;;
    deploy)
        check_requirements
        update_deps
        helm_deploy "${2:-}"
        ;;
    secrets)
        create_namespace
        create_secrets
        ;;
    acr-secret)
        create_namespace
        create_acr_secret
        ;;
    status)
        status
        ;;
    rollback)
        rollback "${2:-}"
        ;;
    uninstall)
        uninstall
        ;;
    deps)
        update_deps
        ;;
    *)
        usage
        ;;
esac
