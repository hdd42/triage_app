# Deployment Options and Strategy

Last updated: 2025-09-15

This document outlines how to deploy this application for quick demo/testing and how to evolve it into a production-ready, cloud-agnostic deployment. It also provides an AWS reference architecture that keeps compute private (EC2 in private subnets) and fronts it with API Gateway. No Terraform code is included here; this is a blueprint you can implement with your preferred IaC.

## Philosophy: Build once, deploy anywhere

For take-home projects and real-world healthcare deployments alike, the goal should be a solution that deploys anywhere: AWS, Azure, GCP, or on-prem. Healthcare organizations often need to run on their own dedicated infrastructure due to compliance, procurement, and vendor preferences.

Key practices for portability:
- Container-first: Package the app into a Docker image that runs the same way in all environments.
- 12-factor config: Use environment variables and avoid hard-coded provider specifics.
- Standard interfaces: Use HTTP/REST, OpenAPI, and standard drivers/SDK abstractions.
- Externalize state: Use managed databases and object stores via clear interfaces.
- Secrets management: Use the platform’s native secret store (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, or Kubernetes secrets) via environment injection.

For the take-home: it’s more meaningful to show a working app deployed in a portable way than to mandate an AWS-specific build with Lambda + API Gateway. The Render deployment below is great for demonstration; the AWS architecture shows one production-leaning path that keeps compute private.

---

## Demo note: Render

We deployed this app to Render for easy showcasing and testing.

Notes for reviewers:
- For a take-home, asking for deep DevOps/MLOps work (e.g., a full AWS Lambda + API Gateway build) is excessive and distracts from evaluating the core solution.
- Candidates should be evaluated on a “deploy everywhere” approach—clean interfaces, containerization, and portability—rather than provider-specific implementations.

---

## Option B: AWS reference architecture (EC2 in private subnets, API Gateway in front)

This design keeps the application instances private, exposes a managed, secure API endpoint, and supports gradual hardening for compliance. It uses Terraform as the infrastructure tool of choice (not included here).

High-level architecture:
- Amazon API Gateway (HTTP API) with WAF for public ingress and TLS termination.
- VPC Link from API Gateway to a private load balancer (NLB or ALB) inside your VPC.
- Private ALB/NLB targets an Auto Scaling Group (ASG) of EC2 instances running the app in private subnets.
- Private subnets route outbound via NAT Gateways (for OS/package updates, external dependencies).
- Secrets and config via AWS Secrets Manager and/or SSM Parameter Store injected as environment variables on boot.
- Data layer: managed RDS (e.g., PostgreSQL) in private subnets, security-group-restricted to the app tier.
- Observability: CloudWatch logs, metrics, alarms. Optionally OpenTelemetry collectors -> your APM.
- Optional: S3 for object storage, KMS for encryption at rest, Route 53 for DNS, ACM for certs.

Traffic flow (simplified):
- Client -> API Gateway (TLS, WAF, auth, throttling)
- API Gateway -> VPC Link -> Private NLB/ALB
- NLB/ALB -> EC2 Auto Scaling Group (private subnets)

Notes:
- API Gateway does not directly reach EC2; use a VPC Link to a private NLB/ALB.
- Choose NLB for simplicity and performance, ALB if you need Layer 7 features.
- Keep all app instances in private subnets; no public IPs on EC2.

Security & compliance posture:
- TLS everywhere; consider TLS from API Gateway to NLB/ALB and to EC2 (end-to-end encryption).
- WAF on API Gateway for basic OWASP protections and rate limiting.
- Least privilege IAM roles for EC2 (access only to required secrets and services).
- Database encryption at rest (RDS + KMS), S3 SSE, and strict security groups.
- Centralized audit logs (CloudTrail, CloudWatch) and secrets rotation policies.

Scaling & resilience:
- Auto Scaling Group policies based on CPU/memory or custom metrics.
- Multi-AZ subnets for high availability.
- Blue/green or canary via weighted target groups or API stages.

Suggested Terraform module layout (no code):
- network: VPC, subnets (public for NAT, private for app/DB), route tables.
- security: security groups, NACLs, KMS keys.
- lb: internal ALB/NLB, target groups, listeners.
- compute: launch template + ASG for EC2 (user-data to bootstrap the app container or native app).
- apigw: API Gateway, VPC Link, integrations, WAF association.
- data: RDS (PostgreSQL), parameter groups, backups, subnet groups.
- secrets: Secrets Manager and Parameter Store entries and IAM policies.
- observability: CloudWatch log groups, metric filters, alarms.
- dns: Route 53 records, ACM certificates.

Runtime considerations on EC2:
- Containerize the app and run it under systemd or a process manager (e.g., `docker run`/`docker compose`, or ECS agent on EC2 if you later move to ECS).
- Use `uvicorn`/`gunicorn` process model with sensible worker settings.
- Health checks on the load balancer target group.

---

## Why not Lambda + API Gateway for this take-home?

AWS Lambda is powerful, but it introduces packaging, cold-start, and architectural constraints that can add complexity and distract from evaluating the application itself—especially for stateful features or long-lived connections. For a take-home, prioritizing a portable containerized service (Render demo, EC2/ALB path, or Cloud Run/App Service) better reflects real-world deployment diversity and keeps the focus on product functionality.

---

## Alternative platforms (cloud-agnostic patterns)

- Azure: Azure API Management -> Private App Service (VNet integration) or Container Apps/AKS. Azure Key Vault for secrets, Log Analytics for observability.
- Google Cloud: API Gateway -> Cloud Run (private with Serverless VPC Access) or GKE. Secret Manager for secrets, Cloud Logging/Monitoring.
- On-prem / customer datacenter: Kubernetes (Ingress + Service + Deployment) or VMs with Nginx reverse proxy and systemd. HashiCorp Vault or your enterprise secret store.

In all cases, the same container image and environment variables are used. Only the ingress and networking layers change.

---

## CI/CD and operations

- CI builds and scans the container image, pushes to a registry (ECR/GHCR/ACR/GCR).
- CD applies Terraform to provision/update infra, then rolls out the new image.
- Use per-environment variables and secret scopes (dev/stage/prod).
- Backups and disaster recovery for databases and object storage.

---

## What to provide when asking for deployment

For future candidates (and teams), prefer asking for:
- A runnable application with a container image and a simple deployment guide that works on any platform.
- Optional cloud-specific reference architecture(s) with a short rationale.
- No requirement for a single cloud provider or service, unless your production constraints demand it.

This approach evaluates real-world readiness and portability without forcing deep provider-specific implementation during a take-home.
