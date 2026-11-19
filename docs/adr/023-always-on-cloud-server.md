# ADR-023: An always-on cloud server: one spot instance that heals itself

## Status

Accepted (19 November 2026). Supersedes [ADR-009](009-temporary-cloud-k3s-aws.md), which planned a temporary environment destroyed after each demo.

## Context

ADR-009 planned a cloud environment that would be created for a demo and destroyed after it. Two things changed. The owner wants to use the agent every day, not only in a demo: that needs a stable public address for Meta's webhook and Google's OAuth callbacks, instead of a tunnel that dies when the laptop sleeps. And the detections of Layer 5 left gaps that only an always-on Linux server closes: an outside check, and Falco, which needs kernel access a laptop's Docker does not give.

The budget did not change: about $30 a month in total, with the language model and WhatsApp included.

## Decision

**One server, always on, on spot.** k3s on a single ARM instance in eu-central-1, in an Auto Scaling group of one, 100% spot, capped at $0.03 an hour (`spot_max_price`). Above the cap AWS gives no server rather than a bigger bill. The instance types are m6g/m8g.medium (one full core, 4 GiB).

- **It heals itself.** When AWS takes the instance back, the group starts another. It does not move on AWS's earlier "rebalance" warnings: one server that owns its data volume cannot overlap with its replacement, so each warning only cost a full move (three in an hour on 19.11). The new one takes over the Elastic IP and the data volume (k3s's whole state, encrypted gp3), installs the pinned k3s binary checked by SHA-256, and becomes the same cluster under the same node name. This happened for real on 19.11: from the warning to the site answering again took about 6 minutes, with nobody involved.
- **The cold start is staged.** On one core, the ~45 pods that come back at once starved each other, failed their health checks and were restarted in a loop that never settled. `sa-boot-stagger` holds the monitoring tools and Argo CD until the application is up, retries every step through k3s restarts, and always releases Argo CD on exit (it once did not, and the monitoring tools stayed at zero). Startup probes give every process 5 minutes before liveness counts.
- **Fitted to 4 GiB.** The cloud reserves 128Mi and 10m CPU per Python process (they use about 80Mi), keeps every limit, and rolls out one pod at a time (`maxSurge: 0`). Argo CD's unused parts are off. Pods may use the 2 GiB swap within limits (Kubernetes' LimitedSwap, a share per pod in proportion to its request), so a memory peak slows pods down instead of stalling them all: adding Falco once left 133Mi free at 98% memory pressure. Falco exports only the counter the rules read.

**No open port but 80 and 443.** No SSH: Session Manager, through the owner's AWS login. The Kubernetes API stays closed and is reached through a Session Manager port forward (`deploy/aws/kube.sh`). IMDSv2 only, one hop, so a pod cannot borrow the instance's role.

**One public name, HTTPS only.** `agent.efi-agent.dev`, a DNS record managed by Terraform (Cloudflare, not proxied). Traefik gets a Let's Encrypt certificate and only redirects plain HTTP. The web app is served as static files from nginx at `/`, the api under `/api` (stripped by a Traefik middleware, so the browser sees one origin), and the Google callback and the WhatsApp webhook on their paths only. A CAA record names Let's Encrypt.

**GitOps from the same branch as k3d.** The cloud's Argo CD deploys the `deploy/k3d` branch (ADR-021), so the same tested images, with `environments/aws/values.yaml` on top. Its Secrets are sealed with its own key. Exactly one cluster polls the mailbox and sends alerts (a test checks); k3d stays for local work.

**Backups off the server.** Every night a systemd timer on the host runs `pg_dump` into a private, encrypted, versioned S3 bucket kept 14 days. The server may only write there; only the owner's admin login may read. A restore was tested into an isolated database: same row counts, Row-Level Security intact.

**Watched from inside and outside.**

- **Falco** (modern eBPF, kernel capabilities only, no downloads while it runs) feeds a counter per rule to the existing detection rules (ADR-022): an interactive shell in a container or any rule of priority Warning or worse goes to the owner's WhatsApp.
- **Daily security updates** (dnf-automatic, from the latest Amazon Linux release), and a weekly reboot only when an update needs one.
- **An outside check** from GitHub Actions every 30 minutes: the api answers, the security headers are there, HTTP only redirects, the certificate has 14 days left, and only 80 and 443 are open. A failed run emails the owner.

**Everything as code.** Terraform for the state bucket and budget (bootstrap), the server, backups and DNS; CI plans every stack on pull requests with a read-only role over OIDC, with no stored AWS keys. `terraform destroy` in `infra/terraform/cloud` stops every charge.

## Alternatives

- **Keep ADR-009's temporary environment.** Cheapest, but no daily use, no stable webhook address, and Falco and the outside check would rarely run.
- **On-demand instead of spot.** About $34 a month for the server alone: over budget. Spot with self-healing costs a few minutes per interruption.
- **t4g.medium (burstable, 2 vCPU, about $20 in total).** The first choice. This account cannot use "unlimited" CPU credits, and in "standard" mode every new spot instance starts with no credits at 20% of each core, where k3s failed to start. A request to AWS Support to enable "unlimited" is open; with it, t4g can come back.
- **A larger server (8 GiB).** Would remove the staged start and the memory fitting, at about $31 a month for the server alone.
- **Managed Kubernetes (EKS).** The control plane alone costs more than the whole budget.
- **Cloudflare's proxy in front.** Hides the address and absorbs attacks, but Cloudflare would end TLS and see the traffic in the clear. Can be revisited.

## Consequences

- **Positive:** the agent runs every day at a fixed address, with no laptop involved, and recovers from a spot interruption by itself.
- **Positive:** the gaps ADR-022 left are closed: an outside dead-man's switch, runtime detection with Falco, and backups off the server.
- **Negative:** one server is one point of failure. A spot interruption is a few minutes of downtime; an AZ outage is longer (the data volume lives in one AZ).
- **Negative:** about $24–27 a month for the cloud, more than planned, which leaves little for the model and WhatsApp. Back to about $20 if t4g becomes possible.
- **Negative:** the staged start and the memory fitting are workarounds for a small server, and they add moving parts that had to be debugged on real failures.
- **Negative:** Falco watches the host only from 6.6 on; what happened before it was installed is not covered.
