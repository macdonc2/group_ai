# Agent System Kubernetes Deployment

Helm chart for deploying the Agent System to Kubernetes.

## Prerequisites

- Kubernetes cluster (tested with Azure AKS)
- Helm 3.x
- kubectl configured
- Azure CLI (for ACR)
- Docker

## Quick Start

### 1. Create Secrets

Before deploying, create the required Kubernetes secrets:

> **Note**: OPENAI_API_KEY is NOT required at the system level. All users must configure their own API keys via the Settings UI.

```bash
# Create namespace
kubectl create namespace agent-system

# Create secrets (interactive)
make k8s-secrets

# Or manually:
kubectl create secret generic agent-system-secrets \
  --namespace agent-system \
  --from-literal=SECRET_KEY=your-jwt-secret-min-32-chars \
  --from-literal=ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  --from-literal=DATABASE_PASSWORD=your-db-password \
  --from-literal=NEO4J_PASSWORD=your-neo4j-password
```

### 2. Create ACR Pull Secret

```bash
make k8s-acr-secret

# Or manually:
kubectl create secret docker-registry acr-pull-secret \
  --namespace agent-system \
  --docker-server=macdoncml.azurecr.io \
  --docker-username=<username> \
  --docker-password=<password>
```

### 3. Build and Push Images

```bash
# Build and push to ACR
make docker-release

# Or with a specific tag
IMAGE_TAG=v1.0.0 make docker-release
```

### 4. Deploy

```bash
# Update Helm dependencies (PostgreSQL, Neo4j)
make helm-deps

# Deploy
make helm-deploy

# Or for production with overrides
make helm-deploy-prod
```

### 5. Verify Deployment

```bash
make helm-status
```

## Configuration

### values.yaml

Key configuration options:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Kubernetes namespace | `agent-system` |
| `backend.replicas` | Backend pod replicas | `1` |
| `frontend.replicas` | Frontend pod replicas | `1` |
| `ingress.host` | Domain name | `agent.macdonml.com` |
| `postgresql.enabled` | Deploy PostgreSQL | `true` |
| `neo4j.enabled` | Deploy Neo4j | `true` |

### Custom Values

Create a custom values file for your environment:

```yaml
# values-custom.yaml
ingress:
  host: your-domain.com

backend:
  replicas: 3
```

Deploy with custom values:

```bash
helm upgrade --install agent-system ./helm/agent-system \
  -f ./helm/agent-system/values-custom.yaml \
  --namespace agent-system
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Ingress                             │
│                   (agent.macdonml.com)                      │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               │ /api/*                       │ /*
               ▼                              ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│      Backend Service     │    │     Frontend Service     │
│       (FastAPI)          │    │        (Nginx)           │
└──────────────┬───────────┘    └──────────────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
┌─────────────┐ ┌─────────────┐
│ PostgreSQL  │ │   Neo4j     │
│ (Bitnami)   │ │ (Knowledge) │
└─────────────┘ └─────────────┘
```

## Makefile Commands

```bash
# Development
make backend          # Run backend locally
make frontend         # Run frontend locally

# Docker
make docker-build     # Build Docker images
make docker-push      # Push to ACR
make docker-release   # Build and push

# Kubernetes
make k8s-secrets      # Create secrets (interactive)
make helm-deps        # Update Helm dependencies
make helm-deploy      # Deploy with Helm
make helm-status      # Check deployment status
make helm-rollback    # Rollback to previous version
make helm-uninstall   # Remove deployment

# Debugging
make logs-backend     # Stream backend logs
make logs-frontend    # Stream frontend logs
make port-forward-backend   # Forward backend port locally
make port-forward-frontend  # Forward frontend port locally
```

## Troubleshooting

### Check pod logs

```bash
kubectl logs -f deployment/agent-system-backend -n agent-system
kubectl logs -f deployment/agent-system-frontend -n agent-system
```

### Check pod status

```bash
kubectl describe pod -l app.kubernetes.io/component=backend -n agent-system
```

### Database connection issues

```bash
# Test PostgreSQL connectivity
kubectl run -it --rm psql --image=postgres:15 --restart=Never -n agent-system -- \
  psql "postgresql://agent_system:PASSWORD@agent-system-postgresql:5432/agent_system"
```

### Neo4j connection issues

```bash
# Port forward Neo4j browser
kubectl port-forward svc/agent-system-neo4j 7474:7474 7687:7687 -n agent-system
# Open http://localhost:7474
```

## Updating

```bash
# Update image tag
IMAGE_TAG=v1.1.0 make docker-release

# Upgrade deployment
helm upgrade agent-system ./helm/agent-system \
  --namespace agent-system \
  --set backend.image.tag=v1.1.0 \
  --set frontend.image.tag=v1.1.0
```

## Rollback

```bash
# View history
helm history agent-system -n agent-system

# Rollback to previous
make helm-rollback

# Rollback to specific revision
helm rollback agent-system 2 -n agent-system
```
