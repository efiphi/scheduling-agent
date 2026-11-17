# Sealed Secrets controller

`controller.yaml` is the upstream release manifest of
[Sealed Secrets v0.40.0](https://github.com/bitnami-labs/sealed-secrets/releases/tag/v0.40.0),
verified against the release's SHA-256
(`ac8aabccdd9110430d117501705818115b2ab0993700a9c118d4d42cf4015a17`) before it was copied
here. One change: the controller image is pinned by digest, not only by tag (T20).

The controller holds the private key; `kubeseal` encrypts with its public key. See ADR-008
and `deploy/k3d/seal-secrets.sh`.
