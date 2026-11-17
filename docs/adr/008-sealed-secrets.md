# ADR-008: Sealed Secrets for Kubernetes secrets

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

From Layer 2 the system is deployed with GitOps: Argo CD syncs the cluster from this public repository. The cluster needs secrets (database passwords, the token encryption key, the Meta token, the stop-code pepper, the LLM key), but nothing secret may ever be committed in plain text (T17).

## Decision

Use Bitnami Sealed Secrets. A controller in the cluster holds a private key; `kubeseal` encrypts a Secret with the matching public key into a `SealedSecret` that is safe to commit. Only the controller can decrypt it, and only inside the cluster.

## Alternatives considered

- **SOPS (with age keys)** — encrypts values inside YAML files and works outside Kubernetes too. Rejected for now because it needs a decryption step wired into Argo CD (a plugin or KSOPS) and key distribution to every place that decrypts.
- **External secret store (AWS Secrets Manager, Vault) with External Secrets Operator** — the production-grade pattern, but it adds a paid service or another system to operate, and the local k3d cluster would still need a different solution.

## Consequences

- **Positive:** Works the same on local k3d and on the temporary cloud cluster. Fits GitOps directly: the repository is the source of truth, secrets included, and Argo CD needs no plugin. Free and open source.
- **Negative:** Secrets are bound to the controller's key. When the cluster is torn down (the cloud cluster is temporary, ADR-009), its key must be backed up and restored, or every secret re-sealed. Rotating a secret means re-sealing and committing.

## Revisit when

The system moves to a long-lived managed cluster where a cloud secret store is cheap and available, or secrets are needed outside Kubernetes.

## References

- `docs/03-architecture.md` — infrastructure and deployment (secrets row)
- `docs/02-threat-model.md` — T17, T21
