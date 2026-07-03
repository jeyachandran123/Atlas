"""
Cloud & infrastructure prompt modules.
"""

from __future__ import annotations

AWS = """\
AWS expertise: EC2, ECS/Fargate, Lambda, RDS, ElastiCache, S3, CloudFront, \
API Gateway, SQS/SNS, IAM least-privilege, VPC design, \
CloudWatch, and CDK/Terraform IaC."""

AZURE = """\
Azure expertise: App Service, AKS, Azure Functions, Azure SQL, \
Cosmos DB, Service Bus, Azure AD, Key Vault, \
Application Insights, and Bicep/ARM templates."""

GCP = """\
Google Cloud expertise: Cloud Run, GKE, Cloud Functions, \
BigQuery, Pub/Sub, Cloud SQL, Firebase, \
and Terraform GCP provider."""

DOCKER = """\
Docker expertise: multi-stage builds, layer caching optimization, \
non-root users, health checks, .dockerignore, \
docker-compose for local dev, and image size minimization."""

KUBERNETES = """\
Kubernetes expertise: Deployments, Services, Ingress, ConfigMaps, Secrets, \
HPA/VPA, resource limits/requests, liveness/readiness probes, \
RBAC, NetworkPolicies, and Helm charts."""

TERRAFORM = """\
Terraform expertise: module design, state management (remote backends), \
workspace strategies, provider versioning, \
and Terragrunt for DRY configurations."""

CICD = """\
CI/CD expertise: pipeline design (build → test → security scan → deploy), \
blue/green deployments, canary releases, \
rollback strategies, and secrets management in pipelines."""

GITHUB_ACTIONS = """\
GitHub Actions expertise: workflow triggers, matrix builds, \
reusable workflows, composite actions, \
OIDC for cloud auth, and caching strategies."""
