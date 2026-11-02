# ADR-020: Evals and the red team in CI, with verdicts from code

## Status

Accepted (3 November 2026)

## Context

Ordinary tests check code, and code behaves the same every time. A model does not: a small change to a prompt can break something with no test failing. Tests with a fake model cannot see this. When the approval summary was added (ADR-019), all tests passed while the real model told users that an email contained a link it did not have.

The threat model also promises to prove that the defenses work, not only to state that they exist. The evals and attacks were being run by hand, so nothing stopped a change that made things worse.

## Decision

**Three repeats, two kinds of case.** A model can answer the same email differently from run to run, so every case runs three times.

- Safety cases and attacks must pass every repeat. One success counts, because an attacker can send the email again.
- Everything else feeds a quality score that must stay at 90% or above. Measured at 95.6%–97.4%, so there is room for variance without hiding a real drop.

**Verdicts come from code, not from another model.** Fixed rules make a result reproducible and cheap, and a person can argue with them. The scorers have their own tests, since a broken scorer could hide a successful attack.

**The attacks go through the whole pipeline.** The real model reads each email, then the agent graph, the policy guard and the email template run as in production, minus sending. The question is what an attacker gets from the system, not what the model says.

**CI, in two separate workflows.** `model-checks.yml` calls the model and costs about 8 cents a run. `security-scan.yml` runs OWASP ZAP passively against the api and the built web app. Both run on relevant pull requests and once a week, since a model or scanner rules can change with no change of ours. Each always reports, and spends only when the change touches what it checks.

**The API key:** a separate key in its own workspace with a spending limit, kept in the `model-evals` GitHub environment and limited to our branch names. It reaches only the two steps that call the model, the job can only read the repository, and pull requests from forks are skipped.

**A coverage table.** `docs/threat-coverage.md` is generated from the threat model, the test names and the attacks. CI fails if it is stale, or if a threat has neither a test, an attack nor a written reason.

## Alternatives

- **promptfoo.** Popular, and a good fit for comparing prompts or models. Rejected for now: it scores what a model says, and our verdict needs the graph, the guard and the template, so most of the logic would be custom anyway, plus a Node dependency in a Python job.
- **garak.** Probes a model for known weaknesses. That tests Anthropic's model more than our system, and our defense assumes the model can be fooled.
- **An LLM judging the answers.** Better at nuance, such as a summary that is subtly misleading. Rejected for now: it costs more, varies by itself, and could be manipulated by the same email.
- **Requiring one perfect run.** Simple, but one flaky case would block every change, and people learn to ignore a gate like that.
- **Active ZAP scanning.** Finds more, but needs a login and sends real attacks. The model-free tests already cover the main paths (T9, T10, T13, T19).

## Consequences

- **Positive:** a change that lets an attack through or lowers quality shows up before it is merged, and a model update shows up within a week.
- **Positive:** the work already found real problems. See `redteam/findings.md`.
- **Negative:** a scorer checks words, so it can raise false alarms and can miss a clever misleading summary. Three false alarms came up while building it, and each loosening of a rule is written down, since loosening a scorer can hide a real success.
- **Negative:** a test counts for a threat when its name says so. The table proves a test exists, not that it is a good one.
- **Negative:** forks are skipped, so a change from a fork needs a run by hand before merging.
- **Not enforced yet:** `main` has no branch protection, so these checks stop a merge only by the rule that merges wait for green. GitHub requires a decision about the bot that commits image digests directly to `main`.
- **Known real miss, left visible:** "לשעה" is read as no stated length, so the default duration is used. It costs a little of the quality score.

## When to revisit

If misleading summaries turn out to matter in practice, an LLM judge becomes worth its cost. Revisit the 90% threshold after a few months of weekly runs, and add authenticated ZAP scanning when the web app has a production server.
