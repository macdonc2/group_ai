.PHONY: setup install dev backend frontend test lint clean neo4j docker-build docker-push deploy k8s-secrets helm-deps helm-deploy helm-status helm-rollback helm-uninstall build-backend push-backend rollout-backend deploy-backend build-frontend push-frontend rollout-frontend deploy-frontend

# ============================================================================
# Development
# ============================================================================

# Setup complete development environment
setup: install
	@echo "Creating .env file if not exists..."
	@test -f .env || cp .env.example .env
	@echo "Setup complete! Edit .env with your API keys."

# Install all dependencies
install:
	@echo "Creating Python virtual environment..."
	uv venv .venv
	@echo "Installing Python dependencies..."
	uv pip install -e ".[dev]"
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Run backend server
backend:
	@source .venv/bin/activate && uvicorn agent_system.adapters.inbound.api.main:app --reload --port 8000

# Run frontend server
frontend:
	cd frontend && npm run dev

# Run both servers (requires tmux or separate terminals)
dev:
	@echo "Start backend with: make backend"
	@echo "Start frontend with: make frontend"

# Run tests
test:
	@source .venv/bin/activate && pytest -m unit -q

# Run linters
lint:
	@source .venv/bin/activate && ruff check src/
	cd frontend && npm run lint

# Clean build artifacts
clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	cd frontend && rm -rf dist node_modules/.cache

# Start Neo4j (Docker)
neo4j:
	docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest

# Stop and remove Neo4j container
neo4j-stop:
	docker stop neo4j && docker rm neo4j

# ============================================================================
# Kubernetes Deployment
# ============================================================================

# Configuration
ACR_NAME ?= macdoncml
ACR_REGISTRY ?= $(ACR_NAME).azurecr.io
IMAGE_TAG ?= latest
NAMESPACE ?= agent-system
RELEASE_NAME ?= agent-system

# Login to Azure Container Registry
acr-login:
	az acr login --name $(ACR_NAME)

# Build Docker images for linux/amd64 (required for AKS)
docker-build:
	@echo "Building backend image for linux/amd64..."
	docker build --platform linux/amd64 -f infra/docker/Dockerfile.backend -t $(ACR_REGISTRY)/agent-system-backend:$(IMAGE_TAG) .
	@echo "Building frontend image for linux/amd64..."
	docker build --platform linux/amd64 -f infra/docker/Dockerfile.frontend -t $(ACR_REGISTRY)/agent-system-frontend:$(IMAGE_TAG) .

# Push Docker images to ACR
docker-push: acr-login
	docker push $(ACR_REGISTRY)/agent-system-backend:$(IMAGE_TAG)
	docker push $(ACR_REGISTRY)/agent-system-frontend:$(IMAGE_TAG)

# Build and push images
docker-release: docker-build docker-push

# Update Helm dependencies
helm-deps:
	helm dependency update ./helm/agent-system

# Create Kubernetes secrets (interactive)
k8s-secrets:
	@chmod +x infra/scripts/deploy.sh
	./infra/scripts/deploy.sh secrets

# Create ACR pull secret
k8s-acr-secret:
	@chmod +x infra/scripts/deploy.sh
	./infra/scripts/deploy.sh acr-secret

# Deploy with Helm
helm-deploy: helm-deps
	helm upgrade --install $(RELEASE_NAME) ./helm/agent-system \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--wait \
		--timeout 10m

# Deploy with custom values file
helm-deploy-prod: helm-deps
	helm upgrade --install $(RELEASE_NAME) ./helm/agent-system \
		--namespace $(NAMESPACE) \
		--create-namespace \
		-f ./helm/agent-system/values-prod.yaml \
		--wait \
		--timeout 10m

# Get deployment status
helm-status:
	@echo "=== Pods ==="
	kubectl get pods -n $(NAMESPACE)
	@echo "\n=== Services ==="
	kubectl get svc -n $(NAMESPACE)
	@echo "\n=== Ingress ==="
	kubectl get ingress -n $(NAMESPACE)

# Rollback to previous release
helm-rollback:
	helm rollback $(RELEASE_NAME) -n $(NAMESPACE)

# Uninstall deployment
helm-uninstall:
	helm uninstall $(RELEASE_NAME) -n $(NAMESPACE)

# Full deployment (build, push, deploy)
deploy: docker-release helm-deploy helm-status

# ============================================================================
# Quick Backend Deployment (faster iteration)
# ============================================================================

# Build backend only
build-backend:
	@echo "Building backend image for linux/amd64..."
	docker build --platform linux/amd64 -f infra/docker/Dockerfile.backend -t $(ACR_REGISTRY)/pydantic-ai-backend:$(IMAGE_TAG) .

# Push backend only
push-backend: acr-login
	docker push $(ACR_REGISTRY)/pydantic-ai-backend:$(IMAGE_TAG)

# Rollout restart backend (pull new image)
rollout-backend:
	kubectl rollout restart deployment/agent-system-backend -n $(NAMESPACE)
	kubectl rollout status deployment/agent-system-backend -n $(NAMESPACE) --timeout=90s

# Quick deploy backend (build, push, rollout)
deploy-backend: build-backend push-backend rollout-backend
	@echo "Backend deployed successfully!"

# Build frontend only
build-frontend:
	@echo "Building frontend image for linux/amd64..."
	docker build --platform linux/amd64 -f infra/docker/Dockerfile.frontend -t $(ACR_REGISTRY)/pydantic-ai-frontend:$(IMAGE_TAG) .

# Push frontend only
push-frontend: acr-login
	docker push $(ACR_REGISTRY)/pydantic-ai-frontend:$(IMAGE_TAG)

# Rollout restart frontend
rollout-frontend:
	kubectl rollout restart deployment/agent-system-frontend -n $(NAMESPACE)
	kubectl rollout status deployment/agent-system-frontend -n $(NAMESPACE) --timeout=90s

# Quick deploy frontend (build, push, rollout)
deploy-frontend: build-frontend push-frontend rollout-frontend
	@echo "Frontend deployed successfully!"

# ============================================================================
# Logs and Debugging
# ============================================================================

# View logs
logs-backend:
	kubectl logs -f -l app.kubernetes.io/component=backend -n $(NAMESPACE)

logs-frontend:
	kubectl logs -f -l app.kubernetes.io/component=frontend -n $(NAMESPACE)

# Port forward for local testing
port-forward-backend:
	kubectl port-forward svc/$(RELEASE_NAME)-backend 8000:80 -n $(NAMESPACE)

port-forward-frontend:
	kubectl port-forward svc/$(RELEASE_NAME)-frontend 3000:80 -n $(NAMESPACE)
