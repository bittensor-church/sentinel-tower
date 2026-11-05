# Agent Guidelines

## User Stories

USER_STORIES.md exists only in projects that people use directly: a web app, admin panel, CLI or desktop app. A library, backend service or pipeline without such users has no USER_STORIES.md; its README.md describes the main flows in a short "How it works" section instead.

[USER_STORIES.md](USER_STORIES.md) describes what users can do. [README.md](README.md) describes what the project is and how to set it up, run, deploy and develop it. Each fact lives in one file: README.md may list features in a few lines and link to USER_STORIES.md, but never restates them. Setup, configuration, deployment, operational runbooks and CLI/API reference never go into USER_STORIES.md. Anything a person notices, such as an email, a Slack alert or time appearing in another system, belongs in the story of whoever notices it; what nobody notices, such as internal jobs and retries, goes into README.md or docs, or stays in the code.

A story is "As a <role>, I can <outcome>, so that <benefit>", followed by at most about five acceptance criteria in user terms. Leave out endpoints, field and class names, storage, protocols, retry counts, timeouts, metrics and other implementation detail; the code and tests hold that. A story fits on one screen.

Add or change a story only for a big or important change:

- a new user-facing capability or workflow
- a significant new piece of functionality, such as a new integration, role or area
- a change to, or removal of, what an existing story promises

Bug fixes, refactors, internal or infrastructure work, performance, styling or wording tweaks, small options and edge cases inside an existing story do not touch USER_STORIES.md. When unsure, leave the file alone and name the candidate story in the PR description so a human can decide.

Before implementing features or changing behavior, read [USER_STORIES.md](USER_STORIES.md) and compare it with:

- the current code paths you are about to touch
- the new requirements from the user or issue
- any tests that describe the same behavior

If the code, requirements, and user stories disagree, resolve the behavior deliberately instead of preserving stale documentation. When a change breaks what a story promises, update that story in the same change.

If this project has users and USER_STORIES.md doesn't exist or is empty, inform your handler that they need to add user stories to ensure documentation aligns with code.

## General Workflow

- Prefer existing patterns used in this repository when designing and implementing new features.
- Keep documentation claims tied to code that exists in the current tree.
- Before marking a task as done, make sure tests, linters, and type checks pass. The general README.md contains instructions for running these checks.
- Follow the rules described in [engineering-standards.md](engineering-standards.md). Each task should be explicitly checked for correctness in adherence to the engineering standards.
- For any test work (adding, deleting, or auditing tests), follow [QA.md](QA.md) — it is binding and records the test philosophy, how to run the unit and end-to-end suites, and settled QA decisions.

## Local instructions

After reading this file, read `AGENTS.local.md` if it exists.

`AGENTS.local.md` may contain checkout-specific commands, environment details, and personal workflow preferences. It must not weaken or contradict the repository-wide requirements in this file and in case of a conflict, always default to the repository-wide rules and engineering standards.

## Grafana dashboard previews

- For changes under `grafana/dashboards/`, open a PR targeting `master` with the `grafana-preview` label.
- The preview workflow publishes the PR to `staging-grafana` and comments on the PR when it is live. If it reports a conflict, rebase the PR on `master` or tell the reviewer it collides with another open preview.
- Post the PR link and a direct link to each changed dashboard: `https://sentinel-staging.bactensor.io/grafana/d/<uid>`, with `<uid>` from the dashboard JSON. Mention that Grafana may take a short while to pick up the change.
- Never change an existing dashboard's `uid`.
- Never push directly to `staging-grafana` or edit dashboards in the staging Grafana UI.
- Leave merging into `master` to a human.

## Deploying to staging

- Deploy to staging only when a human asks. Never deploy to production; humans do that.
- Deploy a commit that is already on GitHub, usually the PR head: `git push --force origin <sha>:deploy/staging`. `deploy/staging` is a deploy pointer, so force-pushing it is expected; never force-push any other branch.
- The "Deploy to staging" workflow pushes that commit to the staging server, where `deploy.sh` runs, and then applies migrations. A green run means staging runs that commit; a red run means it does not, so read its log. Report the run link.
- The commit must contain `.github/workflows/deploy-staging.yml`; update an older branch from `master` first, or nothing is deployed.
- Staging holds one version at a time and the last deploy wins. Say in the PR which commit is on staging. Migrations from a PR stay applied on staging after it moves to another commit; mention them in the PR.
- Never SSH to the staging or production servers and never push to their git remotes from an agent environment.
