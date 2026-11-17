# ADR-018: Observability with OpenTelemetry and the Grafana stack, inside the cluster

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

Until Layer 3 the system was a black box: when an email got no reply there was no quick way to tell whether the filter skipped it, the agent failed, or a queue was stuck. A silent failure (E13) once went unnoticed for a day (the agent restarted 91 times, #35). The design (`docs/03-architecture.md`, observability) asks for one trace per email across services, metrics, central logs and agent run tracing.

Constraints: the data is personal (email senders, user ids) and partly attacker-written (T1, T22); the repository and its images are public; the budget is ~$30/month (`CLAUDE.md`); the machine has ~8 GB for Docker.

## Decision

OpenTelemetry in every service, sending over OTLP to Grafana Alloy in the cluster, which writes traces to Tempo, metrics to Prometheus and logs to Loki; Grafana shows them. Everything runs in the k3d cluster, deployed by Argo CD, and nothing leaves the machine.

- **Traces:** one email is one trace. Redis messages carry a `traceparent`; the pending action stores it (migration 0006, format-checked) so the executor continues the trace after approval. Context from HTTP headers is ignored, so outsiders cannot choose which trace our spans join. Paths with secrets in their query strings (both OAuth callbacks, the WhatsApp handshake) are never traced.
- **Agent runs:** OpenTelemetry GenAI conventions (model, tokens, stop reason), one span per LangGraph step with what code decided, cost per run. Never the prompt, the email or the model's output; the email's length only, not its hash (a short reply could be guessed back from a hash).
- **Logs:** one JSON object per line (`shared.log`), with the trace id, redaction of known token shapes as a second line of defense, and no access log. JSON also closes log injection: a line break in an email subject cannot forge a log line.
- **Metrics:** pushed over OTLP, so no service opens a `/metrics` port. Attributes are low-cardinality and never personal; an AST test over the code enforces the allowed list.
- **Retention:** logs and metrics 7 days, traces 3 days.
- **Access:** Grafana has no Ingress, only `kubectl port-forward`, with a sealed admin login; dashboards and alert rules are provisioned from git and read-only in the UI.

## Alternatives considered

- **Langfuse (cloud)** for agent tracing: a purpose-built LLM tracing UI that shows up in job postings, with a free tier. Rejected for now: agent runs would go to an external service, and those runs are derived from strangers' emails.
- **Langfuse (self-hosted)**: keeps data local, but v3 needs ClickHouse, Redis and object storage besides Postgres, more than 8 GB comfortably holds next to the rest.
- **Prometheus scraping a `/metrics` endpoint on each service:** the classic pull model. Rejected: every service would open a port, and the CronJob runs (`gmail-poll`) live too briefly to be scraped. Push over OTLP needs one NetworkPolicy to one collector.
- **kube-prometheus-stack (Prometheus Operator):** the common all-in-one. Heavier (operator, CRDs, Alertmanager, node-exporter), and its CRDs would need cluster-wide permissions in Argo CD. The plain charts are enough for one node.
- **A log agent on each node reading `/var/log/pods`:** the usual setup, but it needs root and host mounts. Alloy reads pod logs through the Kubernetes API instead, without either.

## Consequences

- **Positive:** one view from email to meeting; failures alert instead of hiding (E13); spend is visible against the cap (T24); no cost, no data leaves the machine; the same OpenTelemetry instrumentation would work with any backend later, Langfuse included.
- **Negative:** ~1.5 GB more memory in the cluster; five more components to keep up to date; no alert notifications yet (they show only in Grafana, since no email or chat channel is configured); LogQL and TraceQL queries are not syntax-checked in CI (PromQL is, with promtool). The observability namespace does not restrict egress yet.

## Revisit when

The system moves to a long-lived cloud environment (managed Grafana or a hosted backend may be cheaper to run than to operate), agent evaluation needs dataset and prompt-version features that Langfuse provides (Layer 4), or a notification channel is chosen for alerts.

## References

- `docs/03-architecture.md` — observability and detection layer
- `docs/02-threat-model.md` — T1, T16, T20, T22, T24, E13
- ADR-004 (Redis Streams), ADR-011 (the agent has no database access), ADR-015 (model choice)
