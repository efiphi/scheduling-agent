# ADR-022: Detection rules as code, alerts to WhatsApp

## Status

Accepted (17 November 2026)

## Context

The services already wrote security events to `app.security_events`, for example a wrong stop code, a forged button or a plan for someone else's task. Nothing watched them. Alerts existed only inside Grafana, so they reached nobody, and when Grafana itself kept restarting, nobody knew that alerts had stopped (E13).

Layer 5 makes the agent watched like a SOC watches a system: rules built from the threat model, tested like code, and alerts that reach the owner.

## Decision

**Signals without database access.** Every security event is also counted (`sa_security_events_total{kind}`) and logged, next to the database row (`shared/security.py`). Rules read the counter, so Prometheus and Grafana need no access to Postgres, which Row-Level Security protects. The kinds are a fixed list tied to threats. Anything else is counted as `unlisted`, so input cannot create a series per value (T22), and a test fails if the code writes a kind missing from the list.

**Rules as code, with unit tests.** `detections/rules.yml` holds one rule per threat, plus watchdog rules for the monitoring stack itself. Every rule has a promtool unit test that makes it fire, and some check it stays quiet. A weakened threshold fails CI. The deployed Helm values are generated from the tested file, and a test fails if they drift.

**Prometheus watches Grafana.** Grafana cannot report its own outage, so Prometheus rules check that Grafana, Alloy and Loki are up, that monitoring pods are not restarting, and that the services still send metrics.

**Alertmanager to WhatsApp, through a relay pod.** Alertmanager receives every alert, from these rules and from Grafana, and posts them to `alert-relay`:

- **Same image, separate pod.** The relay runs from the api image, the only holder of the Meta token, so no new service holds it. If the api pod falls over, alerts still go out.
- **Who may call it:** only Alertmanager, by a NetworkPolicy from the monitoring namespace and a bearer token compared in constant time.
- **What it sends:** the rule's fixed Hebrew summary and severity. Nothing from an event, an email or a message reaches it, and the text is checked like any shown text.
- **How it delivers:** inside Meta's 24-hour window a plain message. Outside it, the approved `system_alert` template, for firing alerts only, since each costs money.
- **How many:** Alertmanager repeats a still-firing alert every 12 hours, not every few minutes, and the relay caps messages at 10 an hour (T24).

## Alternatives

- **Grafana reads `security_events` from Postgres.** The data is already there, but it means a database role for the monitoring stack, and SQL alert rules cannot be unit-tested in CI.
- **Telegram, recommended at first.** Free and independent of our code. The owner chose WhatsApp, where the agent already talks to them, accepting the template cost and the dependence on the Meta number (T27).
- **An external dead-man's switch.** It would catch the whole machine going down, but this cluster runs on a laptop that is often off, so it would mostly raise false alarms. It comes back with the cloud (Layer 6).
- **Falco for container behavior.** It needs kernel access, which Docker Desktop on a Mac may not give. Deferred to the Linux server of Layer 6.

## Consequences

- **Positive:** an attack in the threat model that leaves a security event now reaches the owner's phone. `deploy/k3d/test-detections.sh` proves the path end to end with a harmless forged webhook.
- **Positive:** a rule is reviewed and tested like code, and its test is named after its threat in the coverage table.
- **Negative:** if Prometheus, Alertmanager or the Meta number is down, alerts stop, and nothing outside the cluster notices. Accepted until Layer 6.
- **Negative:** Alertmanager keeps no state between restarts (no persistence), so a silence is lost on restart. Fine for one owner.
- **Negative:** the rules see only what the code records as a security event. An attack that leaves no event, such as a quietly misleading summary (T31), is not detected here.
