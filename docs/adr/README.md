# Architecture Decision Records

Each significant decision is recorded as a short ADR: what was decided, why, what else was considered, and what it costs. New ADRs start from [000-template.md](000-template.md). An accepted ADR is not edited to change its decision; a new ADR supersedes it.

| ADR | Decision | Status |
|---|---|---|
| [001](001-python.md) | Python 3.12+ for all backend services | Accepted |
| [002](002-langgraph.md) | LangGraph for the agent | Accepted |
| [003](003-gmail-polling.md) | Poll Gmail every minute in the MVP | Accepted |
| [004](004-redis-streams.md) | Redis Streams for queues, locks and rate limits | Accepted |
| [005](005-tenant-isolation-rls.md) | Tenant isolation with PostgreSQL RLS and a DB role per service | Accepted |
| [006](006-four-services-by-key-ownership.md) | Four services, split by key ownership | Accepted |
| [007](007-react-frontend.md) | React, TypeScript and Vite for the web app | Accepted |
| [008](008-sealed-secrets.md) | Sealed Secrets for Kubernetes secrets | Accepted |
| [009](009-temporary-cloud-k3s-aws.md) | Temporary cloud: k3s on one AWS server via Terraform | Accepted |
| [010](010-split-oauth-flows.md) | Two OAuth flows; Google tokens land only in `google-gateway` | Accepted |
| [011](011-agent-has-no-db-access.md) | The agent has no database access | Accepted |
| [012](012-outbound-email-from-template.md) | Outbound email is built from a template in `google-gateway` | Accepted |
| [013](013-stop-code-hmac.md) | Emergency stop code stored as an HMAC with a pepper | Superseded by 014 |
| [014](014-stop-code-from-backup-numbers.md) | Emergency stop only from registered backup numbers, plus a web pause | Accepted |
| [015](015-llm-provider-and-model.md) | Claude Haiku 5.5 for the agent, verified on synthetic emails first | Accepted |
| [016](016-token-encryption.md) | Google refresh tokens encrypted with AES-256-GCM, bound to their user | Accepted |
| [017](017-whatsapp-channel.md) | The WhatsApp channel: signed webhook, inbound verification, one template | Accepted |
