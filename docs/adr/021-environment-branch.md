# ADR-021: Image digests on their own branch, so main can be protected

## Status

Accepted (17 November 2026)

## Context

After every green build of `main`, a CI job writes the new image digests into the k3d environment's values, and Argo CD deploys them. That job pushed straight to `main`.

Layer 4 added checks that should stop a bad change, but `main` had no branch protection, so they stopped a merge only by habit. A rule requiring the checks would also block the bot's direct push, and GitHub does not let a personal repository exempt GitHub Actions from a ruleset.

## Decision

The digests live on their own branch, `deploy/k3d`, which holds that one file and nothing else.

- **The bot** checks out `deploy/k3d`, rewrites the digests and pushes there. It never writes to `main`, and a test checks this.
- **Argo CD** uses two sources: the chart and everything else from `main`, and the values file from `deploy/k3d` (`ref: env`).
- **`main`** gets a ruleset with no exceptions: every CI check must pass, no force pushes and no deletion.

`main` keeps a copy of the values file for CI to lint and render the chart with. Its digests are left stale on purpose, and a comment says so.

## Alternatives

- **A deploy key exempt from the ruleset.** The smallest change, but a long-lived write key stored in GitHub, in place of a token that lives only for the job.
- **A GitHub App of our own, exempt from the ruleset.** The route GitHub points to, but an app and its key to create and look after.
- **No protection.** No work, and the checks stay advice.

## Consequences

- **Positive:** nothing reaches `main` without green checks, the bot included. No new secret.
- **Positive:** a compromised bot can change which images run, not the code or the chart. It can only point at images, and only at digests CI built from green commits on `main`.
- **Negative:** the bot's token can still write to `deploy/k3d`, which has no protection. Someone who took over that job could point the cluster at another image. Signing images and checking signatures in the cluster (cosign) would close this; it is a follow-up.
- **Negative:** deployments no longer show up in `main`'s history. They are in `deploy/k3d`'s history, one commit per deployment.
- **Negative:** what runs is spread over two branches, so a reader has to know where to look. The values file on `main` says so.
