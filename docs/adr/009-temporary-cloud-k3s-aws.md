# ADR-009: Temporary cloud: k3s on one AWS server via Terraform

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Day-to-day the system runs locally (Docker Compose, then k3d). Real cloud experience is one of the goals, and the demo video needs a reachable deployment, but the budget is about $30/month and a cluster does not need to run all the time.

## Decision

Terraform creates a temporary environment on AWS when needed: one EC2 instance running k3s, plus the minimum networking around it. The same Helm charts and Argo CD setup as on local k3d are used. The environment is destroyed after the demo, and recreated from code the next time.

## Alternatives considered

- **Amazon EKS** — the managed, production-like option, but the control plane alone costs about $70/month, above the whole budget.
- **GCP or Azure** — comparable offerings. AWS was chosen because it appears most often in the target job postings.
- **No cloud at all** — free, but leaves the "real cloud experience" gap open.

## Consequences

- **Positive:** Cloud cost is near zero most months and a few dollars in a demo month. Infrastructure as code is the deliverable: the environment can be rebuilt from the repository at any time. k3s is real Kubernetes, so the same manifests run everywhere.
- **Negative:** A single server is a single point of failure, which is acceptable for a demo but not for daily use. Tearing down means restoring the Sealed Secrets key (ADR-008) and re-registering the public URL with Meta and Google. Forgetting to destroy the environment costs money, so a budget alert is part of the Terraform setup.

## Revisit when

The system needs to run in the cloud continuously (for daily use by the team), at which point availability and a managed database matter more than cost.

## References

- `docs/03-architecture.md` — infrastructure and deployment, estimated costs, build layers (Layer 6)
